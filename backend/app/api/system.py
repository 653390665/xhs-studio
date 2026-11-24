from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import (
    ApiLog,
    AutoTask,
    PlatformAccount,
    Task,
    User,
    ViralTemplate,
)

router = APIRouter(prefix="/system", tags=["system"])


class SystemSettingsRequest(BaseModel):
    redfox_api_key: Optional[str] = Field(default=None, max_length=200)


def settings_path() -> Path:
    configured = os.getenv("XHS_USER_SETTINGS_FILE")
    path = Path(configured) if configured else Path("./data/user_settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(data: dict) -> None:
    settings_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}****{key[-4:]}"


@router.get("/settings")
def get_system_settings(current_user: User = Depends(get_current_user)):
    data = _read_settings()
    key = str(data.get("redfox_api_key") or "")
    return {
        "redfox_configured": bool(key),
        "redfox_api_key_masked": _mask(key),
        "data_dir": str(settings_path().parent),
        "settings_file": str(settings_path()),
    }


@router.put("/settings")
def save_system_settings(
    payload: SystemSettingsRequest,
    current_user: User = Depends(get_current_user),
):
    data = _read_settings()
    if payload.redfox_api_key is not None:
        key = payload.redfox_api_key.strip()
        if key:
            data["redfox_api_key"] = key
            os.environ["REDFOX_API_KEY"] = key
        else:
            data.pop("redfox_api_key", None)
            os.environ.pop("REDFOX_API_KEY", None)
    _write_settings(data)

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    try:
        from backend.app.adapters.xhs.redfox_api_adapter import reset_redfox_status_cache

        reset_redfox_status_cache()
    except Exception:
        pass

    key = str(data.get("redfox_api_key") or "")
    return {
        "redfox_configured": bool(key),
        "redfox_api_key_masked": _mask(key),
        "data_dir": str(settings_path().parent),
        "settings_file": str(settings_path()),
    }


@router.get("/diagnostics")
def get_diagnostics(
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent failures an operator can act on, without reading raw task payloads."""
    since = shanghai_now() - timedelta(days=days)
    scope = or_(ApiLog.user_id == current_user.id, ApiLog.user_id.is_(None))

    error_filters = (
        ApiLog.created_at >= since,
        ApiLog.status != "success",
        scope,
    )
    api_errors = db.scalars(
        select(ApiLog)
        .where(*error_filters)
        .order_by(ApiLog.created_at.desc())
        .limit(20)
    ).all()
    api_error_count = db.scalar(
        select(func.count()).select_from(ApiLog).where(*error_filters)
    ) or 0

    failed_filters = (
        Task.user_id == current_user.id,
        Task.status == "failed",
        Task.created_at >= since,
    )
    failed_tasks = db.scalars(
        select(Task)
        .where(*failed_filters)
        .order_by(Task.created_at.desc())
        .limit(20)
    ).all()
    failed_task_count = db.scalar(
        select(func.count()).select_from(Task).where(*failed_filters)
    ) or 0

    accounts = db.scalars(
        select(PlatformAccount).where(
            PlatformAccount.user_id == current_user.id,
            PlatformAccount.status.not_in(("active", "healthy")),
        )
    ).all()

    auto_tasks = db.scalars(
        select(AutoTask).where(
            AutoTask.user_id == current_user.id,
            AutoTask.template_id.is_not(None),
        )
    ).all()
    template_ids = {task.template_id for task in auto_tasks if task.template_id}
    templates = {
        template.id: template
        for template in db.scalars(
            select(ViralTemplate).where(
                ViralTemplate.user_id == current_user.id,
                ViralTemplate.id.in_(template_ids or {-1}),
            )
        ).all()
    }
    template_issues = []
    for task in auto_tasks:
        template = templates.get(task.template_id)
        if template is None:
            reason = "模板不存在"
        elif not template.is_active:
            reason = "模板已归档"
        else:
            continue
        template_issues.append(
            {
                "auto_task_id": task.id,
                "name": task.name,
                "template_id": task.template_id,
                "reason": reason,
            }
        )

    return {
        "window_days": days,
        "since": since.isoformat(),
        "summary": {
            "api_errors": int(api_error_count),
            "failed_tasks": int(failed_task_count),
            "account_issues": len(accounts),
            "template_issues": len(template_issues),
        },
        "api_errors": [
            {
                "id": item.id,
                "endpoint": item.endpoint,
                "status": item.status,
                "method": (item.meta or {}).get("method"),
                "status_code": (item.meta or {}).get("status_code"),
                "created_at": item.created_at.isoformat(),
            }
            for item in api_errors
        ],
        "failed_tasks": [
            {
                "id": item.id,
                "task_type": item.task_type,
                "error_type": item.error_type,
                "created_at": item.created_at.isoformat(),
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            }
            for item in failed_tasks
        ],
        "account_issues": [
            {
                "id": item.id,
                "nickname": item.nickname,
                "sub_type": item.sub_type,
                "status": item.status,
            }
            for item in accounts
        ],
        "template_issues": template_issues,
    }
