from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.ai import (
    _image_model_context,
    _text_model_context,
    get_image_ai_client,
    get_text_ai_client,
)
from backend.app.api.publish import serialize_publish_job
from backend.app.core.database import SessionLocal, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AgentRun, AgentStep, AiDraft, PlatformAccount, PublishJob, User
from backend.app.services.agent_service import (
    _workbench_overview,
    agent_capabilities,
    execute_agent_run,
    plan_agent_run,
    run_agent,
)
from backend.app.services.ai_service import ImageAiClient, TextAiClient

router = APIRouter(prefix="/agent", tags=["agent"])

# Tests switch this off to run the loop synchronously inside the request.
_ASYNC_ENABLED = True


class AgentImage(BaseModel):
    file_name: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=2000)


class AgentPlanStep(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=200)


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=1000)
    account_id: int | None = None
    # 兼容旧客户端：部分调用方按序列化输出的字段名传 platform_account_id。
    platform_account_id: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    images: list[AgentImage] = Field(default_factory=list, max_length=9)
    plan: list[AgentPlanStep] = Field(default_factory=list, max_length=8)


class AgentPlanRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=1000)
    account_id: int | None = None
    platform_account_id: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


def _serialize_step(step: AgentStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "step_index": step.step_index,
        "tool": step.tool,
        "args": step.args or {},
        "status": step.status,
        "output": step.output or {},
        "error": step.error,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
    }


def serialize_run(db: Session, run: AgentRun) -> dict[str, Any]:
    steps = db.scalars(
        select(AgentStep)
        .where(AgentStep.run_id == run.id)
        .order_by(AgentStep.step_index.asc(), AgentStep.id.asc())
    ).all()
    return {
        "id": run.id,
        "platform_account_id": run.platform_account_id,
        "goal": run.goal,
        "status": run.status,
        "summary": run.summary,
        "error": run.error,
        "steps": [_serialize_step(step) for step in steps],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _execute_in_background(
    run_id: int,
    user_id: int,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    images: list[dict[str, Any]],
    image_client: ImageAiClient | None,
    image_config: Any,
    image_api_key: str,
    plan: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        run = db.get(AgentRun, run_id)
        user = db.get(User, user_id)
        if run is None or user is None:
            return
        execute_agent_run(
            db,
            user,
            run,
            client,
            model_config,
            api_key,
            images=images,
            image_client=image_client,
            image_config=image_config,
            image_api_key=image_api_key,
            plan=plan,
            context=context,
        )
    finally:
        db.close()


@router.get("/capabilities")
def get_capabilities(current_user: User = Depends(get_current_user)):
    """Static capability catalog used by the novice-friendly agent page."""
    return agent_capabilities()


@router.get("/overview")
def get_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _workbench_overview(db, current_user)


@router.post("/plan")
def plan_run(
    payload: AgentPlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    account_id = payload.account_id or payload.platform_account_id
    if account_id is not None:
        account = db.get(PlatformAccount, account_id)
        if account is None or account.user_id != current_user.id:
            account_id = None
    try:
        return plan_agent_run(
            db,
            current_user,
            payload.goal.strip(),
            text_ai_client,
            model_config,
            api_key,
            account_id=account_id,
            context=payload.context,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"计划生成失败：{exc}",
        ) from exc


@router.post("/runs")
def create_run(
    payload: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    account_id = payload.account_id or payload.platform_account_id
    if account_id is not None:
        account = db.get(PlatformAccount, account_id)
        if account is None or account.user_id != current_user.id:
            account_id = None

    image_config, image_key = None, ""
    try:
        image_config, image_key = _image_model_context(db, current_user)
    except HTTPException:
        pass
    image_snapshot = None
    if image_config is not None:
        image_snapshot = SimpleNamespace(
            id=image_config.id,
            model_name=image_config.model_name,
            base_url=image_config.base_url,
        )

    run = AgentRun(
        user_id=current_user.id,
        platform_account_id=account_id,
        goal=payload.goal.strip(),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    snapshot = SimpleNamespace(
        id=model_config.id,
        model_name=model_config.model_name,
        base_url=model_config.base_url,
    )
    images = [image.model_dump() for image in payload.images]
    plan = [step.model_dump() for step in payload.plan]
    if _ASYNC_ENABLED:
        thread = threading.Thread(
            target=_execute_in_background,
            args=(
                run.id,
                current_user.id,
                text_ai_client,
                snapshot,
                api_key,
                images,
                image_ai_client,
                image_snapshot,
                image_key,
                plan,
                payload.context,
            ),
            daemon=True,
        )
        thread.start()
        return serialize_run(db, run)

    execute_agent_run(
        db,
        current_user,
        run,
        text_ai_client,
        snapshot,
        api_key,
        images=images,
        image_client=image_ai_client,
        image_config=image_snapshot,
        image_api_key=image_key,
        plan=plan,
        context=payload.context,
    )
    db.refresh(run)
    return serialize_run(db, run)


@router.get("/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == current_user.id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    ).all()
    return {"items": [serialize_run(db, run) for run in runs]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return serialize_run(db, run)


class ConfirmPublishRequest(BaseModel):
    draft_id: int | None = None


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if run.status in {"running", "awaiting_confirmation"}:
        run.status = "cancelled"
        run.summary = "已取消"
        db.commit()
        db.refresh(run)
    return serialize_run(db, run)


@router.post("/runs/{run_id}/confirm-publish")
def confirm_publish(
    run_id: int,
    payload: ConfirmPublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    steps = db.scalars(
        select(AgentStep)
        .where(AgentStep.run_id == run.id, AgentStep.tool == "prepare_publish")
        .order_by(AgentStep.step_index.desc())
    ).all()
    draft_id = payload.draft_id
    if draft_id is None and steps:
        draft_id = (steps[0].output or {}).get("draft_id")
    if draft_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="这个运行没有待发布的草稿",
        )

    draft = db.get(AiDraft, int(draft_id))
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    if not draft.platform_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="草稿还没有绑定发布账号",
        )

    # Idempotency: return the existing job for this draft instead of creating another.
    existing = db.scalars(
        select(PublishJob)
        .where(
            PublishJob.user_id == current_user.id,
            PublishJob.source_draft_id == draft.id,
            PublishJob.status.in_(["pending", "scheduled", "publishing", "published"]),
        )
        .order_by(PublishJob.id.desc())
    ).first()
    if existing is not None:
        run.status = "completed"
        run.summary = (
            (run.summary + "\n") if run.summary else ""
        ) + f"已存在发布任务 #{existing.id}，未重复创建。"
        db.commit()
        db.refresh(run)
        return {"run": serialize_run(db, run), "job": serialize_publish_job(existing)}

    if run.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="这个运行不在待确认状态，不能发布",
        )

    from backend.app.api.drafts import DraftSendToPublishRequest, send_draft_to_publish

    job = send_draft_to_publish(
        draft.id,
        DraftSendToPublishRequest(
            platform_account_id=draft.platform_account_id,
            publish_mode="immediate",
        ),
        current_user,
        db,
    )
    run.status = "completed"
    run.summary = (
        (run.summary + "\n") if run.summary else ""
    ) + f"已创建发布任务 #{job['id']}，请前往发布中心选择账号并发布。"
    db.commit()
    db.refresh(run)
    return {"run": serialize_run(db, run), "job": job}
