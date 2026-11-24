from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.ai import _text_model_context, get_text_ai_client
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import TopicIdea, User
from backend.app.services.agent_service import _generate_draft
from backend.app.services.ai_service import TextAiClient
from backend.app.services.topic_bank_service import (
    TopicBankError,
    generate_topic_bank,
    list_saved_topics,
    save_topics,
    serialize_topic,
    update_topic_schedule,
    update_topic_status,
)

router = APIRouter(prefix="/xhs/topics", tags=["xhs-topics"])


class TopicBankRequest(BaseModel):
    account_id: Optional[int] = None
    theme: str = Field(default="", max_length=300)
    per_type: int = Field(default=3, ge=1, le=10)
    use_llm: bool = True
    save: bool = False


class TopicStatusRequest(BaseModel):
    status: str = Field(pattern="^(new|used|archived)$")


class TopicScheduleRequest(BaseModel):
    scheduled_for: Optional[datetime] = None


class TopicDraftRequest(BaseModel):
    template_id: Optional[int] = None


@router.post("/generate")
def generate_topics(
    payload: TopicBankRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    try:
        result = generate_topic_bank(
            db,
            current_user,
            account_id=payload.account_id,
            theme=payload.theme,
            per_type=payload.per_type,
            use_llm=payload.use_llm,
            client=text_ai_client,
        )
    except TopicBankError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.save:
        saved = save_topics(
            db,
            current_user,
            account_id=payload.account_id,
            items=result["items"],
        )
        result.update(saved)
    return result


@router.get("")
def list_topics(
    account_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if status_filter and status_filter not in {"new", "used", "archived"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status 不合法")
    rows = list_saved_topics(
        db,
        current_user,
        account_id=account_id,
        status=status_filter,
        limit=limit,
    )
    return {"items": [serialize_topic(row) for row in rows], "total": len(rows)}


@router.patch("/{topic_id}")
def patch_topic(
    topic_id: int,
    payload: TopicStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        topic = update_topic_status(db, current_user, topic_id, payload.status)
    except TopicBankError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_topic(topic)


@router.patch("/{topic_id}/schedule")
def patch_topic_schedule(
    topic_id: int,
    payload: TopicScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        topic = update_topic_schedule(
            db,
            current_user,
            topic_id,
            payload.scheduled_for,
        )
    except TopicBankError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_topic(topic)


@router.post("/{topic_id}/draft")
def create_draft_from_topic(
    topic_id: int,
    payload: TopicDraftRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    topic = db.get(TopicIdea, topic_id)
    if topic is None or topic.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="选题不存在")
    if topic.status == "used":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这个选题已经生成过草稿")
    if not topic.platform_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="选题没有绑定账号")
    model_config, api_key = _text_model_context(db, current_user)
    try:
        result = _generate_draft(
            db,
            current_user,
            {
                "topic": topic.title,
                "topic_id": topic.id,
                "account_id": topic.platform_account_id,
                "template_id": payload.template_id if payload else None,
                "reference": (
                    f"选题类型：{topic.type_label or topic.type}；"
                    f"增长任务：{topic.growth_task}；"
                    f"用户需求：{topic.need or '未标注'}；"
                    f"推荐理由：{topic.why or '未标注'}"
                ),
            },
            text_ai_client,
            model_config,
            api_key,
            topic.platform_account_id,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"生成草稿失败：{exc}",
        ) from exc
    topic.status = "used"
    db.commit()
    return {**result, "topic_id": topic.id, "topic_status": "used"}
