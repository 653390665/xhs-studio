"""找资料的检索网关：单独配，不再绑死默认文本模型。

背景（真实故障）
----------------
默认文本模型配的是 amr-link（``https://amr-link.open-design.ai/v1``），它只有
``/chat/completions``::

    POST {base}/search             -> 404 page not found
    POST {base}/chat/completions   -> 200

旧实现把 ``f"{base_url}/search"`` 写死，于是「素材 → 找资料」必然 404，
而界面还提示「去设置→模型保存一个默认文本模型」——用户会去重配一次模型，
问题依旧。

本文件守四件事：
1. 单独配了网关就用它；
2. 没单独配要能回落到默认文本模型（老用户不动也能用）；
3. 两样都没有时，报错要说清去哪填；
4. 404 的两种原因（自己配错了 vs 默认模型没有 /search）文案必须不同。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.app.core.config as config_module
from backend.app.api import search_gateway as api_module
from backend.app.core.config import get_settings
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import encrypt_text
from backend.app.models import ModelConfig, User
from backend.app.services import search_gateway as svc


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sg.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    settings_file = tmp_path / "user_settings.json"
    monkeypatch.setenv("XHS_USER_SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(config_module, "_load_yaml_config", lambda: {})
    monkeypatch.setattr(config_module, "_dotenv_keys", lambda: set())
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(api_module.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as client:
        yield client, db, user, settings_file
    db.close()
    get_settings.cache_clear()


def _add_default_text_model(db, user, *, base_url, key="k-123456", model="deepseek-v4.1-flash"):
    row = ModelConfig(
        user_id=user.id,
        name="default",
        model_type="text",
        provider="deepseek",
        model_name=model,
        base_url=base_url,
        encrypted_api_key=encrypt_text(key),
        is_default=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------- 解析


def test_custom_gateway_wins_over_default_model(ctx):
    client, db, user, path = ctx
    _add_default_text_model(db, user, base_url="https://amr-link.open-design.ai/v1")

    path.write_text(
        json.dumps(
            {
                "search_base_url": "http://127.0.0.1:7863/v1",
                "search_api_key": encrypt_text("sk-wb"),
                "search_model_name": "deepseek-v4.1-flash",
            }
        ),
        encoding="utf-8",
    )

    gateway = svc.resolve_search_gateway(db, user)
    assert gateway.source == "custom"
    assert gateway.base_url == "http://127.0.0.1:7863/v1"
    assert gateway.api_key == "sk-wb"


def test_falls_back_to_default_text_model_when_unset(ctx):
    _client, db, user, _path = ctx
    _add_default_text_model(db, user, base_url="https://amr-link.open-design.ai/v1")

    gateway = svc.resolve_search_gateway(db, user)
    assert gateway.source == "default_model"
    assert gateway.base_url == "https://amr-link.open-design.ai/v1"
    assert gateway.api_key == "k-123456", "回落时 Key 必须解出来，不能拿密文去发请求"


def test_missing_everything_raises_with_actionable_text(ctx):
    _client, db, user, _path = ctx
    with pytest.raises(Exception) as excinfo:
        svc.resolve_search_gateway(db, user)
    message = str(excinfo.value)
    assert "找资料用的检索" in message
    assert "search" in message


def test_base_url_without_key_is_reported_separately(ctx):
    _client, db, user, path = ctx
    path.write_text(json.dumps({"search_base_url": "http://127.0.0.1:7863/v1"}), encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        svc.resolve_search_gateway(db, user)
    assert "没填 API Key" in str(excinfo.value)


def test_plaintext_key_still_works(ctx):
    """手改过 settings.json 的明文 Key 不该直接报解密失败。"""
    _client, db, user, path = ctx
    path.write_text(
        json.dumps(
            {"search_base_url": "http://127.0.0.1:7863/v1", "search_api_key": "sk-plain"}
        ),
        encoding="utf-8",
    )
    gateway = svc.resolve_search_gateway(db, user)
    assert gateway.api_key == "sk-plain"


# ---------------------------------------------------------------- 404 文案


def test_404_message_differs_by_source(ctx):
    _client, db, user, _path = ctx
    custom = svc.SearchGateway(
        base_url="http://x/v1", api_key="k", model_name="m", source="custom"
    )
    fallback = svc.SearchGateway(
        base_url="http://x/v1", api_key="k", model_name="m", source="default_model"
    )
    custom_text = svc.describe_404(custom, "http://x/v1/search")
    fallback_text = svc.describe_404(fallback, "http://x/v1/search")

    assert custom_text != fallback_text
    assert "你配置的检索网关" in custom_text
    assert "默认文本模型的网关" in fallback_text
    assert "找资料用的检索" in fallback_text


# ---------------------------------------------------------------- 读写接口


def test_get_returns_unconfigured_by_default(ctx):
    client, _db, _user, _path = ctx
    body = client.get("/api/search/gateway").json()
    assert body["configured"] is False
    assert body["base_url"] == ""


def test_put_saves_key_encrypted_and_masks_it(ctx):
    client, _db, _user, path = ctx
    response = client.put(
        "/api/search/gateway",
        json={
            "base_url": "http://127.0.0.1:7863/v1",
            "model_name": "deepseek-v4.1-flash",
            "api_key": "sk-t270AxGAM6XikFu1BUupQPVL",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["api_key_masked"] == "sk-t****QPVL"

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["search_api_key"] != "sk-t270AxGAM6XikFu1BUupQPVL", "Key 不能明文落盘"
    assert raw["search_base_url"] == "http://127.0.0.1:7863/v1"


def test_put_empty_string_clears_the_field(ctx):
    client, _db, _user, path = ctx
    client.put(
        "/api/search/gateway",
        json={"base_url": "http://127.0.0.1:7863/v1", "api_key": "sk-x"},
    )
    client.put("/api/search/gateway", json={"base_url": ""})

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "search_base_url" not in raw
    assert raw.get("search_api_key"), "清 base_url 不该顺手把 Key 也删了"
