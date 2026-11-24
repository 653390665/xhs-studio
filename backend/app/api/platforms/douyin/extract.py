from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.tasks import paginated
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import DouyinExtractJob, DouyinWork, User
from backend.app.services.douyin_corpus_service import DouyinCorpusError, import_job_as_corpus
from backend.app.services.douyin_extract_service import (
    SOURCE_TYPES,
    DouyinExtractError,
    allowed_output_path,
    create_job,
    faster_whisper_device_plan,
    is_running,
    launch_job,
    list_jobs,
    media_tool,
    run_job,
    serialize_job,
    serialize_work,
)

router = APIRouter(prefix="/douyin/extract", tags=["douyin-extract"])


class CreateJobRequest(BaseModel):
    source_type: Literal["manifest", "links", "profile"] = "manifest"
    source: str = Field(min_length=1, max_length=200_000)
    account_name: str = Field(default="", max_length=128)
    limit: int = Field(default=0, ge=0, le=2000)
    fetch_media: bool = True
    transcribe: bool = True
    keep_media: bool = False
    auto_start: bool = True
    # 同一作品之前采集过就跳过；需要重跑（例如换用新的转写实现）时置 True。
    force: bool = False


class ImportCorpusRequest(BaseModel):
    """一条采集任务的文稿导入哪个对标集。"""

    name: str = Field(default="", max_length=128)
    # 抖音口播短片的体裁比小红书笔记集中：这里默认「观点」，因为多数是
    # 「一个结论 + 三条理由」的讲解，而不是亲历故事。混体裁会让规则互相抵消。
    genre: Literal["experience", "list", "opinion", "event", "recruit"] = "opinion"
    role: Literal["baseline", "negative", "neutral"] = "baseline"
    platform_account_id: Optional[int] = None
    # 重新采集同一作者时指向已有对标集，避免每跑一次就多出一个同名集。
    set_id: Optional[int] = None


def _get_owned_job(db: Session, user: User, job_id: int) -> DouyinExtractJob:
    job = db.get(DouyinExtractJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提取任务不存在")
    return job


@router.get("/meta")
def extract_meta(current_user: User = Depends(get_current_user)):
    command = os.getenv("DOUYIN_EXTRACT_ASR_CMD", "").strip()
    if command:
        engine = "external-command"
        ready = True
        hint = "已配置外部转写命令"
    elif importlib.util.find_spec("faster_whisper"):
        engine = "faster-whisper"
        ready = True
        hint = "已安装 faster-whisper，首次运行会加载模型"
        device = os.getenv("DOUYIN_EXTRACT_WHISPER_DEVICE", "").strip().lower()
        cpu_only = os.getenv("DOUYIN_EXTRACT_WHISPER_CPU_ONLY", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if device == "cpu" or cpu_only:
            hint = "已安装 faster-whisper（CPU 模式），首次运行会加载模型"
        elif device == "cuda":
            hint = "已安装 faster-whisper（GPU 模式），首次运行会加载模型"
        else:
            hint = "已安装 faster-whisper；无可用 GPU 时会自动回退 CPU"
    elif shutil.which("whisper"):
        engine = "whisper-cli"
        ready = True
        hint = "已安装 whisper CLI"
    else:
        engine = ""
        ready = False
        hint = (
            "未安装转写引擎。可执行「pip install faster-whisper」，"
            "或设置 DOUYIN_EXTRACT_ASR_CMD 指向你的转写命令。"
        )
    model_size = os.getenv("DOUYIN_EXTRACT_WHISPER_MODEL", "small")
    return {
        "asr_ready": ready,
        "engine": engine,
        "hint": hint,
        "ffmpeg": bool(media_tool("ffmpeg")),
        "ffprobe": bool(media_tool("ffprobe")),
        "ffmpeg_path": media_tool("ffmpeg") or "",
        "ffprobe_path": media_tool("ffprobe") or "",
        "model_size": model_size if engine == "faster-whisper" else "",
        "device_plan": [
            device for device, _ in faster_whisper_device_plan()
        ]
        if engine == "faster-whisper"
        else [],
        "source_types": list(SOURCE_TYPES),
        "profile_note": "抖音主页有风控，直采可能失败；清单和分享链接更可靠。",
    }


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_extract_job(
    payload: CreateJobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        job = create_job(
            db,
            current_user,
            source_type=payload.source_type,
            source=payload.source,
            account_name=payload.account_name,
            limit=payload.limit,
            fetch_media=payload.fetch_media,
            transcribe=payload.transcribe,
            keep_media=payload.keep_media,
            force=payload.force,
        )
    except DouyinExtractError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.auto_start:
        launch_job(job.id)
    db.refresh(job)
    return serialize_job(job)


@router.get("/jobs")
def list_extract_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_jobs(db, current_user.id)
    return paginated([serialize_job(row) for row in rows], page, page_size)


@router.get("/jobs/{job_id}")
def get_extract_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    works = list(
        db.scalars(
            select(DouyinWork)
            .where(DouyinWork.job_id == job.id)
            .order_by(DouyinWork.id.asc())
            .limit(2000)
        ).all()
    )
    payload = serialize_job(job, include_audit=True)
    payload["works"] = [serialize_work(work) for work in works]
    payload["source_preview"] = (job.source or "")[:500]
    return payload


@router.post("/jobs/{job_id}/run")
def run_extract_job(
    job_id: int,
    retry_failed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    if is_running(job.id):
        return serialize_job(job)
    if job.status == "completed" and not retry_failed:
        return serialize_job(job)
    if job.status == "running":
        job.status = "draft"
    db.commit()
    if retry_failed:
        job = run_job(db, job, retry_failed=True)
    else:
        launch_job(job.id)
    db.refresh(job)
    return serialize_job(job)


@router.post("/jobs/{job_id}/run-sync")
def run_extract_job_sync(
    job_id: int,
    retry_failed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synchronous runner used by tests and CLI-style automation."""
    job = _get_owned_job(db, current_user, job_id)
    job = run_job(db, job, retry_failed=retry_failed)
    return serialize_job(job, include_audit=True)


@router.post("/jobs/{job_id}/pause")
def pause_extract_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    if job.status == "running":
        job.status = "paused"
        db.commit()
        db.refresh(job)
    return serialize_job(job)


@router.get("/jobs/{job_id}/files")
def list_extract_files(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    return {"items": serialize_job(job, include_audit=True)["files"]}


@router.get("/jobs/{job_id}/file")
def download_extract_file(
    job_id: int,
    path: str = Query(min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    try:
        target = allowed_output_path(job, path)
    except DouyinExtractError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return FileResponse(target, filename=target.name)


@router.post("/jobs/{job_id}/corpus", status_code=status.HTTP_201_CREATED)
def import_extract_job_corpus(
    job_id: int,
    payload: ImportCorpusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把已转写的抖音作品导入对标集，供证据蒸馏使用。

    采集任务产出的是文稿文件，蒸馏读的是对标集；这一步把两者接上，所以整条
    「采集 → 转写 → 蒸馏」不必再靠脚本串。
    """
    job = _get_owned_job(db, current_user, job_id)
    try:
        result = import_job_as_corpus(
            db,
            current_user,
            job,
            name=payload.name,
            genre=payload.genre,
            role=payload.role,
            platform_account_id=payload.platform_account_id,
            set_id=payload.set_id,
        )
    except DouyinCorpusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return result


@router.post("/jobs/{job_id}/open-folder")
def open_extract_folder(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, current_user, job_id)
    root = Path(job.output_dir) if job.output_dir else None
    if root is None or not root.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="输出目录还不存在")
    try:
        if sys.platform == "win32":
            os.startfile(str(root))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"无法打开目录：{exc}",
        ) from exc
    return {"ok": True, "path": str(root)}
