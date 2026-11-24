from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import RiskControlSetting, User

RISK_FIELDS: tuple[str, ...] = (
    "auto_ops_enabled",
    "competitor_rewrite_enabled",
    "copy_source_images_enabled",
    "auto_create_publish_job_enabled",
    "auto_publish_enabled",
    "auto_engagement_enabled",
    "matrix_mode_enabled",
    "batch_repost_enabled",
)
FIELD_LABELS: dict[str, str] = {
    "auto_ops_enabled": "自动运营",
    "competitor_rewrite_enabled": "竞品改写",
    "copy_source_images_enabled": "复制来源图片",
    "auto_create_publish_job_enabled": "自动创建待发布任务",
    "auto_publish_enabled": "自动发布",
    "auto_engagement_enabled": "自动私信/评论",
    "matrix_mode_enabled": "批量矩阵",
    "batch_repost_enabled": "批量改写",
}
RESERVED_FIELDS = frozenset({"auto_engagement_enabled"})


def get_risk_controls(db: Session, user: User) -> RiskControlSetting:
    setting = db.scalars(
        select(RiskControlSetting).where(RiskControlSetting.user_id == user.id)
    ).first()
    if setting is None:
        setting = RiskControlSetting(user_id=user.id)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def serialize_risk_controls(setting: RiskControlSetting) -> dict[str, Any]:
    payload = {field: bool(getattr(setting, field)) for field in RISK_FIELDS}
    payload.update(
        {
            "updated_at": setting.updated_at.isoformat() if setting.updated_at else "",
            "reserved_fields": sorted(RESERVED_FIELDS),
            "labels": FIELD_LABELS,
        }
    )
    return payload


def update_risk_controls(
    db: Session,
    user: User,
    updates: dict[str, Optional[bool]],
    *,
    acknowledge_risk: bool = False,
) -> RiskControlSetting:
    setting = get_risk_controls(db, user)
    normalized: dict[str, bool] = {}
    enabling: list[str] = []
    for field, value in updates.items():
        if field not in RISK_FIELDS or value is None:
            continue
        if value and field in RESERVED_FIELDS:
            raise ValueError(f"「{FIELD_LABELS.get(field, field)}」暂未开放")
        normalized[field] = bool(value)
        if value and not getattr(setting, field):
            enabling.append(field)

    if enabling and not acknowledge_risk:
        labels = "、".join(FIELD_LABELS.get(field, field) for field in enabling)
        raise ValueError(f"开启高风险功能需要确认风险：{labels}")

    for field, value in normalized.items():
        setattr(setting, field, value)

    if setting.auto_publish_enabled:
        setting.auto_create_publish_job_enabled = True

    db.commit()
    db.refresh(setting)
    return setting


def require_risk_control(
    db: Session,
    user: User,
    field: str,
    *,
    detail: str = "",
) -> None:
    setting = get_risk_controls(db, user)
    if getattr(setting, field):
        return
    label = FIELD_LABELS.get(field, field)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail
        or f"「{label}」未开启。请到「设置 → 风险控制」开启，并确认由你自行承担相关风险。",
    )
