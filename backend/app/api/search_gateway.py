"""检索网关的读写接口。

为什么需要它
------------
``/api/ai/search`` 需要网关同时支持 ``/search``。默认文本模型往往只做
``/chat/completions``（amr-link 就是），拼出来的 ``{base_url}/search`` 是 404。
所以检索网关要能单独配，否则「找资料」永远用不了。

为什么不塞进 /api/model-configs
------------------------------
模型配置表有 ``model_type`` 枚举（text/image），加第三种类型要改迁移和一堆
按类型取默认值的查询。检索网关只是一组 URL + Key，放 ``user_settings.json``
（和 RedFox key 同一个文件）就够，不动数据库。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.core.deps import get_current_user
from backend.app.core.security import encrypt_text
from backend.app.models import User
from backend.app.services.search_gateway import (
    decrypt_stored_key,
    read_user_settings,
    write_user_settings,
)

router = APIRouter(prefix="/search", tags=["search"])


class SearchGatewayRequest(BaseModel):
    """``None`` = 不改这一项；空字符串 = 清除这一项。"""

    base_url: Optional[str] = Field(default=None, max_length=512)
    model_name: Optional[str] = Field(default=None, max_length=128)
    api_key: Optional[str] = Field(default=None, max_length=512)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


def _payload(data: dict) -> dict:
    raw_key = str(data.get("search_api_key") or "")
    plain = decrypt_stored_key(raw_key) if raw_key else ""
    return {
        "base_url": str(data.get("search_base_url") or ""),
        "model_name": str(data.get("search_model_name") or ""),
        "configured": bool(data.get("search_base_url") and raw_key),
        "api_key_masked": _mask(plain),
    }


@router.get("/gateway")
def get_search_gateway(current_user: User = Depends(get_current_user)):
    return _payload(read_user_settings())


@router.put("/gateway")
def save_search_gateway(
    payload: SearchGatewayRequest,
    current_user: User = Depends(get_current_user),
):
    data = read_user_settings()

    if payload.base_url is not None:
        base = payload.base_url.strip()
        if base:
            data["search_base_url"] = base
        else:
            data.pop("search_base_url", None)

    if payload.model_name is not None:
        name = payload.model_name.strip()
        if name:
            data["search_model_name"] = name
        else:
            data.pop("search_model_name", None)

    if payload.api_key is not None:
        key = payload.api_key.strip()
        if key:
            data["search_api_key"] = encrypt_text(key)
        else:
            data.pop("search_api_key", None)

    write_user_settings(data)
    return _payload(data)
