"""Browser-extension capture endpoint.

The extension runs inside douyin.com, reads the author's work cards and fetches
each detail in the page context (the only place the request survives Argus), then
posts the raw list here. This endpoint applies the sampling policy and creates a
normal extraction job.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.config import PROJECT_ROOT
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.services.capture_service import CaptureError, create_capture_job
from backend.app.services.capture_token_service import resolve_user
from backend.app.services.douyin_extract_service import launch_job

router = APIRouter(prefix="/douyin/capture", tags=["douyin-capture"])


def extension_dir() -> Path:
    """Location of the unpacked Chrome extension.

    Source runs use the repository folder. The packaged app ships the same
    folder under ``_internal/browser-extension`` via ``packaging/app.spec``, so
    the path is consistent in both modes.
    """
    return PROJECT_ROOT / "browser-extension" / "douyin-capture"


def _extension_meta(path: Path) -> dict:
    meta: dict = {}
    manifest = path / "manifest.json"
    if manifest.is_file():
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    return {
        "exists": path.is_dir(),
        "path": str(path),
        "name": meta.get("name") or "XHS Studio 抖音采集插件",
        "version": str(meta.get("version") or ""),
    }


@router.get("/extension")
def capture_extension_info(current_user: User = Depends(get_current_user)):
    """Where to find the unpacked extension shipped with this app."""
    return _extension_meta(extension_dir())


@router.post("/extension/open")
def open_capture_extension_folder(current_user: User = Depends(get_current_user)):
    """Open the extension folder so Chrome can load it unpacked."""
    path = extension_dir()
    if not path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="安装包缺少抖音采集插件目录，请重新安装或联系提供者",
        )
    if os.name != "nt":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="当前系统不支持自动打开目录，请手动定位插件目录",
        )
    os.startfile(str(path))  # type: ignore[attr-defined]
    return {"ok": True, "path": str(path)}


class CaptureWork(BaseModel):
    work_id: str = Field(min_length=1, max_length=64)
    desc: str = Field(default="", max_length=2000)
    duration: float = 0
    play: str = Field(default="", max_length=4000)
    likes: int = 0
    create_time: int = 0


class CaptureRequest(BaseModel):
    author_name: str = Field(default="", max_length=128)
    author_sec_uid: str = Field(default="", max_length=128)
    works: list[CaptureWork] = Field(min_length=1, max_length=200)
    min_duration: int = Field(default=15, ge=0, le=600)
    max_duration: int = Field(default=75, ge=1, le=3600)
    auto_start: bool = True


def capture_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    raw = ""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            raw = value.strip()
    user = resolve_user(db, raw)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="采集令牌无效或已撤销",
        )
    return user


@router.get("/whoami")
def capture_whoami(current_user: User = Depends(capture_user)):
    """Used by the extension popup to verify a pasted token."""
    return {"user_id": current_user.id, "username": current_user.username}


@router.post("", status_code=status.HTTP_201_CREATED)
def capture_works(
    payload: CaptureRequest,
    current_user: User = Depends(capture_user),
    db: Session = Depends(get_db),
):
    if payload.min_duration > payload.max_duration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="最小时长不能大于最大时长",
        )
    try:
        job, plan = create_capture_job(
            db,
            current_user,
            author_name=payload.author_name,
            author_sec_uid=payload.author_sec_uid,
            works=[work.model_dump() for work in payload.works],
            min_duration=payload.min_duration,
            max_duration=payload.max_duration,
        )
    except CaptureError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.auto_start:
        launch_job(job.id)
    return {
        "job_id": job.id,
        "accepted": len(plan["items"]),
        "total": plan["total"],
        "skipped_existing": plan["skipped_existing"],
        "filtered_duration": plan["filtered_duration"],
        "filtered_duplicate": plan["filtered_duplicate"],
        "filtered_invalid": plan["filtered_invalid"],
        "author_name": job.account_name,
    }
