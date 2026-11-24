"""RedFox account + compliance helpers: 余额 / 调用记录 / 违禁词检测.

Like the trends module these features only exist on the RedFox provider, so each
endpoint answers 400 with an actionable message when the effective provider is
``pc``. Balance and usage lookups are free upstream; the sensitive-word check is
billed per call (~¥0.06) and is therefore only run on an explicit user action.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.app.adapters.xhs.redfox_api_adapter import redfox_status, redfox_usage_snapshot

from backend.app.api.platforms.xhs.pc import get_xhs_redfox_adapter_factory
from backend.app.core.deps import get_current_user
from backend.app.models import User

router = APIRouter(prefix="/xhs/redfox", tags=["xhs-redfox"])

_NO_KEY_MESSAGE = (
    "该功能依赖 RedFox 接口，需要配置 redfox_api_key（环境变量或 .env）。"
    "它与「笔记发现」使用的 PC 登录态互不影响，可同时启用。"
)


class SensitiveWordRequest(BaseModel):
    content: str = Field(min_length=1, max_length=3000)


def _require_redfox() -> None:
    """Block RedFox-only endpoints with an actionable status code.

    400 = not configured at all, 402 = configured but out of points.
    """
    status_info = redfox_status()
    if status_info["available"]:
        return
    if status_info["reason"] == "insufficient_balance":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"{status_info['message']}（RedFox 模块已停用，其他功能正常）",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=status_info["message"] or _NO_KEY_MESSAGE,
    )


def _require_redfox_configured() -> None:
    """Balance/usage are free and must work even when the balance is zero."""
    if not redfox_status()["configured"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_NO_KEY_MESSAGE)


@router.get("/status")
def redfox_module_status(
    refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
):
    """RedFox 模块可用性（免费，余额结果缓存 60 秒）."""
    status_info = redfox_status(refresh=refresh)
    status_info["usage"] = redfox_usage_snapshot()
    return status_info


@router.get("/balance")
def account_balance(
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """账户余额（免费接口，余额为 0 时仍可查询）。"""
    _require_redfox_configured()
    success, message, payload = adapter_factory("").get_account_balance()
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "余额查询失败")
    return (payload or {}).get("data") or {}


@router.get("/usage")
def account_usage(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """接口调用记录（免费接口，余额为 0 时仍可查询）。"""
    _require_redfox_configured()
    success, message, payload = adapter_factory("").get_consume_flows(page=page, page_size=page_size)
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "调用记录查询失败")
    return (payload or {}).get("data") or {}


@router.post("/sensitive-words")
def sensitive_words(
    payload: SensitiveWordRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """违禁词检测：RedFox 可用时用官方库，否则回退到本地词库（免费）。"""
    if len(payload.content) > 3000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="待检测内容不能超过 3000 字。"
        )

    from backend.app.services.sensitive_word_service import check_local

    if redfox_status()["available"]:
        success, _message, result = adapter_factory("").check_sensitive_words(payload.content)
        if success:
            data = (result or {}).get("data") or {}
            data["source"] = "redfox"
            return data

    # Fallback: offline dictionary. Never blocks the user when the paid API is off.
    return check_local(payload.content)
