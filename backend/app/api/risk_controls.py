from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.services.risk_control_service import (
    get_risk_controls,
    serialize_risk_controls,
    update_risk_controls,
)

router = APIRouter(prefix="/settings/risk-controls", tags=["risk-controls"])


class RiskControlUpdate(BaseModel):
    auto_ops_enabled: Optional[bool] = None
    competitor_rewrite_enabled: Optional[bool] = None
    copy_source_images_enabled: Optional[bool] = None
    auto_create_publish_job_enabled: Optional[bool] = None
    auto_publish_enabled: Optional[bool] = None
    auto_engagement_enabled: Optional[bool] = None
    matrix_mode_enabled: Optional[bool] = None
    batch_repost_enabled: Optional[bool] = None
    acknowledge_risk: bool = False


@router.get("")
def read_risk_controls(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_risk_controls(get_risk_controls(db, current_user))


@router.put("")
def write_risk_controls(
    payload: RiskControlUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude={"acknowledge_risk"}, exclude_none=True)
    try:
        setting = update_risk_controls(
            db,
            current_user,
            updates,
            acknowledge_risk=payload.acknowledge_risk,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_risk_controls(setting)
