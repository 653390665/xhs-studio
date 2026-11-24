"""Scheduler on/off, from the settings page.

Why this is a separate module instead of a few lines in ``tasks.py``: the
switch is not a task. It writes ``user_settings.json``, clears the settings
cache and starts/stops ``app.state.scheduler`` — three things the task router
has no business owning.

The gap this fills, in one sentence: before, the only way to turn the
scheduler on was editing ``config/default.yaml`` or setting
``SCHEDULER_ENABLED=true``, and neither is reachable from the UI. The risk page
then said 「这批开关对应的功能还没上线」 while 「自动发布」 was in fact
wired — it just never ran.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings, user_settings_file
from backend.app.core.deps import get_current_user
from backend.app.models import User

router = APIRouter(prefix="/settings/scheduler", tags=["settings"])

# Lower bound is a real constraint, not decoration: the due-publish runner and
# monitoring refresh share this interval, and a 1-second loop would hammer the
# platform with the same cookie on every tick.
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 3600


class SchedulerSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )


def _read_file() -> dict:
    path = user_settings_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(data: dict) -> None:
    path = user_settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _status(request: Request) -> dict:
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "enabled": bool(settings.scheduler_enabled),
        "running": bool(scheduler is not None and scheduler.running),
        "interval_seconds": int(settings.scheduler_interval_seconds),
        # 改配置能不能落地的唯一解释：环境变量优先于这个文件。
        "editable": "SCHEDULER_ENABLED" not in os.environ,
    }


def _restart(request: Request, settings) -> None:
    from backend.app.services.scheduler_service import (
        shutdown_due_publish_scheduler,
        start_due_publish_scheduler,
    )

    scheduler = getattr(request.app.state, "scheduler", None)
    is_running = bool(scheduler is not None and scheduler.running)
    if scheduler is not None:
        # wait=True: a publish mid-upload must finish. See
        # ``shutdown_due_publish_scheduler``.
        shutdown_due_publish_scheduler(scheduler, wait=True)
        request.app.state.scheduler = None
        is_running = False
        # 间隔改了也要重启一次：旧 job 的 trigger 不会自己变。

    if settings.scheduler_enabled and not is_running:
        request.app.state.scheduler = start_due_publish_scheduler(
            settings.scheduler_interval_seconds
        )


@router.get("")
def read_scheduler_settings(
    request: Request, current_user: User = Depends(get_current_user)
):
    return _status(request)


@router.put("")
def write_scheduler_settings(
    payload: SchedulerSettingsRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Persist the switch, then start or stop the running scheduler."""
    if "SCHEDULER_ENABLED" in os.environ:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "当前部署通过环境变量 SCHEDULER_ENABLED 指定了调度器状态，"
                "界面改动不会生效。请改部署配置，或去掉该环境变量后用界面控制。"
            ),
        )

    data = _read_file()
    if payload.enabled is not None:
        data["scheduler_enabled"] = bool(payload.enabled)
    if payload.interval_seconds is not None:
        data["scheduler_interval_seconds"] = int(payload.interval_seconds)
    _write_file(data)

    # 配置是 lru_cache 的：不清掉，下面读到的还是旧值，起的还是旧间隔。
    get_settings.cache_clear()
    settings = get_settings()

    _restart(request, settings)
    return _status(request)
