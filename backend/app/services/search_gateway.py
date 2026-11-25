"""检索网关的解析与存取。

为什么单独一个模块
------------------
「找资料」要的是网关的 ``/search``，而写稿/提炼要的是 ``/chat/completions``。
这两件事**不一定在同一个网关**上：

  · amr-link 这类只做 chat 的网关，``/v1/search`` 直接 404；
  · WorkBuddy 反代（``http://127.0.0.1:7863/v1``）两个都有。

以前 ``/api/ai/search`` 写死用「默认文本模型」的 base_url，于是只要默认模型
指向一个没有 /search 的网关，找资料就必然失败，而界面还会误导用户去重配模型。

现在改成两级：
  1. 用户在「设置 → 模型 → 找资料用的检索」里单独填的 base_url + key（优先）
  2. 没填就回落到默认文本模型（保持旧行为，老用户不动也能用）

存在 ``user_settings.json`` 里，和 RedFox key 同一个文件——不新增数据库迁移。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import user_settings_file
from backend.app.models import ModelConfig, User


@dataclass(frozen=True)
class SearchGateway:
    """实际要打的那个网关。"""

    base_url: str
    api_key: str
    model_name: str
    # "custom" = 用户单独配的检索网关；"default_model" = 回落到默认文本模型
    source: str


def user_settings_path() -> Path:
    """``user_settings.json`` 的落地路径（由 launcher 指到用户数据目录）。"""
    return user_settings_file()


def read_user_settings() -> dict:
    """读 ``user_settings.json``；读不到/坏了都当空，不让检索因此打不开。"""
    path = user_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_user_settings(data: dict) -> None:
    path = user_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def decrypt_stored_key(stored: str) -> str:
    """解密落盘的 Key。

    用和模型 Key 同一把 Fernet。解不开就把原值当明文返回：手改过的
    ``settings.json`` 里可能是明文，这时报「解密失败」比报「连不上网关」
    更难让人理解。
    """
    if not stored:
        return ""
    try:
        from backend.app.core.security import decrypt_text

        return decrypt_text(stored)
    except Exception:
        return stored


def _default_text_model(db: Session, user: User) -> Optional[ModelConfig]:
    return db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user.id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()


def resolve_search_gateway(db: Session, user: User) -> SearchGateway:
    """找到这次检索该用哪个网关。

    找不到就抛 400，并把「该去哪里填什么」说清楚——这一条是用户最容易卡住的地方。
    """
    data = read_user_settings()
    base = str(data.get("search_base_url") or "").strip()
    key = decrypt_stored_key(str(data.get("search_api_key") or ""))
    model = str(data.get("search_model_name") or "").strip()

    if base:
        if not key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "已填检索网关地址，但没填 API Key。"
                    "到「设置 → 模型 → 找资料用的检索」补上 Key 再试。"
                ),
            )
        model_name = model
        if not model_name:
            row = _default_text_model(db, user)
            model_name = str(row.model_name or "").strip() if row else ""
        return SearchGateway(
            base_url=base,
            api_key=key,
            model_name=model_name,
            source="custom",
        )

    # 没单独配：回落到默认文本模型，和以前一致
    row = _default_text_model(db, user)
    if row is not None and row.base_url and row.encrypted_api_key:
        api_key = decrypt_stored_key(str(row.encrypted_api_key))
        if api_key:
            return SearchGateway(
                base_url=str(row.base_url).strip(),
                api_key=api_key,
                model_name=str(row.model_name or "").strip(),
                source="default_model",
            )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "还没配置检索网关。到「设置 → 模型 → 找资料用的检索」填一个支持 "
            "/search 的网关（例如 WorkBuddy 反代 http://127.0.0.1:7863/v1），"
            "或者先配一个默认文本模型。"
        ),
    )


def describe_404(gateway: SearchGateway, endpoint: str) -> str:
    """404 的两种原因要分开说，否则用户不知道该改哪儿。"""
    if gateway.source == "custom":
        return (
            f"你配置的检索网关没有 /search 接口（{endpoint}）。"
            "确认地址填的是网关根路径（一般以 /v1 结尾），"
            "并且这个网关确实提供 /search。"
        )
    return (
        f"默认文本模型的网关不支持 /search（{endpoint}）。"
        "检索需要单独的搜索网关：到「设置 → 模型 → 找资料用的检索」"
        "填一个支持 /search 的地址（例如 WorkBuddy 反代 http://127.0.0.1:7863/v1）。"
    )
