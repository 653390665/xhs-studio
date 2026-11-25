import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.main import app

# 仓库根：本文件在 tests/backend/ 下，往上两级。
REPO = Path(__file__).resolve().parents[2]


client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "xhs-studio"
    # version 由 version.py 提供、CI 按 tag 改写；本地跑也必须有值，
    # 因为安装包的冒烟测试就是靠它确认「装的是这一版」。
    assert "version" in payload
    assert payload["version"], "health 必须带版本号，否则装错版本查不出来"


def test_platforms_endpoint_exposes_product_registry():
    response = client.get("/api/platforms")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 6
    assert payload["items"][0]["id"] == "xhs"
    assert payload["items"][0]["enabled"] is True
    assert payload["items"][1]["id"] == "douyin"
    assert payload["items"][1]["enabled"] is False
    assert payload["items"][2]["status"] == "coming_soon"


def test_xhs_analytics_overview_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/xhs/analytics/overview")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_backend_foundation_modules_import():
    from backend.app.core.config import get_settings
    from backend.app.core.database import Base
    from backend.app.models import PlatformAccount, Note, Task, User

    settings = get_settings()
    assert settings.app_name == "XHS Studio"
    assert Base is not None
    assert User.__tablename__ == "users"
    assert PlatformAccount.__tablename__ == "platform_accounts"
    assert Note.__tablename__ == "notes"
    assert Task.__tablename__ == "tasks"


def test_accounts_page_does_not_auto_check_accounts_on_load():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/accounts-page.tsx").read_text(encoding="utf-8")

    assert "refreshMissingProfiles" not in source
    assert "void refreshMissingProfiles(loadedAccounts)" not in source


def test_accounts_page_uses_antd_components_and_shows_check_state():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/accounts-page.tsx").read_text(encoding="utf-8")

    assert "antd" in source
    assert "checkingAccountIds" in source or "checkingId" in source or "isChecking" in source
    assert "检查" in source


def test_xhs_direct_request_env_temporarily_removes_proxy_variables(monkeypatch):
    from backend.app.adapters.xhs.request_env import PROXY_ENV_KEYS, direct_xhs_request_env

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10809")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:10809")

    with direct_xhs_request_env():
        assert all(key not in os.environ for key in PROXY_ENV_KEYS)

    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:10809"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:10809"


def test_xhs_adapters_isolate_sdk_calls_from_broken_system_proxy():
    adapter_paths = [
        "backend/app/adapters/xhs/creator_login_adapter.py",
        "backend/app/adapters/xhs/creator_api_adapter.py",
        "backend/app/adapters/xhs/pc_login_adapter.py",
        "backend/app/adapters/xhs/pc_api_adapter.py",
    ]

    for path in adapter_paths:
        source = open(path, encoding="utf-8").read()
        assert "direct_xhs_request_env" in source


def test_crawler_page_exports_spider_style_excel():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/crawler-page.tsx").read_text(encoding="utf-8")

    assert "noteExcelHeaders" in source
    assert "笔记id" in source
    assert "图片地址url列表" in source
    assert "application/vnd.ms-excel;charset=utf-8" in source


def test_crawler_page_uses_antd_table():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/crawler-page.tsx").read_text(encoding="utf-8")

    assert "antd" in source
    assert "Table" in source


def test_discovery_uses_antd_components_and_preserves_core_logic():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/discovery-page.tsx").read_text(encoding="utf-8")

    assert "antd" in source
    assert "async function ensureNoteDetail" in source or "ensureNoteDetail" in source
    assert "保存" in source
    assert "评论" in source
    assert "原文" in source


def test_discovery_preserves_note_detail_and_media_logic():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/discovery-page.tsx").read_text(encoding="utf-8")

    assert "function getNoteVideoUrl" in source
    assert "function getNoteKindLabel" in source
    assert "detailMediaIndex" in source
    assert "视频" in source
    assert "图文" in source


def test_library_page_preserves_delete_and_media_logic():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/library-page.tsx").read_text(encoding="utf-8")
    api_source = (REPO / "frontend-legacy/src/lib/api.ts").read_text(encoding="utf-8")

    assert "deleteSavedNote" in api_source
    assert "handleDeleteNote" in source
    assert "删除" in source
    assert "function getSavedNoteCoverUrl" in source
    assert 'referrerPolicy="no-referrer"' in source


def test_discovery_cards_show_note_media_type():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/discovery-page.tsx").read_text(encoding="utf-8")

    assert "function getNoteKindLabel" in source
    assert "视频" in source
    assert "图文" in source


def test_rewrite_page_preserves_mode_switch():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/rewrite-page.tsx").read_text(encoding="utf-8")

    assert "rewrite" in source
    assert "generate" in source
    assert "改写" in source
    assert "生成" in source
    assert "antd" in source


def test_navigation_splits_own_notes_library_and_analysis():
    navigation = (REPO / "frontend-legacy/src/app/navigation.ts").read_text(encoding="utf-8")
    router = (REPO / "frontend-legacy/src/app/router.tsx").read_text(encoding="utf-8")

    # IA 最终版：素材/计划/提炼/写稿/发布，复盘并入总览，账号并入设置。
    # 导航标签已集中到 navigation.ts，路由只负责映射。
    assert '{ key: "/platforms/xhs/dashboard/notes", label: "我的笔记" }' in navigation
    assert '{ key: "/platforms/xhs/assets/library", label: "样本库" }' in navigation
    assert 'label: "采集"' in navigation
    assert 'label: "对标分析"' in navigation

    # 我的笔记在总览下，样本库在素材下，二者必须独立。
    assert '<Route path="notes" element={<XhsLibraryPage fixedSource="own" />} />' in router
    assert '<Route path="library" element={<XhsLibraryPage fixedSource="library" />} />' in router
    assert 'path="own" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/notes" />} />' in router

    # 计划只保留选题库；复盘在总览；提炼仍是板块壳层。
    assert '<Route path="/platforms/xhs/plan" element={<TopicBankPage />} />' in router
    assert 'path="review" element={<XhsAnalyticsPage />}' in router
    assert 'path="/platforms/xhs/refine"' in router

    # 账号属于设置。
    assert '<Route path="accounts" element={<XhsAccountsPage />} />' in router


def test_rewrite_page_shows_draft_template_and_topic_sources():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/rewrite-page.tsx").read_text(encoding="utf-8")

    assert "来源选题" in source
    assert "结构模板：" in source
    assert "selectedDraft.topic_id" in source
    assert "selectedDraft.template_id" in source


def test_publish_page_uses_antd_components():
    source = (REPO / "frontend-legacy/src/pages/platforms/xhs/publish-page.tsx").read_text(encoding="utf-8")

    assert "antd" in source
    assert "发布" in source


def test_openai_compatible_text_client_decodes_utf8_json_when_response_headers_are_wrong(monkeypatch):
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    class DummyConfig:
        base_url = "https://api.example.test/v1"
        model_name = "gpt-5.4"

    class FakeResponse:
        def __init__(self):
            self.content = (
                b'{"choices":[{"message":{"content":"'
                + "你好，今天很适合去公园散步。".encode("utf-8")
                + b'"}}]}'
            )
            self.encoding = "ISO-8859-1"
            self.apparent_encoding = "utf-8"
            self.headers = {"content-type": "text/event-stream"}

        def raise_for_status(self):
            return None

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("backend.app.services.ai_service.requests.post", fake_post)

    client = OpenAICompatibleTextClient()
    result = client.rewrite_note(
        model_config=DummyConfig(),
        api_key="test-key",
        title="原文标题",
        body="今天天气很好，我们去公园散步。",
        instruction="保留中文自然表达",
    )

    assert result == "你好，今天很适合去公园散步。"


def test_database_initialization_creates_user_table(tmp_path):
    from alembic import command
    from alembic.config import Config

    db_url = f"sqlite:///{tmp_path / 'init-test.db'}"
    cfg = Config(os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    table_names = inspect(test_engine).get_table_names()
    assert "users" in table_names
    assert "platform_accounts" in table_names
    assert "alembic_version" in table_names


def test_alembic_initial_migration_creates_all_product_tables(tmp_path):
    from alembic import command
    from alembic.config import Config

    db_url = f"sqlite:///{tmp_path / 'alembic-tables-test.db'}"
    cfg = Config(os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    table_names = set(inspect(test_engine).get_table_names())
    expected = {
        "users", "platform_accounts", "account_cookie_versions", "login_sessions",
        "notes", "note_assets", "note_comments", "tags", "note_tags",
        "model_configs", "ai_drafts", "ai_generated_assets",
        "publish_jobs", "publish_assets", "tasks",
        "monitoring_targets", "monitoring_snapshots",
        "keyword_groups", "api_logs",
    }
    assert expected.issubset(table_names)


def test_database_initialization_normalizes_legacy_gpt_54_model_name(tmp_path):
    from backend.app.core.database import _normalize_model_config_names

    engine = create_engine(f"sqlite:///{tmp_path / 'model-name-migration-test.db'}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE model_configs (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    model_type VARCHAR(32) NOT NULL,
                    provider VARCHAR(64) NOT NULL,
                    model_name VARCHAR(128) NOT NULL,
                    base_url TEXT NOT NULL,
                    encrypted_api_key TEXT NOT NULL,
                    is_default BOOLEAN NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO model_configs "
                "(id, user_id, name, model_type, provider, model_name, base_url, encrypted_api_key, is_default) "
                "VALUES (1, 1, 'Text model', 'text', 'openai-compatible', 'gpt5.4', 'https://api.example.test/v1', '', 1)"
            )
        )

    _normalize_model_config_names(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT model_name FROM model_configs WHERE id = 1")).mappings().one()
        assert row["model_name"] == "gpt-5.4"
        assert connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'normalize_legacy_gpt_54_model_name_v1'")
        ).first()


def test_database_initialization_normalizes_existing_sqlite_times_to_shanghai(tmp_path):
    from backend.app.core.database import _normalize_sqlite_datetime_storage

    engine = create_engine(f"sqlite:///{tmp_path / 'time-migration-test.db'}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE platform_accounts (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    platform VARCHAR(32) NOT NULL,
                    sub_type VARCHAR(32),
                    external_user_id VARCHAR(128) NOT NULL,
                    nickname VARCHAR(128) NOT NULL,
                    avatar_url TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    status_message TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO platform_accounts "
                "(id, user_id, platform, sub_type, external_user_id, nickname, avatar_url, status, created_at, updated_at) "
                "VALUES (1, 1, 'xhs', 'pc', 'pc-1', 'cat', '', 'active', '2026-04-30 07:50:43', '2026-04-30 07:50:43')"
            )
        )

    _normalize_sqlite_datetime_storage(engine)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT created_at, updated_at FROM platform_accounts WHERE id = 1")
        ).mappings().one()
        assert str(row["created_at"]).startswith("2026-04-30 15:50:43")
        assert str(row["updated_at"]).startswith("2026-04-30 15:50:43")
        assert connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'sqlite_datetime_asia_shanghai_v1'")
        ).first()


def _parse_sse_response(response):
    import json as _json
    events = []
    done = {}
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            event = _json.loads(line[6:])
            if event.get("type") == "item":
                events.append(event["item"])
            elif event.get("type") == "done":
                done = event
    return {"items": events, **done}


def _override_database(tmp_path):
    from backend.app.core.database import Base, get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'auth-test.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return get_db


def test_auth_register_login_me_and_refresh_use_real_tokens(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        register_response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "secret123"},
        )
        assert register_response.status_code == 200
        registered = register_response.json()
        assert registered["token_type"] == "bearer"
        assert registered["access_token"]
        assert registered["refresh_token"]
        assert registered["user"]["username"] == "operator"

        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered['access_token']}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "operator"

        login_response = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "secret123"},
        )
        assert login_response.status_code == 200
        logged_in = login_response.json()
        assert logged_in["access_token"]
        assert logged_in["refresh_token"]

        refresh_response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": logged_in["refresh_token"]},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["token_type"] == "bearer"
        assert refreshed["access_token"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_auth_rejects_duplicate_user_and_bad_credentials(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "secret123"},
        )
        assert response.status_code == 200

        duplicate_response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "different123"},
        )
        assert duplicate_response.status_code == 400

        bad_login_response = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "wrong-password"},
        )
        assert bad_login_response.status_code == 401

        missing_auth_response = client.get("/api/auth/me")
        assert missing_auth_response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


class FakePcLoginAdapter:
    def create_qrcode(self):
        return {
            "cookies": {"a1": "temp-a1"},
            "qr_id": "qr-123",
            "code": "code-123",
            "qr_url": "https://example.test/qr",
        }

    def check_qrcode_status(self, qr_id, code, cookies):
        assert qr_id == "qr-123"
        assert code == "code-123"
        assert cookies == {"a1": "temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "final-a1", "web_session": "session-123"}}

    def get_user_info(self, cookies):
        assert cookies["web_session"] == "session-123"
        return {
            "external_user_id": "xhs-user-1",
            "nickname": "cat",
            "avatar_url": "https://example.test/avatar.webp",
        }


class FakeCreatorLoginAdapter:
    def create_qrcode(self):
        return {
            "cookies": {"a1": "creator-temp-a1"},
            "qr_id": "creator-qr-123",
            "qr_url": "https://example.test/creator-qr",
        }

    def check_qrcode_status(self, qr_id, cookies):
        assert qr_id == "creator-qr-123"
        assert cookies == {"a1": "creator-temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "creator-final-a1", "customer_session": "session-456"}}

    def get_user_info(self, cookies):
        assert cookies["customer_session"] == "session-456"
        return {
            "external_user_id": "creator-user-1",
            "nickname": "creator-cat",
            "avatar_url": "https://example.test/creator-avatar.webp",
        }

    def exchange_from_user_cookies(self, user_cookies):
        assert user_cookies["a1"] in {"final-a1", "phone-final-a1", "cookie-a1"}
        return {"status": "confirmed", "cookies": {"a1": user_cookies["a1"], "customer_session": "session-456"}}


class FailingCreatorExchangeAdapter(FakeCreatorLoginAdapter):
    def exchange_from_user_cookies(self, user_cookies):
        raise RuntimeError("creator exchange failed")


class FailingQrLoginAdapter:
    def create_qrcode(self):
        raise RuntimeError("proxy refused while creating qrcode")


class FakePhoneLoginAdapter:
    def create_phone_session(self, phone):
        assert phone == "13800138000"
        return {"cookies": {"a1": "phone-temp-a1"}, "message": "sent"}

    def confirm_phone_login(self, phone, code, cookies):
        assert phone == "13800138000"
        assert code == "123456"
        assert cookies == {"a1": "phone-temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "phone-final-a1", "web_session": "phone-session"}}

    def get_user_info(self, cookies):
        assert cookies["web_session"] == "phone-session"
        return {
            "external_user_id": "phone-user-1",
            "nickname": "phone-cat",
            "avatar_url": "https://example.test/phone-avatar.webp",
        }


def _register_and_get_access_token(username: str = "operator") -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_xhs_pc_qrcode_login_session_persists_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token()

        create_response = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["status"] == "pending"
        assert created["qr_url"] == "https://example.test/qr"
        assert created["qr_image_data_url"].startswith("data:image/png;base64,")
        assert isinstance(created["session_id"], int)

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, created["session_id"])
            assert stored_session.platform == "xhs"
            assert stored_session.sub_type == "pc"
            assert stored_session.qr_id == "qr-123"
            assert stored_session.code == "code-123"
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"temp-a1"}'
        finally:
            db.close()

        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert poll_response.status_code == 200
        polled = poll_response.json()
        assert polled["status"] == "confirmed"
        assert polled["account"]["nickname"] == "cat"
        assert polled["creator_account"] is None

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert accounts_response.status_code == 200
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["nickname"] == "cat"
        assert accounts_payload["items"][0]["sub_type"] == "pc"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.platform == "xhs"
            assert account.sub_type == "pc"
            assert account.external_user_id == "xhs-user-1"
            cookie_version = db.query(AccountCookieVersion).one()
            assert cookie_version.platform_account_id == account.id
            assert decrypt_text(cookie_version.encrypted_cookies) == '{"a1":"final-a1","web_session":"session-123"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_pc_qrcode_login_updates_existing_account_for_same_external_user(tmp_path):
    from backend.app.api.accounts import get_pc_account_adapter
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("qr-upsert-operator")

        first_create = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        first_poll = client.get(
            f"/api/xhs/login-sessions/{first_create['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert first_poll.status_code == 200
        assert first_poll.json()["account"]["action"] == "created"

        second_create = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        second_poll = client.get(
            f"/api/xhs/login-sessions/{second_create['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert second_poll.status_code == 200
        assert second_poll.json()["account"]["action"] == "updated"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["updated_at"]
        assert accounts_payload["items"][0]["profile"] == {}

        check_response = client.post(
            f"/api/accounts/{accounts_payload['items'][0]['id']}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert check_response.status_code == 200
        assert check_response.json()["status"] == "active", check_response.json().get("status_message")

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).all()
            assert len(accounts) == 1
            cookie_versions = db.query(AccountCookieVersion).order_by(AccountCookieVersion.id).all()
            assert len(cookie_versions) == 2
            assert cookie_versions[-1].platform_account_id == accounts[0].id
            assert decrypt_text(cookie_versions[-1].encrypted_cookies) == '{"a1":"final-a1","web_session":"session-123"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_creator_qrcode_login_session_persists_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("creator-operator")

        create_response = client.post(
            "/api/xhs/login-sessions/creator/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["status"] == "pending"
        assert created["qr_url"] == "https://example.test/creator-qr"
        assert created["qr_image_data_url"].startswith("data:image/png;base64,")

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, created["session_id"])
            assert stored_session.platform == "xhs"
            assert stored_session.sub_type == "creator"
            assert stored_session.qr_id == "creator-qr-123"
            assert stored_session.code is None
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"creator-temp-a1"}'
        finally:
            db.close()

        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert poll_response.status_code == 200
        polled = poll_response.json()
        assert polled["status"] == "confirmed"
        assert polled["account"]["nickname"] == "creator-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["sub_type"] == "creator"
        assert accounts_payload["items"][0]["nickname"] == "creator-cat"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.sub_type == "creator"
            assert account.external_user_id == "creator-user-1"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_pc_qrcode_reports_adapter_failure_as_bad_gateway(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FailingQrLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("qr-failure-operator")
        response = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 502
        assert "proxy refused" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_pc_qrcode_login_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("pc-auto-creator-operator")

        created = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"sync_creator": True},
        ).json()
        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert poll_response.status_code == 200
        payload = poll_response.json()
        assert payload["status"] == "confirmed"
        assert payload["account"]["sub_type"] == "pc"
        assert payload["creator_account"]["sub_type"] == "creator"
        assert payload["creator_account"]["nickname"] == "creator-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 2
        assert {item["sub_type"] for item in accounts_payload["items"]} == {"pc", "creator"}

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).order_by(PlatformAccount.sub_type.asc()).all()
            assert len(accounts) == 2
            creator_account = next(account for account in accounts if account.sub_type == "creator")
            assert creator_account.external_user_id == "creator-user-1"
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"final-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_pc_phone_login_session_sends_code_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePhoneLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("phone-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/pc/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000"},
        )
        assert send_response.status_code == 200
        sent = send_response.json()
        assert sent["status"] == "pending"
        assert sent["message"] == "sent"

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, sent["session_id"])
            assert stored_session.sub_type == "pc"
            assert stored_session.login_method == "phone"
            assert stored_session.phone_mask == "138****8000"
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"phone-temp-a1"}'
        finally:
            db.close()

        confirm_response = client.post(
            "/api/xhs/login-sessions/pc/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["nickname"] == "phone-cat"
        assert confirmed["creator_account"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.sub_type == "pc"
            assert account.external_user_id == "phone-user-1"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_pc_phone_login_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePhoneLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("phone-auto-creator-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/pc/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000", "sync_creator": True},
        )
        assert send_response.status_code == 200
        sent = send_response.json()

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, sent["session_id"])
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"cookies":{"a1":"phone-temp-a1"},"sync_creator":true}'
        finally:
            db.close()

        confirm_response = client.post(
            "/api/xhs/login-sessions/pc/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["sub_type"] == "pc"
        assert confirmed["creator_account"]["sub_type"] == "creator"
        assert confirmed["creator_account"]["nickname"] == "creator-cat"

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).order_by(PlatformAccount.sub_type.asc()).all()
            assert len(accounts) == 2
            creator_account = next(account for account in accounts if account.sub_type == "creator")
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"phone-final-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_xhs_creator_phone_login_session_sends_code_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakePhoneLoginAdapter()
    try:
        access_token = _register_and_get_access_token("creator-phone-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/creator/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000"},
        )
        assert send_response.status_code == 200
        sent = send_response.json()
        assert sent["status"] == "pending"

        confirm_response = client.post(
            "/api/xhs/login-sessions/creator/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["nickname"] == "phone-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["items"][0]["sub_type"] == "creator"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)


def test_account_delete_requires_owner_and_removes_account(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount

    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("delete-account-owner")
        intruder_token = _register_and_get_access_token("delete-account-intruder")
        db = next(app.dependency_overrides[get_db]())
        try:
            account = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="pc",
                external_user_id="delete-user",
                nickname="Delete Me",
                status="active",
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            account_id = account.id
        finally:
            db.close()

        intruder_response = client.delete(
            f"/api/accounts/{account_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        owner_response = client.delete(
            f"/api/accounts/{account_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json() == {"id": account_id, "status": "deleted"}

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert accounts_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_pc_qrcode_requires_platform_login(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.post("/api/xhs/login-sessions/pc/qrcode")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_accounts_list_requires_platform_login(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.get("/api/accounts?platform=xhs")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


class FakeCookieAccountAdapter:
    def __init__(self):
        self.calls = 0

    def get_user_info(self, cookies):
        self.calls += 1
        assert cookies["a1"] == "cookie-a1"
        return {
            "external_user_id": "cookie-user-1",
            "nickname": "cookie-cat",
            "avatar_url": "https://example.test/cookie-avatar.webp",
        }


class FakeSelfProfileAdapter:
    calls = []

    def get_self_profile(self, cookies_text):
        self.__class__.calls.append(cookies_text)
        return {
            "success": True,
            "msg": "ok",
            "data": {
                "basic_info": {
                    "nickname": "cookie-cat-live",
                    "images": "https://example.test/live-avatar.webp",
                    "red_id": "red-cookie-1",
                    "desc": "live profile",
                    "ip_location": "上海",
                },
                "interactions": [
                    {"type": "follows", "name": "关注", "count": "28", "i18n_count": "28"},
                    {"type": "fans", "name": "粉丝", "count": "90", "i18n_count": "90"},
                    {"type": "interaction", "name": "获赞与收藏", "count": "340", "i18n_count": "340"},
                ],
            },
            "code": 0,
        }


class FailingCookieAccountAdapter:
    def get_user_info(self, cookies):
        raise RuntimeError("expired")


def test_account_cookie_import_creates_account_and_health_check_updates_status(tmp_path):
    from backend.app.api.accounts import get_creator_account_adapter, get_pc_account_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.core.time import shanghai_now
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    fake_adapter = FakeCookieAccountAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("cookie-operator")
        before_create = shanghai_now()

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        after_create = shanghai_now()
        assert import_response.status_code == 200
        imported = import_response.json()
        assert imported["nickname"] == "cookie-cat"
        assert imported["status"] == "active"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.external_user_id == "cookie-user-1"
            assert before_create <= account.created_at <= after_create
            assert before_create <= account.updated_at <= after_create
            cookie_version = db.query(AccountCookieVersion).one()
            assert cookie_version.platform_account_id == account.id
            assert decrypt_text(cookie_version.encrypted_cookies) == "a1=cookie-a1; web_session=session"
        finally:
            db.close()

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert accounts_response.status_code == 200
        assert accounts_response.json()["total"] == 1

        check_response = client.post(
            f"/api/accounts/{imported['id']}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert check_response.status_code == 200
        checked = check_response.json()
        assert checked["status"] == "active"
        assert checked["nickname"] == "cookie-cat"
        assert fake_adapter.calls >= 2
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)


def test_account_cookie_import_for_pc_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.accounts import get_creator_account_adapter, get_pc_account_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    fake_pc_adapter = FakeCookieAccountAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_pc_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("cookie-auto-creator-operator")

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "platform": "xhs",
                "sub_type": "pc",
                "cookie_string": "a1=cookie-a1; web_session=session",
                "sync_creator": True,
            },
        )
        assert import_response.status_code == 200

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 2
        assert {item["sub_type"] for item in accounts_payload["items"]} == {"pc", "creator"}

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).order_by(PlatformAccount.sub_type.asc()).all()
            assert len(accounts) == 2
            creator_account = next(account for account in accounts if account.sub_type == "creator")
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"cookie-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)


def test_account_check_refreshes_xhs_self_profile_metrics(tmp_path):
    from backend.app.api.accounts import (
        get_creator_account_adapter,
        get_pc_account_adapter,
        get_xhs_self_profile_adapter,
    )

    db_dependency = _override_database(tmp_path)
    fake_adapter = FakeCookieAccountAdapter()
    FakeSelfProfileAdapter.calls = []
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FailingCreatorExchangeAdapter()
    app.dependency_overrides[get_xhs_self_profile_adapter] = lambda: FakeSelfProfileAdapter()
    try:
        access_token = _register_and_get_access_token("profile-metrics-operator")
        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        account_id = import_response.json()["id"]

        check_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert check_response.status_code == 200
        checked = check_response.json()
        assert checked["status"] == "active"
        assert checked["nickname"] == "cookie-cat-live"
        assert checked["avatar_url"] == "https://example.test/live-avatar.webp"
        assert checked["profile"]["followers"] == "90"
        assert checked["profile"]["following"] == "28"
        assert checked["profile"]["likes"] == "340"
        assert checked["profile"]["red_id"] == "red-cookie-1"
        assert FakeSelfProfileAdapter.calls == ["a1=cookie-a1; web_session=session", "a1=cookie-a1; web_session=session"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)
        app.dependency_overrides.pop(get_xhs_self_profile_adapter, None)


def test_account_check_enforces_ownership_and_marks_expired_on_adapter_failure(tmp_path):
    from backend.app.api.accounts import get_pc_account_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_account_adapter] = lambda: FakeCookieAccountAdapter()
    try:
        owner_token = _register_and_get_access_token("owner-operator")
        intruder_token = _register_and_get_access_token("intruder-operator")

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        account_id = import_response.json()["id"]

        forbidden_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert forbidden_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_pc_account_adapter, None)

    app.dependency_overrides[get_pc_account_adapter] = lambda: FailingCookieAccountAdapter()
    try:
        expired_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert expired_response.status_code == 200
        assert expired_response.json()["status"] == "expired"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)


class FakeXhsPcSearchAdapter:
    calls = []

    def __init__(self, cookies):
        self.cookies = cookies

    def search_note(self, keyword, page=1, **kwargs):
        self.__class__.calls.append({"cookies": self.cookies, "keyword": keyword, "page": page, **kwargs})
        return (
            True,
            "ok",
            {
                "success": True,
                "msg": "ok",
                "data": {
                    "has_more": True,
                    "items": [
                        {
                            "model_type": "note",
                            "xsec_token": "xsec-search-001",
                            "note_card": {
                                "note_id": "note-001",
                                "display_title": "低卡早餐搜索笔记",
                                "desc": "适合工作日的早餐搭配",
                                "type": "normal",
                                "user": {
                                    "user_id": "author-001",
                                    "nickname": "早餐研究员",
                                    "avatar": "https://example.test/avatar.webp",
                                },
                                "cover": {"url_default": "https://example.test/cover.webp"},
                                "interact_info": {
                                    "liked_count": "1234",
                                    "collected_count": "456",
                                    "comment_count": "78",
                                    "share_count": "9",
                                },
                            },
                        }
                    ],
                },
            },
        )


def _create_pc_account_with_cookie(tmp_path, username="search-owner"):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    access_token = _register_and_get_access_token(username)
    db = next(app.dependency_overrides[get_db]())
    try:
        account = PlatformAccount(
            user_id=1,
            platform="xhs",
            sub_type="pc",
            external_user_id="search-user",
            nickname="搜索账号",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"a1":"json-a1","web_session":"json-session"}'),
            )
        )
        db.commit()
        account_id = account.id
    finally:
        db.close()
    return db_dependency, access_token, account_id


def _create_creator_account_with_cookie(tmp_path, username="creator-owner"):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    access_token = _register_and_get_access_token(username)
    db = next(app.dependency_overrides[get_db]())
    try:
        account = PlatformAccount(
            user_id=1,
            platform="xhs",
            sub_type="creator",
            external_user_id="creator-user",
            nickname="Creator account",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"web_session":"creator-session","a1":"creator-a1"}'),
            )
        )
        db.commit()
        account_id = account.id
    finally:
        db.close()
    return db_dependency, access_token, account_id


def test_xhs_pc_note_search_uses_owned_account_cookie_and_normalizes_results(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path)
    FakeXhsPcSearchAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcSearchAdapter
    try:
        response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 2},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["page"] == 2
        assert payload["has_more"] is True
        assert FakeXhsPcSearchAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "keyword": "低卡早餐",
                "page": 2,
                "sort_type_choice": 0,
                "note_type": 0,
                "note_time": 0,
                "note_range": 0,
                "pos_distance": 0,
                "geo": "",
            }
        ]
        note = payload["items"][0]
        assert note["note_id"] == "note-001"
        assert note["note_url"] == "https://www.xiaohongshu.com/explore/note-001?xsec_token=xsec-search-001&xsec_source=pc_feed"
        assert note["title"] == "低卡早餐搜索笔记"
        assert note["content"] == "适合工作日的早餐搭配"
        assert note["author_name"] == "早餐研究员"
        assert note["author_id"] == "author-001"
        assert note["cover_url"] == "https://example.test/cover.webp"
        assert note["likes"] == 1234
        assert note["collects"] == 456
        assert note["comments"] == 78
        assert note["shares"] == 9
        assert note["type"] == "normal"
        assert note["raw"]["model_type"] == "note"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_xhs_pc_note_search_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    db_dependency, owner_token, account_id = _create_pc_account_with_cookie(tmp_path, "search-owner-2")
    intruder_token = _register_and_get_access_token("search-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcSearchAdapter
    try:
        missing_auth_response = client.post(
            "/api/xhs/pc/search/notes",
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert missing_auth_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert intruder_response.status_code == 404

        owner_response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert owner_response.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_xhs_pc_note_detail_uses_owned_account_cookie_and_normalizes_result(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcDetailAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_info(self, url):
            self.calls.append({"cookies": self.cookies, "url": url})
            return (
                True,
                "ok",
                {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "note_card": {
                                    "note_id": "detail-note-001",
                                    "title": "Detail title",
                                    "desc": "Detail body",
                                    "type": "video",
                                    "user": {
                                        "user_id": "author-detail",
                                        "nickname": "Detail author",
                                        "avatar": "https://example.test/author.webp",
                                    },
                                    "image_list": [
                                        {
                                            "url_default": "https://example.test/image-preview.webp",
                                            "info_list": [
                                                {"image_scene": "WB_DFT", "url": "https://example.test/image-low.webp"},
                                                {"image_scene": "WB_PRV", "url": "https://example.test/image-high.webp"},
                                            ],
                                        },
                                    ],
                                    "video": {
                                        "media": {
                                            "stream": {
                                                "h264": [
                                                    {
                                                        "master_url": "https://sns-video-hw.xhscdn.com/detail-video-master.mp4",
                                                        "url": "https://sns-video-hw.xhscdn.com/detail-video-fallback.mp4",
                                                    }
                                                ]
                                            }
                                        }
                                    },
                                    "interact_info": {
                                        "liked_count": "100",
                                        "collected_count": "20",
                                        "comment_count": "3",
                                        "share_count": "4",
                                    },
                                    "tag_list": [{"name": "topic-a"}, {"name": "topic-b"}],
                                }
                            }
                        ]
                    },
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "detail-owner")
    FakeXhsPcDetailAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcDetailAdapter
    try:
        response = client.post(
            "/api/xhs/pc/notes/detail",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "url": "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed",
            },
        )

        assert response.status_code == 200
        detail = response.json()
        assert detail["note_id"] == "detail-note-001"
        assert detail["note_url"] == "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed"
        assert detail["title"] == "Detail title"
        assert detail["content"] == "Detail body"
        assert detail["author_id"] == "author-detail"
        assert detail["author_name"] == "Detail author"
        assert detail["cover_url"] == "https://example.test/image-high.webp"
        assert detail["image_urls"] == ["https://example.test/image-high.webp"]
        assert detail["video_url"] == "https://sns-video-hw.xhscdn.com/detail-video-master.mp4"
        assert detail["video_addr"] == "https://sns-video-hw.xhscdn.com/detail-video-master.mp4"
        assert detail["tags"] == ["topic-a", "topic-b"]
        assert detail["likes"] == 100
        assert FakeXhsPcDetailAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "url": "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed",
            }
        ]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_xhs_pc_note_detail_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcDetailAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user detail must not instantiate adapter")

    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "detail-cross-owner")
    intruder_token = _register_and_get_access_token("detail-cross-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcDetailAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/pc/notes/detail",
            json={"account_id": account_id, "url": "https://www.xiaohongshu.com/explore/detail-note-001"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/notes/detail",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "url": "https://www.xiaohongshu.com/explore/detail-note-001"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_xhs_pc_note_comments_uses_owned_account_cookie_and_normalizes_result(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            self.calls.append({"cookies": self.cookies, "note_url": note_url})
            return (
                True,
                "ok",
                {
                    "data": {
                        "comments": [
                            {
                                "id": "comment-001",
                                "content": "Top level comment",
                                "like_count": "12",
                                "create_time": "2026-04-29 12:00:00",
                                "user_info": {"user_id": "user-001", "nickname": "Comment author"},
                                "sub_comments": [
                                    {
                                        "id": "comment-001-1",
                                        "content": "Reply content",
                                        "like_count": 3,
                                        "create_time": "2026-04-29 12:01:00",
                                        "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                                    }
                                ],
                            }
                        ]
                    }
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comments-owner")
    FakeXhsPcCommentAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentAdapter
    try:
        response = client.post(
            "/api/xhs/pc/notes/comments",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["items"] == [
            {
                "comment_id": "comment-001",
                "user_name": "Comment author",
                "user_id": "user-001",
                "content": "Top level comment",
                "like_count": 12,
                "parent_comment_id": None,
                "created_at_remote": "2026-04-29 12:00:00",
                "raw_json": {
                    "id": "comment-001",
                    "content": "Top level comment",
                    "like_count": "12",
                    "create_time": "2026-04-29 12:00:00",
                    "user_info": {"user_id": "user-001", "nickname": "Comment author"},
                    "sub_comments": [
                        {
                            "id": "comment-001-1",
                            "content": "Reply content",
                            "like_count": 3,
                            "create_time": "2026-04-29 12:01:00",
                            "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                        }
                    ],
                },
            },
            {
                "comment_id": "comment-001-1",
                "user_name": "Reply author",
                "user_id": "user-002",
                "content": "Reply content",
                "like_count": 3,
                "parent_comment_id": "comment-001",
                "created_at_remote": "2026-04-29 12:01:00",
                "raw_json": {
                    "id": "comment-001-1",
                    "content": "Reply content",
                    "like_count": 3,
                    "create_time": "2026-04-29 12:01:00",
                    "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                },
            },
        ]
        assert FakeXhsPcCommentAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "note_url": "https://www.xiaohongshu.com/explore/comment-note-001",
            }
        ]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_xhs_pc_note_comments_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user comments must not instantiate adapter")

    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "comments-cross-owner")
    intruder_token = _register_and_get_access_token("comments-cross-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/pc/notes/comments",
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/notes/comments",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_notes_batch_save_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/notes/batch-save",
            json={"account_id": 1, "notes": [{"note_id": "note-001", "title": "标题"}]},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_save_persists_owned_search_results_and_updates_duplicates(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Note

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "save-owner")
    try:
        first_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-save-001",
                        "title": "第一版标题",
                        "content": "第一版正文",
                        "author_name": "作者 A",
                        "raw": {"source": "search", "version": 1},
                    }
                ],
            },
        )
        assert first_response.status_code == 200
        first_payload = first_response.json()
        assert first_payload["saved_count"] == 1
        assert first_payload["items"][0]["note_id"] == "note-save-001"
        assert first_payload["items"][0]["title"] == "第一版标题"

        second_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-save-001",
                        "title": "第二版标题",
                        "content": "第二版正文",
                        "author_name": "作者 B",
                        "raw": {"source": "search", "version": 2},
                    }
                ],
            },
        )
        assert second_response.status_code == 200
        assert second_response.json()["saved_count"] == 1

        db = next(app.dependency_overrides[get_db]())
        try:
            notes = db.query(Note).all()
            assert len(notes) == 1
            assert notes[0].platform == "xhs"
            assert notes[0].platform_account_id == account_id
            assert notes[0].note_id == "note-save-001"
            assert notes[0].title == "第二版标题"
            assert notes[0].content == "第二版正文"
            assert notes[0].author_name == "作者 B"
            assert notes[0].raw_json == {"source": "search", "version": 2}
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_save_derives_published_at_from_raw(tmp_path):
    """采集入库时必须把发布时间写进列，而不是只留在 raw_json 里。

    704 篇笔记的 `published_at` 曾经全是 NULL，而 raw 里 463 条明明能解析。
    这不是解析能力缺失（`extract_note_metrics` 早就返回了解析结果），
    而是 `batch_save_notes` 把这个值丢掉了——于是「最近发布」永远 0 条，
    低粉爆款的时间窗也筛不出东西。
    """
    from backend.app.core.database import get_db
    from backend.app.models import Note
    from backend.app.services.note_metrics_service import parse_published_at

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(
        tmp_path, "save-published-owner"
    )
    try:
        # 1) 第一次采集：raw 里没有时间 → 保持 NULL，不能瞎猜成「现在」
        first = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-published-001",
                        "title": "没有时间的笔记",
                        "content": "正文",
                        "raw": {"source": "search"},
                    }
                ],
            },
        )
        assert first.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            note = db.query(Note).filter(Note.note_id == "note-published-001").one()
            assert note.published_at is None
        finally:
            db.close()

        # 2) 补采：raw 带 web 卡片时间（秒），应当落到列上
        second = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-published-001",
                        "title": "补到时间的笔记",
                        "content": "正文",
                        "raw": {
                            "data": {
                                "items": [
                                    {"note_card": {"time": 1730184000, "title": "卡片标题"}}
                                ]
                            }
                        },
                    }
                ],
            },
        )
        assert second.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            note = db.query(Note).filter(Note.note_id == "note-published-001").one()
            assert note.published_at == parse_published_at(1730184000)
        finally:
            db.close()

        # 3) 重复采集到更早/不同的时间：已解析的发布时间是事实，不许被覆盖
        third = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-published-001",
                        "title": "再采一次",
                        "content": "正文",
                        "raw": {"workPublishTime": "2020-01-01 08:00"},
                    }
                ],
            },
        )
        assert third.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            note = db.query(Note).filter(Note.note_id == "note-published-001").one()
            assert note.published_at == parse_published_at(1730184000)
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_save_persists_detail_assets_and_lists_owned_assets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteAsset

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "save-assets-owner")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-assets-001",
                        "title": "Asset detail title",
                        "content": "Asset detail body",
                        "author_name": "Asset author",
                        "image_urls": [
                            "https://example.test/detail-1.webp",
                            "https://example.test/detail-2.webp",
                        ],
                        "video_addr": "https://example.test/detail-video.mp4",
                        "cover_url": "https://example.test/detail-cover.webp",
                        "raw": {"source": "detail"},
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        saved_payload = save_response.json()["items"][0]
        note_id = saved_payload["id"]
        assert saved_payload["cover_url"] == "https://example.test/detail-1.webp"
        assert saved_payload["asset_urls"] == [
            "https://example.test/detail-1.webp",
            "https://example.test/detail-2.webp",
            "https://example.test/detail-video.mp4",
        ]

        list_response = client.get(
            f"/api/notes/{note_id}/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 3
        assert [(item["asset_type"], item["url"]) for item in payload["items"]] == [
            ("image", "https://example.test/detail-1.webp"),
            ("image", "https://example.test/detail-2.webp"),
            ("video", "https://example.test/detail-video.mp4"),
        ]

        note_detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert note_detail_response.status_code == 200
        assert note_detail_response.json()["asset_urls"] == [
            "https://example.test/detail-1.webp",
            "https://example.test/detail-2.webp",
            "https://example.test/detail-video.mp4",
        ]

        update_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-assets-001",
                        "title": "Asset detail title updated",
                        "image_urls": ["https://example.test/detail-2.webp"],
                    }
                ],
            },
        )
        assert update_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            assets = db.query(NoteAsset).filter(NoteAsset.note_id == note_id).all()
            assert [(asset.asset_type, asset.url) for asset in assets] == [("image", "https://example.test/detail-2.webp")]
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_assets_reject_cross_user_note(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "assets-owner")
    intruder_token = _register_and_get_access_token("assets-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "note-assets-cross-001",
                        "title": "Owner note",
                        "image_urls": ["https://example.test/owner.webp"],
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        response = client.get(
            f"/api/notes/{note_id}/assets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_save_fetches_and_persists_comments(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    class FakeXhsPcCommentPersistAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            self.calls.append({"cookies": self.cookies, "note_url": note_url})
            return (
                True,
                "ok",
                {
                    "data": {
                        "comments": [
                            {
                                "id": "persist-comment-001",
                                "content": "Persisted top comment",
                                "like_count": "8",
                                "create_time": "2026-04-29 13:00:00",
                                "user_info": {"user_id": "persist-user-001", "nickname": "Persist author"},
                            }
                        ]
                    }
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comment-persist-owner")
    FakeXhsPcCommentPersistAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentPersistAdapter
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "fetch_comments": True,
                "notes": [
                    {
                        "note_id": "note-comments-001",
                        "note_url": "https://www.xiaohongshu.com/explore/note-comments-001",
                        "title": "Comment note",
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]
        assert FakeXhsPcCommentPersistAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "note_url": "https://www.xiaohongshu.com/explore/note-comments-001",
            }
        ]

        list_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["comment_id"] == "persist-comment-001"
        assert payload["items"][0]["user_name"] == "Persist author"
        assert payload["items"][0]["user_id"] == "persist-user-001"
        assert payload["items"][0]["content"] == "Persisted top comment"
        assert payload["items"][0]["like_count"] == 8
        assert payload["items"][0]["parent_comment_id"] is None
        assert payload["items"][0]["created_at_remote"] == "2026-04-29 13:00:00"

        db = next(app.dependency_overrides[get_db]())
        try:
            comments = db.query(NoteComment).filter(NoteComment.note_id == note_id).all()
            assert len(comments) == 1
            assert comments[0].raw_json["id"] == "persist-comment-001"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_notes_batch_save_replaces_stale_comments_on_refetch(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentReplaceAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            self.calls.append(note_url)
            comment_id = "stale-comment" if len(self.calls) == 1 else "fresh-comment"
            return (
                True,
                "ok",
                {"data": {"comments": [{"id": comment_id, "content": comment_id, "user_info": {"nickname": "User"}}]}},
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comment-replace-owner")
    FakeXhsPcCommentReplaceAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentReplaceAdapter
    try:
        for _ in range(2):
            save_response = client.post(
                "/api/notes/batch-save",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "account_id": account_id,
                    "fetch_comments": True,
                    "notes": [
                        {
                            "note_id": "note-comments-replace-001",
                            "note_url": "https://www.xiaohongshu.com/explore/note-comments-replace-001",
                            "title": "Replace comments",
                        }
                    ],
                },
            )
            assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]

        list_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["comment_id"] == "fresh-comment"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_notes_comments_list_requires_auth_and_enforces_ownership(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentListAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            return (
                True,
                "ok",
                {"data": {"comments": [{"id": "owned-comment", "content": "Owned", "user_info": {"nickname": "User"}}]}},
            )

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "comments-list-owner")
    intruder_token = _register_and_get_access_token("comments-list-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentListAdapter
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "fetch_comments": True,
                "notes": [
                    {
                        "note_id": "note-comments-owned-001",
                        "note_url": "https://www.xiaohongshu.com/explore/note-comments-owned-001",
                        "title": "Owned comment note",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        anonymous_response = client.get(f"/api/notes/{note_id}/comments")
        assert anonymous_response.status_code == 401

        intruder_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_tags_crud_are_user_scoped_and_validate_duplicates(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("tags-crud-owner")
        intruder_token = _register_and_get_access_token("tags-crud-intruder")

        create_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "High value", "color": "#111111"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "High value"
        assert created["color"] == "#111111"

        duplicate_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "High value", "color": "#ef4444"},
        )
        assert duplicate_response.status_code == 400

        owner_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        intruder_update_response = client.patch(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "Stolen"},
        )
        assert intruder_update_response.status_code == 404

        update_response = client.patch(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Rewrite queue", "color": "#2563eb"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Rewrite queue"
        assert update_response.json()["color"] == "#2563eb"

        intruder_delete_response = client.delete(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_delete_response.status_code == 404

        delete_response = client.delete(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json() == {"id": created["id"], "status": "deleted"}

        empty_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert empty_list_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_tag_applies_and_removes_owned_tags(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-tag-owner")
    try:
        first_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Rewrite", "color": "#111111"},
        ).json()
        second_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Benchmark", "color": "#2563eb"},
        ).json()
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "note-tags-001",
                        "title": "Tagged note",
                        "content": "Tag me",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        replace_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [first_tag["id"]], "mode": "replace"},
        )
        assert replace_response.status_code == 200
        assert replace_response.json()["updated_count"] == 1
        assert replace_response.json()["items"][0]["tags"] == [first_tag]

        add_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [second_tag["id"]], "mode": "add"},
        )
        assert add_response.status_code == 200
        assert [tag["name"] for tag in add_response.json()["items"][0]["tags"]] == ["Rewrite", "Benchmark"]

        remove_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [first_tag["id"]], "mode": "remove"},
        )
        assert remove_response.status_code == 200
        assert remove_response.json()["items"][0]["tags"] == [second_tag]

        detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 200
        assert detail_response.json()["tags"] == [second_tag]

        list_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["tags"] == [second_tag]
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_tag_rejects_cross_user_note_or_tag(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-tag-cross-owner")
    intruder_token = _register_and_get_access_token("batch-tag-cross-intruder")
    try:
        owner_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Owner tag", "color": "#111111"},
        ).json()
        intruder_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "Intruder tag", "color": "#ef4444"},
        ).json()
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "note-tags-cross-001", "title": "Owner note"}],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        intruder_note_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_id], "tag_ids": [intruder_tag["id"]], "mode": "replace"},
        )
        assert intruder_note_response.status_code == 404

        owner_cross_tag_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [intruder_tag["id"]], "mode": "replace"},
        )
        assert owner_cross_tag_response.status_code == 404

        owner_valid_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [owner_tag["id"]], "mode": "replace"},
        )
        assert owner_valid_response.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_create_drafts_creates_owned_drafts_and_rejects_cross_user_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-drafts-owner")
    intruder_token = _register_and_get_access_token("batch-drafts-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {"note_id": "batch-draft-001", "title": "First source", "content": "First body"},
                    {"note_id": "batch-draft-002", "title": "Second source", "content": "Second body"},
                ],
            },
        )
        assert save_response.status_code == 200
        note_ids = [item["id"] for item in save_response.json()["items"]]
        client.put(
            "/api/settings/risk-controls",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"batch_repost_enabled": True, "acknowledge_risk": True},
        )

        response = client.post(
            "/api/notes/batch-create-drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": note_ids, "intent": "rewrite"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["created_count"] == 2
        assert [item["title"] for item in payload["items"]] == ["First source", "Second source"]
        assert [item["body"] for item in payload["items"]] == ["First body", "Second body"]
        assert [item["source_note_id"] for item in payload["items"]] == note_ids

        intruder_response = client.post(
            "/api/notes/batch-create-drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_ids[0]], "intent": "rewrite"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_export_writes_json_for_owned_notes_and_rejects_cross_user_notes(tmp_path):
    import json
    from pathlib import Path

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "notes-export-owner")
    intruder_token = _register_and_get_access_token("notes-export-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "export-note-001",
                        "title": "Exported note",
                        "content": "Export body",
                        "author_name": "Export author",
                        "raw": {"source": "unit-test"},
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]
        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Export", "color": "#111111"},
        )
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [tag_response.json()["id"]], "mode": "replace"},
        )

        response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "format": "json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["exported_count"] == 1
        assert payload["file_name"].endswith(".json")
        assert f"u{1}-" in payload["file_name"]
        export_path = Path(payload["file_path"])
        assert export_path.exists()
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        assert exported["items"][0]["note_id"] == "export-note-001"
        assert exported["items"][0]["tags"][0]["name"] == "Export"

        download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.json()["items"][0]["note_id"] == "export-note-001"

        intruder_download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_download_response.status_code == 404

        intruder_response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_id], "format": "json"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_export_writes_csv_for_owned_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "notes-export-csv-owner")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "export-csv-001",
                        "title": "CSV 标题",
                        "content": "CSV 正文",
                        "author_name": "CSV 作者",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "format": "csv"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["file_name"].endswith(".csv")
        download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        csv_text = download_response.content.decode("utf-8-sig")
        assert "note_id,title,author_id,author_name,author_fans,likes,collects,comments,shares,like_fan_ratio,engagement_rate,content,tags,created_at" in csv_text
        assert "export-csv-001" in csv_text
        assert "CSV 标题" in csv_text
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_analytics_uses_current_user_saved_notes_tags_and_comments(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "analytics-owner")
    intruder_token = _register_and_get_access_token("analytics-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "analytics-note-001",
                        "title": "高互动早餐笔记",
                        "content": "早餐选题正文",
                        "author_name": "早餐作者",
                        "raw": {"likes": 100, "collects": 30, "comments": 12, "shares": 8, "tags": ["早餐", "低卡"]},
                    },
                    {
                        "note_id": "analytics-note-002",
                        "title": "普通收纳笔记",
                        "content": "收纳正文",
                        "author_name": "收纳作者",
                        "raw": {"likes": 10, "collects": 2, "comments": 1, "shares": 0, "tags": ["收纳"]},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        first_note_id = save_response.json()["items"][0]["id"]
        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐", "color": "#111111"},
        )
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [first_note_id], "tag_ids": [tag_response.json()["id"]], "mode": "add"},
        )
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                NoteComment(
                    note_id=first_note_id,
                    comment_id="analytics-comment-001",
                    user_name="用户 A",
                    content="这个早餐适合通勤吗？价格会不会高？",
                    like_count=9,
                )
            )
            db.commit()
        finally:
            db.close()

        overview_response = client.get(
            "/api/xhs/analytics/overview",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert overview_response.status_code == 200
        overview = overview_response.json()
        assert overview["platform"] == "xhs"
        assert overview["saved_notes"] == 2
        assert overview["total_engagement"] == 163
        assert overview["comment_count"] == 1
        assert overview["hot_topics"][0]["keyword"] == "早餐"

        top_response = client.get(
            "/api/xhs/analytics/top-content",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert top_response.status_code == 200
        top_items = top_response.json()["items"]
        assert [item["note_id"] for item in top_items] == ["analytics-note-001", "analytics-note-002"]
        assert top_items[0]["engagement"] == 150

        topics_response = client.get(
            "/api/xhs/analytics/hot-topics",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert topics_response.status_code == 200
        topics = topics_response.json()["items"]
        assert topics[0]["keyword"] == "早餐"
        assert topics[0]["notes"] == 1
        assert topics[0]["engagement"] == 150

        comments_response = client.get(
            "/api/xhs/analytics/comment-insights",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert comments_response.status_code == 200
        comments = comments_response.json()
        assert comments["total_comments"] == 1
        assert comments["question_count"] == 1
        assert comments["top_comments"][0]["content"] == "这个早餐适合通勤吗？价格会不会高？"

        intruder_response = client.get(
            "/api/xhs/analytics/overview",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["saved_notes"] == 0
        assert intruder_response.json()["total_engagement"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_follower_filter_reports_how_many_it_skipped(tmp_path):
    """The follower filter must say what it hid.

    ``GET /analytics/low-fan-notes`` used to carry this warning, but nothing
    called it - the sample library filters through ``GET /notes``. So the count
    simply shrank with no explanation.
    """
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(
        tmp_path, "low-fan-owner"
    )
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "low-fan-measured",
                        "title": "measured sample",
                        "content": "body",
                        "author_id": "author-measured",
                        "author_fans": 800,
                        "likes": 5000,
                    },
                    {
                        "note_id": "low-fan-unmeasured",
                        "title": "unmeasured sample",
                        "content": "body",
                        "author_id": "author-unmeasured",
                        "likes": 4000,
                    },
                ],
            },
        )
        assert save_response.status_code == 200

        response = client.get(
            "/api/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            params={"platform": "xhs", "source": "library", "max_fans": 10000},
        )
        assert response.status_code == 200
        payload = response.json()

        # Only the measured note qualifies; the other cannot be judged.
        assert [item["note_id"] for item in payload["items"]] == ["low-fan-measured"]
        # And the response says one sample was skipped for lack of data.
        assert payload["unmeasured_fans"] == 1
        assert "1" in payload["filter_note"]

    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_without_follower_filter_do_not_mention_skipped_samples(tmp_path):
    """No filter, no caveat - the note must not appear out of context."""
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(
        tmp_path, "no-filter-owner"
    )
    try:
        client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "plain-note",
                        "title": "plain sample",
                        "content": "body",
                        "likes": 10,
                    }
                ],
            },
        )

        response = client.get(
            "/api/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            params={"platform": "xhs"},
        )
        payload = response.json()

        assert "filter_note" not in payload
        assert "unmeasured_fans" not in payload

    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_analytics_benchmarks_are_user_scoped_from_monitoring_targets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import MonitoringTarget

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "benchmark-owner")
    intruder_token = _register_and_get_access_token("benchmark-intruder")
    try:
        anonymous_response = client.get("/api/xhs/analytics/benchmarks")
        assert anonymous_response.status_code == 401

        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "benchmark-note-account",
                        "title": "竞品账号低卡早餐",
                        "content": "creator-001 的早餐选题",
                        "author_name": "creator-001",
                        "raw": {"likes": 80, "collects": 12, "comments": 6, "shares": 2},
                    },
                    {
                        "note_id": "benchmark-note-brand",
                        "title": "BrandA 收纳爆文",
                        "content": "BrandA 新品收纳角度",
                        "author_name": "brand-author",
                        "raw": {"likes": 30, "collects": 10, "comments": 4, "shares": 1},
                    },
                    {
                        "note_id": "benchmark-note-keyword-only",
                        "title": "低卡早餐普通趋势",
                        "content": "低卡早餐关键词命中但不是竞品目标",
                        "author_name": "trend-author",
                        "raw": {"likes": 300},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="account",
                        name="竞品账号",
                        value="creator-001",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="brand",
                        name="BrandA",
                        value="BrandA",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="keyword",
                        name="低卡早餐",
                        value="低卡早餐",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=2,
                        platform="xhs",
                        target_type="account",
                        name="Other account",
                        value="creator-001",
                        status="active",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/xhs/analytics/benchmarks",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_targets"] == 2
        assert payload["matched_notes"] == 2
        assert payload["total_engagement"] == 145
        assert [item["target_type"] for item in payload["items"]] == ["account", "brand"]
        assert payload["items"][0]["name"] == "竞品账号"
        assert payload["items"][0]["matched_notes"] == 1
        assert payload["items"][0]["total_engagement"] == 100
        assert payload["items"][0]["top_notes"][0]["note_id"] == "benchmark-note-account"
        assert payload["items"][1]["name"] == "BrandA"
        assert payload["items"][1]["total_engagement"] == 45

        intruder_response = client.get(
            "/api/xhs/analytics/benchmarks",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total_targets"] == 1
        assert intruder_response.json()["matched_notes"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_benchmark_create_drafts_uses_owned_target_matches(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft, MonitoringTarget

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "benchmark-draft-owner")
    intruder_token = _register_and_get_access_token("benchmark-draft-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "benchmark-draft-note-001",
                        "title": "creator-002 爆款标题",
                        "content": "creator-002 的爆款正文",
                        "author_name": "creator-002",
                        "raw": {"likes": 90},
                    },
                    {
                        "note_id": "benchmark-draft-note-002",
                        "title": "creator-002 第二篇",
                        "content": "creator-002 的第二篇正文",
                        "author_name": "creator-002",
                        "raw": {"likes": 40},
                    },
                    {
                        "note_id": "benchmark-draft-note-other",
                        "title": "其他账号内容",
                        "content": "不该命中",
                        "author_name": "other",
                        "raw": {"likes": 500},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        db = next(app.dependency_overrides[get_db]())
        try:
            target = MonitoringTarget(
                user_id=1,
                platform="xhs",
                target_type="account",
                name="creator-002",
                value="creator-002",
                status="active",
            )
            keyword_target = MonitoringTarget(
                user_id=1,
                platform="xhs",
                target_type="keyword",
                name="普通关键词",
                value="creator-002",
                status="active",
            )
            intruder_target = MonitoringTarget(
                user_id=2,
                platform="xhs",
                target_type="account",
                name="intruder target",
                value="creator-002",
                status="active",
            )
            db.add_all([target, keyword_target, intruder_target])
            db.commit()
            target_id = target.id
            keyword_target_id = keyword_target.id
        finally:
            db.close()

        anonymous_response = client.post(f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts")
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        keyword_response = client.post(
            f"/api/xhs/analytics/benchmarks/{keyword_target_id}/create-drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert keyword_response.status_code == 400

        response = client.post(
            f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts?limit=1",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["created_count"] == 1
        assert payload["items"][0]["title"] == "creator-002 爆款标题"
        assert payload["items"][0]["source_note_id"] == save_response.json()["items"][0]["id"]

        db = next(app.dependency_overrides[get_db]())
        try:
            drafts = db.query(AiDraft).all()
            assert len(drafts) == 1
            assert drafts[0].user_id == 1
            assert drafts[0].platform == "xhs"
            assert drafts[0].body == "creator-002 的爆款正文"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_analytics_report_generates_owned_json_export_and_rejects_cross_user_notes(tmp_path):
    import json
    from pathlib import Path

    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "analytics-report-owner")
    intruder_token = _register_and_get_access_token("analytics-report-intruder")
    try:
        anonymous_response = client.post("/api/xhs/analytics/reports")
        assert anonymous_response.status_code == 401

        owner_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "analytics-report-note-001",
                        "title": "Report note one",
                        "content": "Breakfast content with BrandA",
                        "author_name": "creator-report",
                        "raw": {"likes": 20, "collects": 5, "comments": 3, "shares": 2, "tags": ["breakfast"]},
                    },
                    {
                        "note_id": "analytics-report-note-002",
                        "title": "Report note two",
                        "content": "Storage content",
                        "author_name": "creator-report",
                        "raw": {"likes": 10, "collects": 1, "comments": 0, "shares": 0, "tags": ["storage"]},
                    },
                ],
            },
        )
        assert owner_save_response.status_code == 200
        owner_note_ids = [item["id"] for item in owner_save_response.json()["items"]]

        db = next(app.dependency_overrides[get_db]())
        try:
            intruder_account = PlatformAccount(
                user_id=2,
                platform="xhs",
                sub_type="pc",
                external_user_id="analytics-report-intruder",
                nickname="Intruder",
                status="active",
            )
            db.add(intruder_account)
            db.commit()
            intruder_account_id = intruder_account.id
        finally:
            db.close()

        intruder_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={
                "account_id": intruder_account_id,
                "notes": [
                    {
                        "note_id": "analytics-report-intruder-note",
                        "title": "Intruder note",
                        "content": "Not visible to owner",
                        "author_name": "intruder",
                        "raw": {"likes": 999},
                    }
                ],
            },
        )
        assert intruder_save_response.status_code == 200
        intruder_note_id = intruder_save_response.json()["items"][0]["id"]

        forbidden_response = client.post(
            "/api/xhs/analytics/reports",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [owner_note_ids[0], intruder_note_id], "format": "json"},
        )
        assert forbidden_response.status_code == 404

        report_response = client.post(
            "/api/xhs/analytics/reports",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": owner_note_ids, "format": "json"},
        )
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["report_type"] == "operations"
        assert report["note_count"] == 2
        assert report["summary"]["total_engagement"] == 41
        assert report["summary"]["top_notes"][0]["note_id"] == "analytics-report-note-001"
        assert report["file_name"].startswith("xhs-report-u1-")
        assert report["download_url"].startswith("/api/files/exports/xhs-report-u1-")

        report_path = Path(report["file_path"])
        assert report_path.is_file()
        report_file = json.loads(report_path.read_text(encoding="utf-8"))
        assert report_file["metadata"]["user_id"] == 1
        assert report_file["summary"]["note_count"] == 2
        assert report_file["top_notes"][0]["title"] == "Report note one"

        download_response = client.get(
            report["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.json()["metadata"]["report_type"] == "operations"

        intruder_download_response = client.get(
            report["download_url"],
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_download_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_crawl_routes_are_authenticated_task_backed_and_persist_notes(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Note, NoteAsset, Task

    class FakeCrawlAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def search_note(self, keyword, page=1, **kwargs):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-search-001",
                                "display_title": f"{keyword} search title",
                                "desc": "search content",
                                "user": {"nickname": "search author"},
                                "interact_info": {"liked_count": 12, "collected_count": 3, "comment_count": 2},
                                "cover": {"url": "https://img.example/search.png"},
                            }
                        }
                    ],
                    "total": 1,
                    "has_more": False,
                }
            }

        def get_note_info(self, url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-url-001",
                                "display_title": "url detail title",
                                "desc": "url detail body",
                                "user": {"nickname": "url author"},
                                "interact_info": {"liked_count": 30},
                                "image_list": [{"url": "https://img.example/url-1.png"}],
                            }
                        }
                    ]
                }
            }

        def get_user_notes(self, user_url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-user-001",
                                "display_title": "user note title",
                                "desc": "user note body",
                                "user": {"nickname": "profile author"},
                                "interact_info": {"liked_count": 7},
                                "cover": {"url": "https://img.example/user.png"},
                            }
                        }
                    ],
                    "total": 1,
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "crawl-routes-owner")
    intruder_token = _register_and_get_access_token("crawl-routes-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeCrawlAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/crawl/search-notes",
            json={"account_id": owner_account_id, "keyword": "breakfast"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/crawl/search-notes",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": owner_account_id, "keyword": "breakfast"},
        )
        assert intruder_response.status_code == 404

        search_response = client.post(
            "/api/xhs/crawl/search-notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "keyword": "breakfast", "page": 1},
        )
        assert search_response.status_code == 200
        search_payload = search_response.json()
        assert search_payload["task"]["task_type"] == "crawl"
        assert search_payload["task"]["status"] == "completed"
        assert search_payload["saved_count"] == 1
        assert search_payload["items"][0]["note_id"] == "crawl-search-001"

        url_response = client.post(
            "/api/xhs/crawl/note-urls",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "urls": ["https://www.xiaohongshu.com/explore/crawl-url-001"]},
        )
        assert url_response.status_code == 200
        assert url_response.json()["saved_count"] == 1
        assert url_response.json()["items"][0]["note_id"] == "crawl-url-001"

        user_response = client.post(
            "/api/xhs/crawl/user-notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "user_url": "https://www.xiaohongshu.com/user/profile/demo"},
        )
        assert user_response.status_code == 200
        assert user_response.json()["saved_count"] == 1
        assert user_response.json()["items"][0]["note_id"] == "crawl-user-001"

        db = next(app.dependency_overrides[get_db]())
        try:
            tasks = db.query(Task).filter(Task.task_type == "crawl").all()
            notes = db.query(Note).order_by(Note.note_id.asc()).all()
            assets = db.query(NoteAsset).all()
            assert len(tasks) == 3
            assert all(task.user_id == 1 and task.status == "completed" for task in tasks)
            assert [note.note_id for note in notes] == ["crawl-search-001", "crawl-url-001", "crawl-user-001"]
            assert len(assets) == 3
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_data_crawl_marks_partial_failures_and_fetches_comments(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeDataCrawlAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_info(self, url):
            self.__class__.calls.append(("detail", url))
            if "bad" in url:
                return False, "detail failed", {}
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "data-url-001",
                                "display_title": "data crawl detail",
                                "desc": "detail body",
                                "user": {"nickname": "detail author"},
                                "interact_info": {"liked_count": 8, "comment_count": 1},
                                "image_list": [{"url": "https://img.example/data-url.png"}],
                            }
                        }
                    ]
                }
            }

        def get_note_comments(self, url):
            self.__class__.calls.append(("comments", url))
            return True, "ok", {
                "data": {
                    "comments": [
                        {
                            "id": "comment-001",
                            "content": "想看更多",
                            "user_info": {"nickname": "reader"},
                            "like_count": "3",
                        }
                    ]
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "data-crawl-owner")
    FakeDataCrawlAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeDataCrawlAdapter
    try:
        response = client.post(
            "/api/xhs/crawl/data",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "mode": "note_urls",
                "urls": [
                    "https://www.xiaohongshu.com/explore/data-url-001",
                    "https://www.xiaohongshu.com/explore/bad-url",
                ],
                "fetch_comments": True,
            },
        )

        assert response.status_code == 200
        payload = _parse_sse_response(response)
        assert payload["total"] == 2
        assert payload["success_count"] == 1
        assert payload["failed_count"] == 1
        assert payload["items"][0]["status"] == "success"
        assert payload["items"][0]["note"]["note_id"] == "data-url-001"
        assert payload["items"][0]["comment_count"] == 1
        assert payload["items"][0]["comments"][0]["content"] == "想看更多"
        assert payload["items"][1]["status"] == "failed"
        assert payload["items"][1]["error"] == "detail failed"
        assert ("comments", "https://www.xiaohongshu.com/explore/data-url-001") in FakeDataCrawlAdapter.calls
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_data_crawl_search_expands_filters_and_fetches_details(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeSearchDataCrawlAdapter:
        search_calls = []
        detail_calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def search_note(self, keyword, page=1, **kwargs):
            self.__class__.search_calls.append({"keyword": keyword, "page": page, **kwargs})
            return True, "ok", {
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "xsec_token": "xsec-data-search",
                            "note_card": {
                                "note_id": "data-search-001",
                                "display_title": "search source title",
                                "desc": "search source body",
                                "user": {"nickname": "search author"},
                                "interact_info": {"liked_count": 12},
                                "cover": {"url": "https://img.example/search.png"},
                            },
                        }
                    ],
                }
            }

        def get_note_info(self, url):
            self.__class__.detail_calls.append(url)
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "data-search-001",
                                "display_title": "detail title",
                                "desc": "detail body",
                                "user": {"nickname": "detail author"},
                                "interact_info": {"liked_count": 88},
                                "image_list": [{"url": "https://img.example/detail.png"}],
                            }
                        }
                    ]
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "data-crawl-search-owner")
    FakeSearchDataCrawlAdapter.search_calls = []
    FakeSearchDataCrawlAdapter.detail_calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeSearchDataCrawlAdapter
    try:
        response = client.post(
            "/api/xhs/crawl/data",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "mode": "search",
                "keyword": "低卡早餐",
                "pages": 1,
                "max_notes": 5,
                "sort_type_choice": 2,
                "note_type": 2,
                "note_time": 1,
                "note_range": 3,
                "pos_distance": 1,
                "geo": "31.2304,121.4737",
            },
        )

        assert response.status_code == 200
        payload = _parse_sse_response(response)
        assert payload["success_count"] == 1
        assert payload["items"][0]["note"]["title"] == "detail title"
        assert FakeSearchDataCrawlAdapter.search_calls == [
            {
                "keyword": "低卡早餐",
                "page": 1,
                "sort_type_choice": 2,
                "note_type": 2,
                "note_time": 1,
                "note_range": 3,
                "pos_distance": 1,
                "geo": "31.2304,121.4737",
            }
        ]
        assert FakeSearchDataCrawlAdapter.detail_calls == [
            "https://www.xiaohongshu.com/explore/data-search-001?xsec_token=xsec-data-search&xsec_source=pc_feed"
        ]
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_analytics_keyword_trends_are_user_scoped_from_keyword_groups(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import KeywordGroup

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "keyword-trends-owner")
    intruder_token = _register_and_get_access_token("keyword-trends-intruder")
    try:
        anonymous_response = client.get("/api/xhs/analytics/keyword-trends")
        assert anonymous_response.status_code == 401

        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "keyword-trend-note-001",
                        "title": "Breakfast angle",
                        "content": "Low calorie breakfast for commute",
                        "author_name": "trend author",
                        "raw": {"likes": 20, "collects": 5, "comments": 1, "shares": 0},
                    },
                    {
                        "note_id": "keyword-trend-note-002",
                        "title": "Storage angle",
                        "content": "Closet storage checklist",
                        "author_name": "trend author",
                        "raw": {"likes": 10, "collects": 2},
                    },
                ],
            },
        )
        assert save_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    KeywordGroup(user_id=1, platform="xhs", name="Owner ideas", keywords=["breakfast", "storage"]),
                    KeywordGroup(user_id=2, platform="xhs", name="Intruder ideas", keywords=["breakfast"]),
                ]
            )
            db.commit()
        finally:
            db.close()

        owner_response = client.get(
            "/api/xhs/analytics/keyword-trends",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        owner_items = owner_response.json()["items"]
        assert [item["keyword"] for item in owner_items] == ["breakfast", "storage"]
        assert owner_items[0]["group_name"] == "Owner ideas"
        assert owner_items[0]["notes"] == 1
        assert owner_items[0]["engagement"] == 26
        assert owner_items[0]["top_notes"][0]["note_id"] == "keyword-trend-note-001"
        assert owner_items[1]["engagement"] == 12

        intruder_response = client.get(
            "/api/xhs/analytics/keyword-trends",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["items"][0]["keyword"] == "breakfast"
        assert intruder_response.json()["items"][0]["notes"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_creator_routes_use_owned_creator_account_and_record_tasks(tmp_path):
    from backend.app.api.platforms.xhs.creator import get_creator_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorRoutesAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_topic(self, keyword):
            return True, "ok", {"data": {"items": [{"id": "topic-creator", "name": keyword}]}}

        def get_location_info(self, keyword):
            return True, "ok", {"data": {"items": [{"id": "loc-creator", "name": keyword}]}}

        def upload_media(self, file_path, media_type):
            return {"fileIds": "file-creator-001", "width": 1080, "height": 1440, "media_type": media_type}

        def post_note(self, note_info):
            return {"success": True, "data": {"note_id": "creator-direct-note"}, "note_info": {"media_type": note_info.get("media_type"), "title": note_info.get("title")}}

        def resolve_media_bytes(self, file_path):
            return b"video-bytes"

        def get_published_notes(self):
            return True, "ok", {"data": {"items": [{"note_id": "published-001", "title": "Published"}]}}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "creator-routes-owner"
    )
    intruder_token = _register_and_get_access_token("creator-routes-intruder")
    app.dependency_overrides[get_creator_api_adapter_factory] = lambda: FakeCreatorRoutesAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/creator/topics/search",
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/creator/topics/search",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert intruder_response.status_code == 404

        topic_response = client.post(
            "/api/xhs/creator/topics/search",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert topic_response.status_code == 200
        assert topic_response.json()["items"][0]["name"] == "breakfast"

        location_response = client.post(
            "/api/xhs/creator/locations/search",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "keyword": "Shanghai"},
        )
        assert location_response.status_code == 200
        assert location_response.json()["items"][0]["id"] == "loc-creator"

        upload_response = client.post(
            "/api/xhs/creator/assets/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "file_path": "storage/media/cover.png", "media_type": "image"},
        )
        assert upload_response.status_code == 200
        assert upload_response.json()["payload"]["fileIds"] == "file-creator-001"
        assert upload_response.json()["task"]["task_type"] == "creator_direct_upload"

        publish_response = client.post(
            "/api/xhs/creator/publish/image",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Direct title",
                "body": "Direct body",
                "image_file_infos": [{"fileIds": "file-creator-001", "width": 1080, "height": 1440}],
            },
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["payload"]["data"]["note_id"] == "creator-direct-note"
        assert publish_response.json()["task"]["task_type"] == "creator_direct_publish"

        video_response = client.post(
            "/api/xhs/creator/publish/video",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Video title",
                "body": "Video body",
                "video_path": "storage/media/video.mp4",
            },
        )
        assert video_response.status_code == 200
        assert video_response.json()["payload"]["note_info"]["media_type"] == "video"

        published_response = client.get(
            f"/api/xhs/creator/published?account_id={creator_account_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert published_response.status_code == 200
        assert published_response.json()["items"][0]["note_id"] == "published-001"

        db = next(app.dependency_overrides[get_db]())
        try:
            tasks = db.query(Task).filter(Task.task_type.in_(["creator_direct_upload", "creator_direct_publish"])).all()
            assert [task.status for task in tasks] == ["completed", "completed", "completed"]
            assert all(task.user_id == 1 for task in tasks)
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_xhs_creator_direct_publish_accepts_optional_publish_parameters(tmp_path):
    from backend.app.api.platforms.xhs.creator import get_creator_api_adapter_factory

    class FakeCreatorOptionalAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"success": True, "data": {"note_id": "optional-note"}, "note_info": note_info}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "creator-optional-owner"
    )
    FakeCreatorOptionalAdapter.calls = []
    app.dependency_overrides[get_creator_api_adapter_factory] = lambda: FakeCreatorOptionalAdapter
    try:
        image_response = client.post(
            "/api/xhs/creator/publish/image",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Direct optional title",
                "image_file_infos": [{"fileIds": "file-optional", "width": 1080, "height": 1440}],
                "topics": ["早餐", "通勤"],
                "location": "上海",
                "is_private": False,
            },
        )

        assert image_response.status_code == 200
        assert FakeCreatorOptionalAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Direct optional title",
                    "desc": "",
                    "media_type": "image",
                    "image_file_infos": [{"fileIds": "file-optional", "width": 1080, "height": 1440}],
                    "type": 0,
                    "postTime": None,
                    "topics": ["早餐", "通勤"],
                    "location": "上海",
                },
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_monitoring_targets_crud_are_user_scoped(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("monitoring-owner")
    intruder_token = _register_and_get_access_token("monitoring-intruder")
    try:
        anonymous_response = client.get("/api/xhs/monitoring/targets")
        assert anonymous_response.status_code == 401

        create_response = client.post(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "target_type": "keyword",
                "name": "早餐趋势",
                "value": "低卡早餐",
                "config": {"frequency": "daily"},
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["target_type"] == "keyword"
        assert created["name"] == "早餐趋势"
        assert created["value"] == "低卡早餐"
        assert created["status"] == "active"

        owner_list_response = client.get(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        update_response = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐趋势组", "status": "paused"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "早餐趋势组"
        assert update_response.json()["status"] == "paused"

        intruder_update_response = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "偷看"},
        )
        assert intruder_update_response.status_code == 404

        delete_response = client.delete(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json() == {"id": created["id"], "status": "deleted"}
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_monitoring_targets_refresh_creates_owned_task(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeMonitoringAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_user_notes(self, user_url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawled-note-001",
                                "display_title": "竞品账号低卡早餐",
                                "desc": "creator-001 的早餐选题",
                                "user": {"nickname": "creator-001"},
                                "interact_info": {"liked_count": 50, "collected_count": 20, "comment_count": 3},
                                "cover": {"url": "https://img.example/cover.png"},
                            }
                        }
                    ],
                    "total": 1,
                    "has_more": False,
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "monitoring-refresh-owner")
    intruder_token = _register_and_get_access_token("monitoring-refresh-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeMonitoringAdapter
    try:
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"target_type": "account", "name": "竞品账号", "value": "creator-001"},
        ).json()

        refresh_response = client.post(
            f"/api/xhs/monitoring/targets/{created['id']}/refresh",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert refresh_response.status_code == 200
        payload = refresh_response.json()
        assert payload["target"]["id"] == created["id"]
        assert payload["task"]["task_type"] == "monitoring_crawl"
        assert payload["task"]["status"] == "completed"
        assert payload["task"]["payload"]["target_id"] == created["id"]
        assert payload["task"]["payload"]["crawled_count"] == 1
        assert payload["snapshot"]["payload"]["matched_count"] >= 1
        assert payload["snapshot"]["payload"]["top_notes"][0]["note_id"] == "crawled-note-001"
        assert payload["target"]["consecutive_failures"] == 0

        tasks_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tasks_response.status_code == 200
        assert tasks_response.json()["items"][0]["task_type"] == "monitoring_crawl"

        notes_response = client.get(
            f"/api/xhs/monitoring/targets/{created['id']}/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert notes_response.status_code == 200
        assert len(notes_response.json()["items"]) >= 1

        # 竞品抓取结果必须真正进入内容库
        library_response = client.get(
            "/api/notes",
            params={"platform": "xhs", "q": "crawled-note-001"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert library_response.status_code == 200
        assert any(
            item["note_id"] == "crawled-note-001" for item in library_response.json()["items"]
        )

        snapshots_response = client.get(
            f"/api/xhs/monitoring/targets/{created['id']}/snapshots",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert snapshots_response.status_code == 200
        assert snapshots_response.json()["items"][0]["payload"]["matched_count"] >= 1

        intruder_response = client.post(
            f"/api/xhs/monitoring/targets/{created['id']}/refresh",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_crawl_rate_limiter_blocks_after_max_requests():
    from backend.app.services.rate_limiter import CrawlRateLimiter

    limiter = CrawlRateLimiter(max_per_minute=3)
    assert limiter.allow(1) is True
    assert limiter.allow(1) is True
    assert limiter.allow(1) is True
    assert limiter.allow(1) is False

    assert limiter.allow(2) is True

    limiter.reset(1)
    assert limiter.allow(1) is True


def test_keyword_groups_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/keyword-groups")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_keyword_groups_crud_are_user_scoped(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "keyword-group-owner")
    intruder_token = _register_and_get_access_token("keyword-group-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "keyword-note-001",
                        "title": "低卡早餐模板",
                        "content": "适合通勤的低卡早餐搭配。",
                        "author_name": "早餐作者",
                        "raw": {"likes": 30, "collects": 10, "comments": 4, "shares": 1, "tags": ["低卡", "早餐"]},
                    },
                    {
                        "note_id": "keyword-note-002",
                        "title": "家居收纳灵感",
                        "content": "收纳工具清单。",
                        "author_name": "收纳作者",
                        "raw": {"likes": 2, "collects": 1, "comments": 0, "shares": 0, "tags": ["收纳"]},
                    },
                    {
                        "note_id": "keyword-note-own",
                        "title": "我自己的低卡早餐复盘",
                        "content": "低卡早餐的发布复盘。",
                        "author_name": "我自己",
                        "raw": {
                            "likes": 999,
                            "collects": 0,
                            "comments": 0,
                            "shares": 0,
                            "source": "creator_published",
                        },
                    },
                ],
            },
        )
        assert save_response.status_code == 200

        create_response = client.post(
            "/api/keyword-groups",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "name": "早餐机会", "keywords": ["低卡", "早餐"]},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "早餐机会"
        assert created["keywords"] == ["低卡", "早餐"]

        owner_list_response = client.get("/api/keyword-groups", headers={"Authorization": f"Bearer {owner_token}"})
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get("/api/keyword-groups", headers={"Authorization": f"Bearer {intruder_token}"})
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        detail_response = client.get(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["trend"]["total_matches"] == 1
        assert detail["trend"]["total_engagement"] == 45
        assert detail["trend"]["keywords"][0]["keyword"] == "低卡"
        assert detail["trend"]["matched_notes"][0]["note_id"] == "keyword-note-001"
        assert all(
            item["note_id"] != "keyword-note-own"
            for item in detail["trend"]["matched_notes"]
        )

        patch_response = client.patch(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐选题池", "keywords": ["早餐"]},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "早餐选题池"
        assert patch_response.json()["keywords"] == ["早餐"]

        cross_get_response = client.get(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert cross_get_response.status_code == 404

        cross_patch_response = client.patch(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "偷看"},
        )
        assert cross_patch_response.status_code == 404

        delete_response = client.delete(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_batch_save_rejects_cross_user_account(tmp_path):
    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "save-owner-2")
    intruder_token = _register_and_get_access_token("save-intruder")
    try:
        response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "notes": [{"note_id": "note-001", "title": "标题"}]},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_library_list_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/notes?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_library_list_returns_only_current_user_saved_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-owner")
    intruder_token = _register_and_get_access_token("library-intruder")
    try:
        owner_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "owner-note-001",
                        "title": "我的内容库笔记",
                        "content": "这条应该只属于 owner。",
                        "author_name": "作者 Owner",
                        "raw": {"source": "owner"},
                    }
                ],
            },
        )
        assert owner_save_response.status_code == 200

        intruder_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total"] == 0

        owner_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        payload = owner_response.json()
        assert payload["total"] == 1
        assert payload["page"] == 1
        assert payload["page_size"] == 20
        assert payload["items"][0]["note_id"] == "owner-note-001"
        assert payload["items"][0]["title"] == "我的内容库笔记"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_library_filters_by_keyword_tag_assets_and_comments(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-filter-owner")
    intruder_token = _register_and_get_access_token("library-filter-intruder")
    try:
        first_save = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "filter-note-assets",
                        "title": "低卡早餐灵感",
                        "content": "适合通勤前快速准备。",
                        "author_name": "早餐研究员",
                        "image_urls": ["https://example.test/filter-assets.webp"],
                    },
                    {
                        "note_id": "filter-note-comments",
                        "title": "旅行收纳清单",
                        "content": "评论里有很多问题。",
                        "author_name": "收纳作者",
                    },
                ],
            },
        )
        assert first_save.status_code == 200
        asset_note_id = first_save.json()["items"][0]["id"]
        comment_note_id = first_save.json()["items"][1]["id"]

        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Breakfast", "color": "#111111"},
        )
        tag_id = tag_response.json()["id"]
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [asset_note_id], "tag_ids": [tag_id], "mode": "replace"},
        )
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                NoteComment(
                    note_id=comment_note_id,
                    comment_id="filter-comment-001",
                    user_name="评论用户",
                    content="这条笔记有评论",
                )
            )
            db.commit()
        finally:
            db.close()

        keyword_response = client.get(
            "/api/notes?platform=xhs&q=早餐",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert keyword_response.status_code == 200
        assert [item["note_id"] for item in keyword_response.json()["items"]] == ["filter-note-assets"]

        tag_filter_response = client.get(
            f"/api/notes?platform=xhs&tag_id={tag_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tag_filter_response.status_code == 200
        assert [item["note_id"] for item in tag_filter_response.json()["items"]] == ["filter-note-assets"]

        assets_response = client.get(
            "/api/notes?platform=xhs&has_assets=true",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert assets_response.status_code == 200
        assert [item["note_id"] for item in assets_response.json()["items"]] == ["filter-note-assets"]

        comments_response = client.get(
            "/api/notes?platform=xhs&has_comments=true",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert comments_response.status_code == 200
        assert [item["note_id"] for item in comments_response.json()["items"]] == ["filter-note-comments"]

        intruder_response = client.get(
            f"/api/notes?platform=xhs&tag_id={tag_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_library_detail_enforces_ownership(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-detail-owner")
    intruder_token = _register_and_get_access_token("library-detail-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "detail-note-001",
                        "title": "详情页笔记",
                        "content": "详情正文",
                        "author_name": "详情作者",
                        "raw": {"source": "detail"},
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        owner_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json()["note_id"] == "detail-note-001"
        assert owner_response.json()["raw_json"] == {"source": "detail"}

        intruder_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notes_library_delete_removes_owned_note_children_and_rejects_cross_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft, Note, NoteAsset, NoteComment, Tag, note_tags

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-delete-owner")
    intruder_token = _register_and_get_access_token("library-delete-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            note = Note(
                user_id=1,
                platform_account_id=owner_account_id,
                platform="xhs",
                note_id="delete-note-001",
                title="Delete me",
            )
            tag = Tag(user_id=1, name="待删除", color="#111111")
            db.add_all([note, tag])
            db.flush()
            db.add(NoteAsset(note_id=note.id, asset_type="image", url="https://example.test/delete.webp"))
            db.add(NoteComment(note_id=note.id, comment_id="delete-comment", content="删除评论"))
            db.add(AiDraft(user_id=1, platform="xhs", title="Draft", body="Body", source_note_id=note.id))
            db.execute(note_tags.insert().values(note_id=note.id, tag_id=tag.id))
            db.commit()
            note_id = note.id
        finally:
            db.close()

        intruder_response = client.delete(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        owner_response = client.delete(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json() == {"id": note_id, "status": "deleted"}

        detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 404

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(Note, note_id) is None
            assert db.query(NoteAsset).filter(NoteAsset.note_id == note_id).count() == 0
            assert db.query(NoteComment).filter(NoteComment.note_id == note_id).count() == 0
            assert db.execute(select(note_tags).where(note_tags.c.note_id == note_id)).first() is None
            assert db.query(AiDraft).filter(AiDraft.source_note_id == note_id).count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_drafts_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/drafts",
            json={"platform": "xhs", "title": "草稿标题", "body": "草稿正文"},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_drafts_api_creates_from_owned_note_and_lists_current_user_only(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-owner")
    intruder_token = _register_and_get_access_token("draft-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "draft-source-note",
                        "title": "源笔记标题",
                        "content": "源笔记正文",
                        "author_name": "源作者",
                        "raw": {"source": "draft"},
                    }
                ],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]

        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id, "intent": "rewrite"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["platform"] == "xhs"
        assert created["title"] == "源笔记标题"
        assert created["body"] == "源笔记正文"
        assert created["source_note_id"] == source_note_id

        owner_list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["id"] == created["id"]

        intruder_list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        db = next(app.dependency_overrides[get_db]())
        try:
            draft = db.query(AiDraft).one()
            assert draft.source_note_id == source_note_id
            assert draft.title == "源笔记标题"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_drafts_api_rejects_cross_user_source_note(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-source-owner")
    intruder_token = _register_and_get_access_token("draft-source-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "foreign-source", "title": " чужая", "content": "nope"}],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]

        response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id, "intent": "publish"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_drafts_update_persists_owned_changes_and_rejects_cross_user(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-update-owner")
    intruder_token = _register_and_get_access_token("draft-update-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "update-source", "title": "旧标题", "content": "旧正文"}],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]
        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id},
        )
        draft_id = create_response.json()["id"]

        update_response = client.patch(
            f"/api/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "新标题", "body": "新正文"},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "新标题"
        assert updated["body"] == "新正文"

        list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        listed = list_response.json()["items"][0]
        assert listed["id"] == draft_id
        assert listed["title"] == "新标题"
        assert listed["body"] == "新正文"

        intruder_response = client.patch(
            f"/api/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"title": "攻击标题", "body": "攻击正文"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_model_configs_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/model-configs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_model_configs_create_list_filter_and_encrypt_api_key(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import ModelConfig

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-owner")
    intruder_token = _register_and_get_access_token("model-intruder")
    try:
        create_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "OpenAI Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-secret-text",
                "is_default": True,
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "OpenAI Text"
        assert created["model_type"] == "text"
        assert created["model_name"] == "gpt-test"
        assert created["has_api_key"] is True
        assert "api_key" not in created
        assert "encrypted_api_key" not in created

        image_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Image Model",
                "model_type": "image",
                "provider": "openai-compatible",
                "model_name": "image-test",
                "base_url": "",
                "api_key": "",
                "is_default": False,
            },
        )
        assert image_response.status_code == 200

        owner_list_response = client.get(
            "/api/model-configs?model_type=text",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["id"] == created["id"]
        assert owner_payload["items"][0]["model_type"] == "text"

        intruder_list_response = client.get(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        db = next(app.dependency_overrides[get_db]())
        try:
            config = db.query(ModelConfig).filter(ModelConfig.name == "OpenAI Text").one()
            assert config.encrypted_api_key != "sk-secret-text"
            assert decrypt_text(config.encrypted_api_key) == "sk-secret-text"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_text_model_config_defaults_to_gpt_54_when_model_name_omitted(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-default-owner")
    try:
        response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-default",
                "is_default": True,
            },
        )

        assert response.status_code == 200
        assert response.json()["model_name"] == "gpt-5.4"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_model_configs_update_and_set_default_are_owner_scoped(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-update-owner")
    intruder_token = _register_and_get_access_token("model-update-intruder")
    try:
        first_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Text One",
                "model_type": "text",
                "provider": "provider-a",
                "model_name": "model-a",
                "base_url": "https://a.example.test",
                "api_key": "secret-a",
                "is_default": True,
            },
        )
        second_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Text Two",
                "model_type": "text",
                "provider": "provider-b",
                "model_name": "model-b",
                "base_url": "https://b.example.test",
                "api_key": "secret-b",
                "is_default": False,
            },
        )
        first_id = first_response.json()["id"]
        second_id = second_response.json()["id"]

        update_response = client.patch(
            f"/api/model-configs/{second_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Text Two Updated", "api_key": "secret-b2"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Text Two Updated"
        assert update_response.json()["has_api_key"] is True

        intruder_update_response = client.patch(
            f"/api/model-configs/{second_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "stolen"},
        )
        assert intruder_update_response.status_code == 404

        default_response = client.post(
            f"/api/model-configs/{second_id}/set-default",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert default_response.status_code == 200
        assert default_response.json()["is_default"] is True

        list_response = client.get(
            "/api/model-configs?model_type=text",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        listed = {item["id"]: item for item in list_response.json()["items"]}
        assert listed[first_id]["is_default"] is False
        assert listed[second_id]["is_default"] is True

        intruder_default_response = client.post(
            f"/api/model-configs/{second_id}/set-default",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_default_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_rewrite_note_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/rewrite-note", json={"draft_id": 1})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_rewrite_note_requires_owned_draft_and_default_text_model(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-rewrite-owner")
    intruder_token = _register_and_get_access_token("ai-rewrite-intruder")
    try:
        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Original title", "body": "Original body"},
        )
        draft_id = create_response.json()["id"]

        no_model_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"draft_id": draft_id},
        )
        assert no_model_response.status_code == 400
        assert "默认文本模型" in no_model_response.json()["detail"]

        intruder_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"draft_id": draft_id},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_rewrite_note_uses_default_text_model_and_updates_owned_draft(tmp_path):
    from backend.app.api.ai import get_text_ai_client

    class FakeTextAiClient:
        def __init__(self):
            self.calls = []

        def rewrite_note(self, *, model_config, api_key, title, body, instruction, template=None):
            self.calls.append(
                {
                    "model_name": model_config.model_name,
                    "api_key": api_key,
                    "title": title,
                    "body": body,
                    "instruction": instruction,
                }
            )
            return f"改写结果：{title} / {instruction}"

    fake_client = FakeTextAiClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-rewrite-success")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: fake_client

        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-rewrite-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-rewrite-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "爆款标题", "body": "原始正文"},
        )
        draft_id = draft_response.json()["id"]

        rewrite_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"draft_id": draft_id, "instruction": "更适合小红书种草"},
        )
        assert rewrite_response.status_code == 200
        rewritten = rewrite_response.json()
        assert rewritten["id"] == draft_id
        # 定位注入（层 1a）后，instruction 不再只有用户那句话；没有定位时会带
        # 「定位缺失，不要编造细节」的约束，改写结果会把它一起回显。
        assert rewritten["body"].startswith("改写结果：爆款标题 / ")
        assert "账号定位缺失" in rewritten["body"]
        call = fake_client.calls[0]
        assert call["model_name"] == "gpt-rewrite-test"
        assert call["api_key"] == "sk-rewrite-secret"
        assert call["title"] == "爆款标题"
        assert call["body"] == "原始正文"
        # 用户那句话必须保留在 instruction 里。不能断言 endswith：
        # draft 模块的 Skill 正文会拼在它后面（内置 Skill 随包发布，
        # 空库也会被播种），拼在末尾的是方法论而不是用户的要求。
        assert "更适合小红书种草" in call["instruction"]
        assert "账号定位缺失" in call["instruction"]

        list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.json()["items"][0]["body"].startswith("改写结果：爆款标题 / ")

        tasks_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tasks_response.status_code == 200
        task_payload = tasks_response.json()
        assert task_payload["total"] == 1
        task = task_payload["items"][0]
        assert task["task_type"] == "ai_rewrite"
        assert task["status"] == "completed"
        assert task["progress"] == 100
        assert task["payload"]["draft_id"] == draft_id
        assert task["payload"]["model_config_id"] == model_response.json()["id"]
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_rewrite_note_extracts_title_and_strips_labels(tmp_path):
    """The model echoes 标题/正文 labels; they must not leak into the draft body."""
    from backend.app.api.ai import get_text_ai_client

    class FakeLabelTextAiClient:
        def rewrite_note(self, *, model_config, api_key, title, body, instruction, template=None):
            return "标题：新的标题\n正文：\n新的正文第一段\n\n新的正文第二段"

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-rewrite-labels")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: FakeLabelTextAiClient()
        client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-rewrite-labels",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-label-secret",
                "is_default": True,
            },
        )
        draft_id = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "原标题", "body": "原正文"},
        ).json()["id"]

        rewritten = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"draft_id": draft_id, "instruction": "更口语"},
        ).json()

        assert rewritten["title"] == "新的标题"
        assert rewritten["body"] == "新的正文第一段\n\n新的正文第二段"
        assert "标题：" not in rewritten["body"]
        assert "正文：" not in rewritten["body"]
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_text_generation_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/generate-note", json={"topic": "低卡早餐"})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_text_generation_endpoints_use_default_model_and_create_tasks(tmp_path):
    from backend.app.api.ai import get_text_ai_client

    class FakeTextGenerationClient:
        def __init__(self):
            self.calls = []

        def rewrite_note(self, *, model_config, api_key, title, body, instruction, template=None):
            raise AssertionError("rewrite_note should not be called")

        def generate_note(self, *, model_config, api_key, topic, reference, instruction, template=None):
            self.calls.append(("generate_note", model_config.model_name, api_key, topic, reference, instruction))
            return {
                "title": f"{topic} 标题",
                "body": f"{topic} 正文 {reference} {instruction}".strip(),
                "tags": ["低卡", "早餐"],
            }

        def generate_titles(self, *, model_config, api_key, title, body, count, template=None, instruction=""):
            self.calls.append(("generate_titles", model_config.model_name, api_key, title, body, count))
            # 定位注入（层 1a）会带上 instruction；没有定位时也应带上「不要编造」的约束。
            assert instruction, "generate_titles 应当收到定位/风格约束"
            return ["标题 A", "标题 B"][:count]

        def generate_tags(self, *, model_config, api_key, title, body, count, instruction=""):
            self.calls.append(("generate_tags", model_config.model_name, api_key, title, body, count))
            assert instruction, "generate_tags 应当收到定位/风格约束"
            return ["低卡", "早餐", "通勤"][:count]

        def polish_text(self, *, model_config, api_key, text, instruction):
            self.calls.append(("polish_text", model_config.model_name, api_key, text, instruction))
            return f"润色：{text} / {instruction}"

    fake_client = FakeTextGenerationClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-generate-owner")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: fake_client
        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-generate-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-generate-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        generate_response = client.post(
            "/api/ai/generate-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "topic": "低卡早餐", "reference": "参考笔记", "instruction": "更具体"},
        )
        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["title"] == "低卡早餐 标题"
        # 定位注入（层 1a）后 body 不再只是「参考 + 指令」：没有填写定位时，
        # 提示词会显式带上「定位缺失，不要编造细节」的约束。
        assert generated["body"].startswith("低卡早餐 正文 参考笔记")
        assert "账号定位缺失" in generated["body"]
        # 同样不能断言 endswith：draft 模块的 Skill 正文拼在用户指令之后。
        assert "更具体" in generated["body"]
        # The tag rubric reads this field; dropping it zeroed the tags dimension.
        assert generated["tags"] == ["低卡", "早餐"]

        titles_response = client.post(
            "/api/ai/generate-title",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "旧标题", "body": "正文", "count": 2},
        )
        assert titles_response.status_code == 200
        assert titles_response.json()["items"] == ["标题 A", "标题 B"]

        tags_response = client.post(
            "/api/ai/generate-tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "早餐", "body": "低卡早餐正文", "count": 3},
        )
        assert tags_response.status_code == 200
        assert tags_response.json()["items"] == ["低卡", "早餐", "通勤"]

        polish_response = client.post(
            "/api/ai/polish-text",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"text": "原文", "instruction": "更自然"},
        )
        assert polish_response.status_code == 200
        assert polish_response.json()["text"] == "润色：原文 / 更自然"

        tasks_response = client.get("/api/tasks?platform=xhs", headers={"Authorization": f"Bearer {owner_token}"})
        assert tasks_response.status_code == 200
        task_types = [item["task_type"] for item in tasks_response.json()["items"]]
        assert task_types == ["ai_polish_text", "ai_generate_tags", "ai_generate_title", "ai_generate_note"]
        note_call = fake_client.calls[0]
        assert note_call[:5] == (
            "generate_note",
            "gpt-generate-test",
            "sk-generate-secret",
            "低卡早餐",
            "参考笔记",
        )
        # 定位块排在用户指令之前：没有定位时是「不要编造」的约束。
        # 用户那句话在中间；draft 模块的 Skill 正文拼在末尾（内置 Skill
        # 随包发布，空库也会被播种），所以不能断言 endswith。
        assert "更具体" in note_call[5]
        assert "账号定位缺失" in note_call[5]
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_topic_draft_records_template_and_topic_source(tmp_path):
    from backend.app.api.ai import get_text_ai_client
    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount, TopicIdea, ViralTemplate

    class FakeTopicDraftClient:
        def generate_note(self, *, model_config, api_key, topic, reference, instruction, template=None):
            assert template is not None
            return {"title": f"{topic} 标题", "body": "通勤穿搭正文"}

    fake_client = FakeTopicDraftClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("topic-draft-owner")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: fake_client
        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-topic-draft-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-topic-draft-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            account = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="pc",
                external_user_id="topic-draft-user",
                nickname="Topic Draft",
                status="active",
            )
            template = ViralTemplate(
                user_id=1,
                name="通勤穿搭结构",
                source_note_ids=[],
                payload={"structure": ["开头", "正文"]},
            )
            db.add_all([account, template])
            db.commit()
            db.refresh(account)
            db.refresh(template)
            topic = TopicIdea(
                user_id=1,
                platform_account_id=account.id,
                title="通勤穿搭怎么配",
                type="pain",
                type_label="痛点型",
                growth_task="建立信任",
                need="省时间",
                why="高频问题",
            )
            db.add(topic)
            db.commit()
            db.refresh(topic)
            topic_id = topic.id
            template_id = template.id
        finally:
            db.close()

        response = client.post(
            f"/api/xhs/topics/{topic_id}/draft",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"template_id": template_id},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["topic_id"] == topic_id
        assert payload["template_id"] == template_id

        drafts_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert drafts_response.status_code == 200
        drafts = drafts_response.json()["items"]
        assert drafts[0]["topic_id"] == topic_id
        assert drafts[0]["template_id"] == template_id
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_image_routes_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/images/generate-cover", json={"prompt": "低卡早餐封面"})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_ai_image_routes_use_default_model_store_assets_and_enforce_scope(tmp_path):
    from backend.app.api.ai import get_image_ai_client

    class FakeImageAiClient:
        def __init__(self):
            self.calls = []

        def generate_cover(self, *, model_config, api_key, prompt, size, style):
            self.calls.append(("generate_cover", model_config.model_name, api_key, prompt, size, style))
            return {"url": "https://cdn.example.test/cover.png", "raw": {"seed": 1}}

        def describe_image(self, *, model_config, api_key, image_url, instruction):
            self.calls.append(("describe_image", model_config.model_name, api_key, image_url, instruction))
            return "这是一张低卡早餐封面"

    fake_client = FakeImageAiClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-image-owner")
    intruder_token = _register_and_get_access_token("ai-image-intruder")
    try:
        app.dependency_overrides[get_image_ai_client] = lambda: fake_client
        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Image",
                "model_type": "image",
                "provider": "openai-compatible",
                "model_name": "image-generate-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-image-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        generate_response = client.post(
            "/api/ai/images/generate-cover",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"prompt": "低卡早餐封面", "size": "1024x1024", "style": "clean"},
        )
        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["file_path"] == "https://cdn.example.test/cover.png"
        assert generated["prompt"] == "低卡早餐封面"
        assert generated["model_name"] == "image-generate-test"

        list_response = client.get("/api/ai/images/assets", headers={"Authorization": f"Bearer {owner_token}"})
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == generated["id"]

        intruder_list_response = client.get("/api/ai/images/assets", headers={"Authorization": f"Bearer {intruder_token}"})
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        describe_response = client.post(
            "/api/ai/images/describe",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"image_url": generated["file_path"], "instruction": "描述卖点"},
        )
        assert describe_response.status_code == 200
        assert describe_response.json()["text"] == "这是一张低卡早餐封面"

        tasks_response = client.get("/api/tasks?platform=xhs", headers={"Authorization": f"Bearer {owner_token}"})
        assert tasks_response.status_code == 200
        task_types = [item["task_type"] for item in tasks_response.json()["items"]]
        assert task_types == ["ai_image_describe", "ai_image_generate_cover"]
        assert fake_client.calls == [
            ("generate_cover", "image-generate-test", "sk-image-secret", "低卡早餐封面", "1024x1024", "clean"),
            ("describe_image", "image-generate-test", "sk-image-secret", "https://cdn.example.test/cover.png", "描述卖点"),
        ]
    finally:
        app.dependency_overrides.pop(get_image_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_tasks_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/tasks?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_tasks_api_lists_only_current_user_tasks_and_filters_platform(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("task-owner")
    intruder_token = _register_and_get_access_token("task-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="ai_rewrite",
                        status="completed",
                        progress=100,
                        payload={"draft_id": 11},
                    ),
                    Task(
                        user_id=1,
                        platform="douyin",
                        task_type="crawl",
                        status="pending",
                        progress=0,
                        payload={"keyword": "demo"},
                    ),
                    Task(
                        user_id=2,
                        platform="xhs",
                        task_type="publish",
                        status="failed",
                        progress=100,
                        payload={"error": "nope"},
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        owner_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        owner_payload = owner_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["platform"] == "xhs"
        assert owner_payload["items"][0]["task_type"] == "ai_rewrite"
        assert owner_payload["items"][0]["payload"] == {"draft_id": 11}

        intruder_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total"] == 1
        assert intruder_response.json()["items"][0]["task_type"] == "publish"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_tasks_api_scope_system_excludes_business_tasks(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("task-scope-owner")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="ai_rewrite",
                        status="completed",
                        progress=100,
                        payload={},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="creator_publish",
                        status="failed",
                        progress=100,
                        payload={},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="auto_ops_run",
                        status="failed",
                        progress=100,
                        payload={},
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        all_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert all_response.status_code == 200
        assert all_response.json()["total"] == 3

        system_response = client.get(
            "/api/tasks?platform=xhs&scope=system",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert system_response.status_code == 200
        payload = system_response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["task_type"] == "ai_rewrite"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_note_comments_are_persisted_for_insights(tmp_path):
    """Fetching comments must write rows, otherwise insights stay empty."""
    from backend.app.api.platforms.xhs.pc import _persist_comments
    from backend.app.core.database import get_db
    from backend.app.models import Note, NoteComment

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(
        tmp_path, "comment-persist"
    )
    try:
        save = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "6ab27c270000000038000c4f",
                        "title": "评论持久化测试",
                        "content": "正文",
                        "author_name": "作者",
                        "raw": {"likes": 1},
                    }
                ],
            },
        )
        assert save.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            note = db.query(Note).filter(Note.note_id == "6ab27c270000000038000c4f").one()
            user_id = note.user_id
            from backend.app.models import User

            user = db.get(User, user_id)
            url = "https://www.xiaohongshu.com/explore/6ab27c270000000038000c4f"
            items = [
                {
                    "comment_id": "c-1",
                    "user_name": "甲",
                    "content": "要报名吗？",
                    "like_count": 3,
                },
                {
                    "comment_id": "c-2",
                    "user_name": "乙",
                    "content": "明天见",
                    "like_count": 0,
                },
            ]
            note_db_id, saved = _persist_comments(db, user, url, items)
            assert note_db_id == note.id
            assert saved == 2

            # Re-running updates rows instead of duplicating them.
            _, saved_again = _persist_comments(db, user, url, items)
            assert saved_again == 2
            rows = db.query(NoteComment).filter(NoteComment.note_id == note.id).all()
            assert len(rows) == 2
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_note_detail_business_error_is_not_silent():
    """XHS returns 200 + empty data for removed notes; that must be an error."""
    from backend.app.api.platforms.xhs.pc import _detail_business_error

    removed = {"code": 300031, "success": True, "msg": "当前笔记暂时无法浏览", "data": {}}
    assert "无法浏览" in _detail_business_error(removed)
    assert _detail_business_error({"data": {}})
    ok = {"code": 0, "data": {"items": [{"note_card": {"desc": "正文"}}]}}
    assert _detail_business_error(ok) == ""


def test_scheduler_status_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/tasks/scheduler/status")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_scheduler_status_reports_config_and_recent_owned_scheduler_tasks(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("scheduler-status-owner")
    _register_and_get_access_token("scheduler-status-other")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="monitoring_refresh",
                        status="completed",
                        progress=100,
                        payload={"scheduler": True, "target_id": 1},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="ai_rewrite",
                        status="completed",
                        progress=100,
                        payload={"draft_id": 10},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="monitoring_refresh",
                        status="pending",
                        progress=0,
                        payload={"target_id": 2},
                    ),
                    Task(
                        user_id=2,
                        platform="xhs",
                        task_type="creator_publish_scheduler",
                        status="completed",
                        progress=100,
                        payload={"publish_job_id": 99},
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/tasks/scheduler/status",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is False
        assert payload["running"] is False
        assert payload["interval_seconds"] == 60
        assert payload["jobs"] == []
        assert [task["task_type"] for task in payload["recent_tasks"]] == ["monitoring_refresh"]
        assert payload["recent_tasks"][0]["payload"] == {"scheduler": True, "target_id": 1}
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_tasks_detail_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("task-detail-owner")
    intruder_token = _register_and_get_access_token("task-detail-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            task = Task(
                user_id=1,
                platform="xhs",
                task_type="ai_rewrite",
                status="completed",
                progress=100,
                payload={"draft_id": 22},
            )
            db.add(task)
            db.commit()
            task_id = task.id
        finally:
            db.close()

        owner_response = client.get(
            f"/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json()["id"] == task_id
        assert owner_response.json()["payload"] == {"draft_id": 22}

        intruder_response = client.get(
            f"/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_task_execution_fields_and_retry_with_exhausted_status(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("task-fields-user")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            now = shanghai_now()
            parent = Task(
                user_id=1, platform="xhs", task_type="monitoring_crawl",
                status="completed", progress=100,
                started_at=now, finished_at=now,
            )
            child = Task(
                user_id=1, platform="xhs", task_type="note_crawl",
                status="failed", progress=0, error_type="network",
                retry_count=2, max_retries=3,
                started_at=now, finished_at=now,
            )
            db.add(parent)
            db.flush()
            child.parent_task_id = parent.id
            db.add(child)
            db.commit()
            parent_id, child_id = parent.id, child.id
        finally:
            db.close()

        detail = client.get(f"/api/tasks/{parent_id}", headers={"Authorization": f"Bearer {token}"})
        assert detail.status_code == 200
        body = detail.json()
        assert body["started_at"] is not None
        assert body["finished_at"] is not None
        assert body["duration_ms"] is not None
        assert body["duration_ms"] >= 0
        assert len(body["children"]) == 1
        assert body["children"][0]["id"] == child_id
        assert body["children"][0]["error_type"] == "network"

        child_detail = client.get(f"/api/tasks/{child_id}", headers={"Authorization": f"Bearer {token}"})
        assert child_detail.json()["parent_task_id"] == parent_id
        assert child_detail.json()["retry_count"] == 2
        assert child_detail.json()["max_retries"] == 3

        retry = client.post(f"/api/tasks/{child_id}/retry", headers={"Authorization": f"Bearer {token}"})
        assert retry.status_code == 200
        assert retry.json()["status"] == "pending"
        assert retry.json()["retry_count"] == 3
        assert retry.json()["error_type"] is None

        db2 = next(app.dependency_overrides[get_db]())
        try:
            t = db2.get(Task, child_id)
            t.status = "exhausted"
            t.error_type = "network"
            db2.commit()
        finally:
            db2.close()

        exhausted_retry = client.post(f"/api/tasks/{child_id}/retry", headers={"Authorization": f"Bearer {token}"})
        assert exhausted_retry.status_code == 200
        assert exhausted_retry.json()["status"] == "pending"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/drafts/1/send-to-publish", json={"platform_account_id": 1})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_notifications_crud_and_trigger_helpers(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Notification, Task
    from backend.app.services.notification_service import notify_task_failed, notify_task_exhausted

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("notif-user")
    other_token = _register_and_get_access_token("notif-other")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            task = Task(user_id=1, platform="xhs", task_type="ai_rewrite", status="failed", error_type="network")
            db.add(task)
            db.flush()
            n1 = notify_task_failed(db, task)
            task.status = "exhausted"
            n2 = notify_task_exhausted(db, task)
            other_n = Notification(user_id=2, title="other", level="info")
            db.add(other_n)
            db.commit()
        finally:
            db.close()

        unauth = client.get("/api/notifications")
        assert unauth.status_code == 401

        listing = client.get("/api/notifications", headers={"Authorization": f"Bearer {token}"})
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 2
        levels = {items[0]["level"], items[1]["level"]}
        assert levels == {"warning", "error"}

        unread_only = client.get("/api/notifications?unread=true", headers={"Authorization": f"Bearer {token}"})
        assert len(unread_only.json()["items"]) == 2

        mark = client.post(f"/api/notifications/{items[0]['id']}/read", headers={"Authorization": f"Bearer {token}"})
        assert mark.status_code == 200
        assert mark.json()["read"] is True

        unread_after = client.get("/api/notifications?unread=true", headers={"Authorization": f"Bearer {token}"})
        assert len(unread_after.json()["items"]) == 1

        mark_all = client.post("/api/notifications/read-all", headers={"Authorization": f"Bearer {token}"})
        assert mark_all.status_code == 200
        assert mark_all.json()["marked"] == 1

        other_listing = client.get("/api/notifications", headers={"Authorization": f"Bearer {other_token}"})
        assert len(other_listing.json()["items"]) == 1

        cross_mark = client.post(f"/api/notifications/{items[0]['id']}/read", headers={"Authorization": f"Bearer {other_token}"})
        assert cross_mark.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_draft_send_to_publish_creates_job_and_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-owner")
    intruder_token = _register_and_get_access_token("publish-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Ready title", "body": "Ready body"},
        )
        draft_id = draft_response.json()["id"]

        create_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id, "publish_mode": "immediate"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["platform"] == "xhs"
        assert created["platform_account_id"] == owner_account_id
        assert created["source_draft_id"] == draft_id
        assert created["title"] == "Ready title"
        assert created["body"] == "Ready body"
        assert created["publish_mode"] == "immediate"
        assert created["status"] == "pending"

        intruder_draft_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform_account_id": owner_account_id, "publish_mode": "immediate"},
        )
        assert intruder_draft_response.status_code == 404

        db = next(app.dependency_overrides[get_db]())
        try:
            publish_job = db.query(PublishJob).one()
            assert publish_job.source_draft_id == draft_id
            assert publish_job.platform_account_id == owner_account_id
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_jobs_list_requires_auth_and_filters_current_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-list-owner")
    intruder_token = _register_and_get_access_token("publish-list-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            intruder_account = PlatformAccount(
                user_id=2,
                platform="xhs",
                sub_type="pc",
                external_user_id="publish-list-intruder",
                nickname="发布测试账号",
                status="active",
            )
            db.add(intruder_account)
            db.flush()
            db.add(
                AccountCookieVersion(
                    platform_account_id=intruder_account.id,
                    encrypted_cookies=encrypt_text('{"a1":"intruder-a1"}'),
                )
            )
            db.commit()
            intruder_account_id = intruder_account.id
        finally:
            db.close()

        owner_draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner publish", "body": "Owner body"},
        )
        owner_draft_id = owner_draft_response.json()["id"]
        owner_create_response = client.post(
            f"/api/drafts/{owner_draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        assert owner_create_response.status_code == 200

        intruder_draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform": "xhs", "title": "Intruder publish", "body": "Intruder body"},
        )
        intruder_draft_id = intruder_draft_response.json()["id"]
        intruder_create_response = client.post(
            f"/api/drafts/{intruder_draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform_account_id": intruder_account_id},
        )
        assert intruder_create_response.status_code == 200

        anonymous_response = client.get("/api/publish/jobs?platform=xhs")
        assert anonymous_response.status_code == 401

        owner_list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["title"] == "Owner publish"

        intruder_list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        intruder_payload = intruder_list_response.json()
        assert intruder_payload["total"] == 1
        assert intruder_payload["items"][0]["title"] == "Intruder publish"
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_detail_and_update_enforce_ownership(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-detail-owner")
    intruder_token = _register_and_get_access_token("publish-detail-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Draft title", "body": "Draft body"},
        )
        draft_id = draft_response.json()["id"]
        create_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        job_id = create_response.json()["id"]

        owner_detail_response = client.get(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_detail_response.status_code == 200
        assert owner_detail_response.json()["title"] == "Draft title"

        intruder_detail_response = client.get(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_detail_response.status_code == 404

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "title": "Edited publish title",
                "body": "Edited publish body",
                "publish_mode": "scheduled",
                "scheduled_at": "2030-01-02T03:04:05",
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "Edited publish title"
        assert updated["body"] == "Edited publish body"
        assert updated["publish_mode"] == "scheduled"
        assert updated["scheduled_at"] == "2030-01-02T03:04:05"

        list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.json()["items"][0]["title"] == "Edited publish title"

        intruder_update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"title": "stolen"},
        )
        assert intruder_update_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_assets_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/publish/jobs/1/assets")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_assets_api_adds_lists_and_deletes_owned_assets(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-assets-owner")
    intruder_token = _register_and_get_access_token("publish-assets-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Asset title", "body": "Asset body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        job_id = job_response.json()["id"]

        create_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["publish_job_id"] == job_id
        assert created["asset_type"] == "image"
        assert created["file_path"] == "storage/media/cover.png"

        list_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == created["id"]

        intruder_list_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 404

        intruder_delete_response = client.delete(
            f"/api/publish/assets/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_delete_response.status_code == 404

        delete_response = client.delete(
            f"/api/publish/assets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        empty_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert empty_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_asset_upload_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/publish/assets/1/upload")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_asset_upload_uses_creator_cookie_and_updates_asset(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def upload_media(self, file_path, media_type):
            self.calls.append({"cookies": self.cookies, "file_path": file_path, "media_type": media_type})
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001"}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-upload-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Upload title", "body": "Upload body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]

        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert upload_response.status_code == 200
        uploaded = upload_response.json()
        assert uploaded["upload_status"] == "uploaded"
        assert uploaded["creator_media_id"] == "creator-media-001"
        assert uploaded["upload_error"] == ""
        assert FakeCreatorPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "file_path": "storage/media/cover.png",
                "media_type": "image",
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_asset_upload_rejects_cross_user_asset(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user upload must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-upload-cross-owner"
    )
    intruder_token = _register_and_get_access_token("publish-upload-cross-intruder")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner asset", "body": "Owner body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]

        response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/publish/jobs/1/publish")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_uses_creator_cookie_and_updates_status(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Note, Task

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "xhs-note-001", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 200
        published = publish_response.json()
        assert published["status"] == "published"
        assert published["external_note_id"] == "xhs-note-001"
        assert published["publish_error"] == ""
        assert published["published_at"] is not None
        assert FakeCreatorPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Publish title",
                    "desc": "Publish body",
                    "media_type": "image",
                    "image_file_infos": [
                        {
                            "creator_media_id": "creator-media-001",
                            "fileIds": "file-001",
                            "width": 1080,
                            "height": 1440,
                        }
                    ],
                    "type": 1,
                    "postTime": None,
                },
            }
        ]

        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert task.user_id == 1
            assert task.platform == "xhs"
            assert task.status == "completed"
            assert task.progress == 100
            assert task.payload["publish_job_id"] == job_id
            assert task.payload["external_note_id"] == "xhs-note-001"

            # published notes flow back into the content library
            note = db.query(Note).filter(Note.note_id == "xhs-note-001").one()
            assert note.title == "Publish title"
            assert note.content == "Publish body"
            assert note.platform_account_id == creator_account_id
            assert note.raw_json["origin"] == "publish"
            assert note.raw_json["publish_job_id"] == job_id
            assert note.raw_json["note_url"] == "https://www.xiaohongshu.com/explore/xhs-note-001"
            assert task.payload["library_note_id"] == note.id
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_passes_optional_creator_parameters(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorOptionalPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "optional-job-note", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-optional", "fileIds": "file-optional", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-optional-owner"
    )
    FakeCreatorOptionalPublishAdapter.calls = []
    # 正文必须非空：送进队列时会跑内容预检。
    optional_body = "正文内容，用来通过发布前检查。" * 4
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorOptionalPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            # 正文不能为空：送进队列时就会跑内容预检（以前只有定时才查，
            # 空正文能进队列，点确认时才 400 且没有出路）。
            json={
                "platform": "xhs",
                "title": "Optional title",
                "body": optional_body,
            },
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "platform_account_id": creator_account_id,
                "topics": ["早餐"],
                "location": "上海",
                "is_private": False,
            },
        )
        job_id = job_response.json()["id"]
        assert job_response.json()["publish_options"] == {
            "topics": ["早餐"],
            "location": "上海",
            "is_private": False,
            "privacy_type": 0,
        }

        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"topics": ["早餐", "通勤"], "is_private": True, "location": ""},
        )
        assert update_response.status_code == 200
        assert update_response.json()["publish_options"] == {
            "topics": ["早餐", "通勤"],
            "is_private": True,
            "privacy_type": 1,
        }

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 200
        assert FakeCreatorOptionalPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Optional title",
                    "desc": optional_body,
                    "media_type": "image",
                    "image_file_infos": [
                        {
                            "creator_media_id": "creator-media-optional",
                            "fileIds": "file-optional",
                            "width": 1080,
                            "height": 1440,
                        }
                    ],
                    "type": 1,
                    "postTime": None,
                    "topics": ["早餐", "通勤"],
                },
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_records_failed_task(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeFailingCreatorPublishAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            raise RuntimeError("creator publish denied")

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-failed-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeFailingCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 502
        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert task.status == "failed"
            assert task.progress == 100
            assert task.payload["publish_job_id"] == job_id
            assert task.payload["error"] == "creator publish denied"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_rejects_empty_content_before_adapter(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("invalid publish content must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-preflight-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Valid title", "body": "Valid body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "   ", "body": ""},
        )
        assert update_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 400
        assert publish_response.json()["detail"] == "请填写发布标题"
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_rejects_past_scheduled_time_before_adapter(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import PublishAsset, Task

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("past scheduled publish must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-past-schedule-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Scheduled title", "body": "Scheduled body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "publish_mode": "scheduled",
                "scheduled_at": (shanghai_now() - timedelta(minutes=5)).isoformat(),
            },
        )
        assert update_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                PublishAsset(
                    publish_job_id=job_id,
                    asset_type="image",
                    file_path="storage/media/cover.png",
                    upload_status="uploaded",
                    creator_media_id="creator-media-001",
                    creator_upload_info='{"fileIds":"file-001","width":1080,"height":1440}',
                )
            )
            db.commit()
        finally:
            db.close()

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 400
        assert publish_response.json()["detail"] == "定时发布时间必须晚于当前时间"
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_rejects_already_completed_job(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "xhs-note-001", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-completed-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": "storage/media/cover.png"},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        first_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert first_response.status_code == 200

        second_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert second_response.status_code == 400
        assert second_response.json()["detail"] == "该发布任务已经完成"
        assert len(FakeCreatorPublishAdapter.calls) == 1
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 1
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_publish_rejects_cross_user_job(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user publish must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-cross-owner"
    )
    intruder_token = _register_and_get_access_token("publish-action-cross-intruder")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner publish", "body": "Owner body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_image_utility_routes_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        compose_response = client.post(
            "/api/files/images/compose",
            json={"title": "低卡早餐", "body": "三分钟做完", "width": 720, "height": 960},
        )
        resize_response = client.post(
            "/api/files/images/resize",
            json={"source_file_name": "xhs-image-u1-missing.png", "width": 320, "height": 320},
        )
        download_response = client.get("/api/files/media/xhs-image-u1-missing.png")

        assert compose_response.status_code == 401
        assert resize_response.status_code == 401
        assert download_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_image_utilities_compose_resize_download_and_enforce_scope(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("image-utility-owner")
        intruder_token = _register_and_get_access_token("image-utility-intruder")

        compose_response = client.post(
            "/api/files/images/compose",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "title": "低卡早餐合集",
                "body": "适合通勤前快速准备的小红书封面",
                "width": 720,
                "height": 960,
                "accent_color": "#111111",
            },
        )

        assert compose_response.status_code == 200
        composed = compose_response.json()
        assert composed["file_name"].startswith("xhs-image-u1-")
        assert composed["file_name"].endswith(".png")
        assert composed["download_url"] == f"/api/files/media/{composed['file_name']}"
        assert composed["width"] == 720
        assert composed["height"] == 960
        assert composed["media_type"] == "image/png"

        download_response = client.get(
            composed["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.headers["content-type"].startswith("image/png")
        assert download_response.content.startswith(b"\x89PNG")

        resize_response = client.post(
            "/api/files/images/resize",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "source_file_name": composed["file_name"],
                "width": 320,
                "height": 320,
                "mode": "cover",
                "format": "jpeg",
                "quality": 82,
            },
        )

        assert resize_response.status_code == 200
        resized = resize_response.json()
        assert resized["file_name"].startswith("xhs-image-u1-")
        assert resized["file_name"].endswith(".jpg")
        assert resized["file_name"] != composed["file_name"]
        assert resized["width"] == 320
        assert resized["height"] == 320
        assert resized["media_type"] == "image/jpeg"

        resized_download_response = client.get(
            resized["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert resized_download_response.status_code == 200
        assert resized_download_response.content.startswith(b"\xff\xd8")

        forbidden_download = client.get(
            composed["download_url"],
        )
        assert forbidden_download.status_code == 200

        forbidden_resize = client.post(
            "/api/files/images/resize",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"source_file_name": composed["file_name"], "width": 320, "height": 320},
        )
        assert forbidden_resize.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_retry_and_cancel_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        retry_response = client.post("/api/publish/jobs/1/retry")
        cancel_response = client.post("/api/publish/jobs/1/cancel")

        assert retry_response.status_code == 401
        assert cancel_response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_retry_resets_failed_job_and_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob, Task

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-retry-owner"
    )
    intruder_token = _register_and_get_access_token("publish-retry-intruder")
    db = next(app.dependency_overrides[get_db]())
    try:
        failed_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Failed title",
            body="Failed body",
            status="failed",
            external_note_id="old-note",
            publish_error="creator denied",
            published_at=datetime.utcnow(),
        )
        db.add(failed_job)
        db.commit()
        db.refresh(failed_job)
        job_id = failed_job.id
    finally:
        db.close()

    try:
        forbidden_response = client.post(
            f"/api/publish/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert forbidden_response.status_code == 404

        retry_response = client.post(
            f"/api/publish/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert retry_response.status_code == 200
        retried = retry_response.json()
        assert retried["status"] == "pending"
        assert retried["publish_error"] == ""
        assert retried["external_note_id"] == ""
        assert retried["published_at"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish_retry").one()
            assert task.user_id == 1
            assert task.status == "pending"
            assert task.progress == 0
            assert task.payload["publish_job_id"] == job_id
            assert db.get(PublishJob, job_id).status == "pending"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_publish_job_cancel_transitions_pending_or_scheduled_and_rejects_locked(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob, Task

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-cancel-owner"
    )
    db = next(app.dependency_overrides[get_db]())
    try:
        pending_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Pending title",
            body="Pending body",
            status="pending",
        )
        scheduled_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Scheduled title",
            body="Scheduled body",
            publish_mode="scheduled",
            status="scheduled",
            scheduled_at=datetime.utcnow(),
        )
        published_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Published title",
            body="Published body",
            status="published",
        )
        db.add_all([pending_job, scheduled_job, published_job])
        db.commit()
        db.refresh(pending_job)
        db.refresh(scheduled_job)
        db.refresh(published_job)
        pending_id = pending_job.id
        scheduled_id = scheduled_job.id
        published_id = published_job.id
    finally:
        db.close()

    try:
        pending_response = client.post(
            f"/api/publish/jobs/{pending_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        scheduled_response = client.post(
            f"/api/publish/jobs/{scheduled_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        locked_response = client.post(
            f"/api/publish/jobs/{published_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert pending_response.status_code == 200
        assert pending_response.json()["status"] == "cancelled"
        assert scheduled_response.status_code == 200
        assert scheduled_response.json()["status"] == "cancelled"
        assert locked_response.status_code == 400
        assert locked_response.json()["detail"] == "该发布任务当前状态不能取消"

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(PublishJob, pending_id).status == "cancelled"
            assert db.get(PublishJob, scheduled_id).status == "cancelled"
            assert db.get(PublishJob, published_id).status == "published"
            assert db.query(Task).filter(Task.task_type == "creator_publish_cancel").count() == 2
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_run_due_tasks_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/tasks/run-due?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_run_due_tasks_executes_current_user_due_scheduled_publish_jobs(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.core.time import shanghai_now
    from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task

    class FakeDuePublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "due-note-001"}

    db_dependency, owner_token, owner_account_id = _create_creator_account_with_cookie(
        tmp_path, "due-publish-owner"
    )
    intruder_token = _register_and_get_access_token("due-publish-intruder")
    db = next(app.dependency_overrides[get_db]())
    try:
        now = shanghai_now()
        intruder_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="creator",
            external_user_id="intruder-creator",
            nickname="Intruder creator",
            status="active",
        )
        db.add(intruder_account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=intruder_account.id,
                encrypted_cookies=encrypt_text('{"web_session":"intruder-session","a1":"intruder-a1"}'),
            )
        )

        due_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="Due title",
            body="Due body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now - timedelta(minutes=5),
        )
        future_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="Future title",
            body="Future body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now + timedelta(hours=2),
        )
        intruder_due_job = PublishJob(
            user_id=2,
            platform_account_id=intruder_account.id,
            platform="xhs",
            title="Intruder due title",
            body="Intruder due body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now - timedelta(minutes=5),
        )
        db.add_all([due_job, future_job, intruder_due_job])
        db.flush()
        db.add_all(
            [
                PublishAsset(
                    publish_job_id=due_job.id,
                    asset_type="image",
                    file_path="storage/media/due.png",
                    upload_status="uploaded",
                    creator_media_id="media-due",
                    creator_upload_info='{"fileIds":"file-due","width":1080,"height":1440}',
                ),
                PublishAsset(
                    publish_job_id=future_job.id,
                    asset_type="image",
                    file_path="storage/media/future.png",
                    upload_status="uploaded",
                    creator_media_id="media-future",
                    creator_upload_info='{"fileIds":"file-future","width":1080,"height":1440}',
                ),
                PublishAsset(
                    publish_job_id=intruder_due_job.id,
                    asset_type="image",
                    file_path="storage/media/intruder.png",
                    upload_status="uploaded",
                    creator_media_id="media-intruder",
                    creator_upload_info='{"fileIds":"file-intruder","width":1080,"height":1440}',
                ),
            ]
        )
        db.commit()
        due_job_id = due_job.id
        future_job_id = future_job.id
        intruder_job_id = intruder_due_job.id
    finally:
        db.close()

    FakeDuePublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeDuePublishAdapter
    try:
        intruder_response = client.post(
            "/api/tasks/run-due?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["executed_count"] == 1

        owner_response = client.post(
            "/api/tasks/run-due?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert owner_response.status_code == 200
        payload = owner_response.json()
        assert payload["executed_count"] == 1
        assert payload["failed_count"] == 0
        assert payload["items"][0]["id"] == due_job_id
        assert payload["items"][0]["status"] == "published"
        assert len(FakeDuePublishAdapter.calls) == 2
        owner_call = FakeDuePublishAdapter.calls[-1]
        assert owner_call["cookies"] == "web_session=creator-session; a1=creator-a1"
        assert owner_call["note_info"]["title"] == "Due title"
        assert owner_call["note_info"]["postTime"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(PublishJob, due_job_id).status == "published"
            assert db.get(PublishJob, due_job_id).external_note_id == "due-note-001"
            assert db.get(PublishJob, future_job_id).status == "pending"
            assert db.get(PublishJob, intruder_job_id).status == "published"
            tasks = db.query(Task).filter(Task.task_type == "creator_publish_scheduler").all()
            assert len(tasks) == 2
            assert {task.user_id for task in tasks} == {1, 2}
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_run_due_publish_jobs_for_all_users_executes_each_due_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task
    from backend.app.services.scheduler_service import run_due_publish_jobs_for_all_users

    class FakeAllUsersDuePublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": f"note-{len(self.calls)}"}

    db_dependency, owner_token, owner_account_id = _create_creator_account_with_cookie(
        tmp_path, "all-users-due-owner"
    )
    _register_and_get_access_token("all-users-due-second")
    db = next(app.dependency_overrides[get_db]())
    try:
        second_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="creator",
            external_user_id="second-creator",
            nickname="Second creator",
            status="active",
        )
        db.add(second_account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=second_account.id,
                encrypted_cookies=encrypt_text('{"web_session":"second-session","a1":"second-a1"}'),
            )
        )
        first_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="First due",
            body="First body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=datetime.utcnow() - timedelta(minutes=10),
        )
        second_job = PublishJob(
            user_id=2,
            platform_account_id=second_account.id,
            platform="xhs",
            title="Second due",
            body="Second body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=datetime.utcnow() - timedelta(minutes=8),
        )
        db.add_all([first_job, second_job])
        db.flush()
        db.add_all(
            [
                PublishAsset(
                    publish_job_id=first_job.id,
                    asset_type="image",
                    file_path="storage/media/first.png",
                    upload_status="uploaded",
                    creator_media_id="first-media",
                    creator_upload_info='{"fileIds":"first-file"}',
                ),
                PublishAsset(
                    publish_job_id=second_job.id,
                    asset_type="image",
                    file_path="storage/media/second.png",
                    upload_status="uploaded",
                    creator_media_id="second-media",
                    creator_upload_info='{"fileIds":"second-file"}',
                ),
            ]
        )
        db.commit()
        first_job_id = first_job.id
        second_job_id = second_job.id

        # 这条测试考的是「能否枚举到每个有待发任务的用户」，不是「要不要
        # 自动发」。无人值守路径现在默认要求 `auto_publish_enabled`（见
        # `test_scheduler_respects_auto_publish_switch.py`），所以这里把两个
        # 用户的开关都打开，让测试继续只考枚举。
        from backend.app.models import RiskControlSetting

        for uid in (1, 2):
            db.add(
                RiskControlSetting(
                    user_id=uid,
                    auto_publish_enabled=True,
                    auto_create_publish_job_enabled=True,
                )
            )
        db.commit()
    finally:
        db.close()

    FakeAllUsersDuePublishAdapter.calls = []
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            result = run_due_publish_jobs_for_all_users(
                db=db,
                now=datetime.utcnow(),
                platform="xhs",
                adapter_factory=FakeAllUsersDuePublishAdapter,
            )

            assert result["executed_count"] == 2
            assert result["failed_count"] == 0
            assert {item["id"] for item in result["items"]} == {first_job_id, second_job_id}
            assert db.get(PublishJob, first_job_id).status == "published"
            assert db.get(PublishJob, second_job_id).status == "published"
            assert db.query(Task).filter(Task.task_type == "creator_publish_scheduler").count() == 2
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_due_publish_scheduler_registers_interval_job():
    from backend.app.services.scheduler_service import build_due_publish_scheduler, shutdown_due_publish_scheduler

    scheduler = build_due_publish_scheduler(interval_seconds=17, job_func=lambda: None)

    try:
        jobs = scheduler.get_jobs()
        assert {job.id for job in jobs} == {"due_publish_runner", "monitoring_refresh_runner", "auto_tasks_runner", "cookie_health_checker", "metric_refresh_runner"}
        job_intervals = {job.id: job.trigger.interval.total_seconds() for job in jobs}
        assert job_intervals["due_publish_runner"] == 17
        assert job_intervals["monitoring_refresh_runner"] == 17
        assert job_intervals["auto_tasks_runner"] == 60
        assert job_intervals["cookie_health_checker"] == 7200
        assert job_intervals["metric_refresh_runner"] == 3600
    finally:
        shutdown_due_publish_scheduler(scheduler)


def test_run_monitoring_refresh_for_all_users_refreshes_active_targets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import MonitoringSnapshot, MonitoringTarget, Note, PlatformAccount, Task
    from backend.app.services.scheduler_service import run_monitoring_refresh_for_all_users

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(
        tmp_path, "scheduled-monitor-owner"
    )
    _register_and_get_access_token("scheduled-monitor-second")
    db = next(app.dependency_overrides[get_db]())
    try:
        second_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="pc",
            external_user_id="second-pc",
            nickname="Second PC",
            status="active",
        )
        db.add(second_account)
        db.flush()
        db.add_all(
            [
                Note(
                    user_id=1,
                    platform_account_id=owner_account_id,
                    platform="xhs",
                    note_id="monitor-auto-owner",
                    title="低卡早餐自动监控",
                    content="适合通勤的低卡早餐",
                    author_name="owner-author",
                    raw_json={"likes": 20, "collects": 5, "comments": 2, "shares": 1},
                ),
                Note(
                    user_id=2,
                    platform_account_id=second_account.id,
                    platform="xhs",
                    note_id="monitor-auto-second",
                    title="低卡早餐第二用户",
                    content="第二用户的低卡早餐",
                    author_name="second-author",
                    raw_json={"likes": 100},
                ),
            ]
        )
        active_owner = MonitoringTarget(
            user_id=1,
            platform="xhs",
            target_type="keyword",
            name="Owner breakfast",
            value="低卡早餐",
            status="active",
        )
        paused_owner = MonitoringTarget(
            user_id=1,
            platform="xhs",
            target_type="keyword",
            name="Paused breakfast",
            value="低卡早餐",
            status="paused",
        )
        active_second = MonitoringTarget(
            user_id=2,
            platform="xhs",
            target_type="keyword",
            name="Second breakfast",
            value="低卡早餐",
            status="active",
        )
        db.add_all([active_owner, paused_owner, active_second])
        db.commit()
        active_owner_id = active_owner.id
        paused_owner_id = paused_owner.id
        active_second_id = active_second.id
    finally:
        db.close()

    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            result = run_monitoring_refresh_for_all_users(db=db, now=datetime.utcnow(), platform="xhs")

            assert result["refreshed_count"] == 2
            assert result["items"][0]["target_id"] in {active_owner_id, active_second_id}
            assert db.get(MonitoringTarget, active_owner_id).last_refreshed_at is not None
            assert db.get(MonitoringTarget, active_second_id).last_refreshed_at is not None
            assert db.get(MonitoringTarget, paused_owner_id).last_refreshed_at is None
            owner_snapshot = db.scalars(
                select(MonitoringSnapshot).where(MonitoringSnapshot.target_id == active_owner_id)
            ).one()
            second_snapshot = db.scalars(
                select(MonitoringSnapshot).where(MonitoringSnapshot.target_id == active_second_id)
            ).one()
            assert owner_snapshot.payload["matched_count"] == 1
            assert owner_snapshot.payload["total_engagement"] == 28
            assert second_snapshot.payload["matched_count"] == 1
            assert second_snapshot.payload["total_engagement"] == 100
            tasks = db.query(Task).filter(Task.task_type == "monitoring_refresh").all()
            assert len(tasks) == 2
            assert {task.user_id for task in tasks} == {1, 2}
            assert all(task.status == "completed" for task in tasks)
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_note_metrics_service_parses_counts_and_computes_rates():
    from backend.app.services.note_metrics_service import (
        compute_note_metrics,
        extract_note_metrics,
        filter_and_sort_items,
        parse_count,
    )

    assert parse_count(None) == 0
    assert parse_count(1234) == 1234
    assert parse_count("1,234") == 1234
    assert parse_count("1.2万") == 12000
    assert parse_count("3.5w") == 35000
    assert parse_count("12k") == 12000

    rates = compute_note_metrics(3000, 500, 100, 20, 2000)
    assert rates == {"like_fan_ratio": 1.5, "engagement_rate": 1.81}
    assert compute_note_metrics(10, 5, 1, 1, 0) == {"like_fan_ratio": 0.0, "engagement_rate": 0.0}

    raw = {
        "data": {
            "items": [
                {
                    "note_card": {
                        "user": {"user_id": "author-1", "nickname": "作者"},
                        "interact_info": {
                            "liked_count": "1.2万",
                            "collected_count": "300",
                            "comment_count": 20,
                            "share_count": "5",
                        },
                    }
                }
            ]
        }
    }
    metrics = extract_note_metrics(raw)
    assert metrics["author_id"] == "author-1"
    assert metrics["likes"] == 12000
    assert metrics["collects"] == 300
    assert metrics["comments"] == 20
    assert metrics["shares"] == 5

    items = [
        {"note_id": "a", "likes": 5000, "author_fans": 3000, "like_fan_ratio": 1.67, "engagement_rate": 1.8},
        {"note_id": "b", "likes": 3000, "author_fans": 50000, "like_fan_ratio": 0.06, "engagement_rate": 0.1},
        {"note_id": "c", "likes": 800, "author_fans": 2000, "like_fan_ratio": 0.4, "engagement_rate": 0.5},
        {"note_id": "d", "likes": 2000, "author_fans": 0, "like_fan_ratio": 0.0, "engagement_rate": 0.0},
    ]
    filtered = filter_and_sort_items(
        items, max_fans=10000, min_likes=1000, min_like_fan_ratio=0.5, sort_by="like_fan_ratio"
    )
    assert [item["note_id"] for item in filtered] == ["a"]


def test_enrich_items_with_authors_deduplicates_and_caps_profiles():
    from backend.app.services.note_metrics_service import enrich_items_with_authors

    class FakeAuthorAdapter:
        def __init__(self):
            self.calls = []

        def get_user_info(self, user_id):
            self.calls.append(user_id)
            if user_id == "missing":
                return False, "not found", {}
            return True, "ok", {"data": {"basic_info": {"user_id": user_id, "nickname": "昵称", "fans": 2000}}}

    items = [
        {"note_id": "a", "likes": 3000, "author_id": "u1", "author_name": "", "raw": {}},
        {"note_id": "b", "likes": 2000, "author_id": "u1", "author_name": "", "raw": {}},
        {"note_id": "c", "likes": 1500, "author_id": "u2", "author_name": "", "raw": {}},
        {"note_id": "d", "likes": 1500, "author_id": "u3", "author_name": "", "raw": {}},
        {"note_id": "e", "likes": 100, "author_id": "u4", "author_name": "", "raw": {}},
    ]
    adapter = FakeAuthorAdapter()
    stats = enrich_items_with_authors(
        adapter, items, min_likes_for_profile=1000, max_profiles=2, sleep_seconds=0
    )

    assert adapter.calls == ["u1", "u2"]
    assert stats["candidate_authors"] == 3
    assert stats["profiles_requested"] == 2
    assert stats["profiles_fetched"] == 2
    assert items[0]["author_fans"] == 2000
    assert items[0]["like_fan_ratio"] == 1.5
    assert items[1]["author_fans"] == 2000
    assert items[1]["like_fan_ratio"] == 1.0
    assert items[3]["author_fans"] == 0
    assert items[4]["author_fans"] == 0


def test_xhs_pc_note_search_enriches_author_fans_and_filters_low_fan_viral(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeEnrichAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def search_note(self, keyword, page=1, **kwargs):
            return (
                True,
                "ok",
                {
                    "data": {
                        "items": [
                            {
                                "model_type": "note",
                                "note_card": {
                                    "note_id": "viral",
                                    "user": {"user_id": "u1", "nickname": "小号"},
                                    "interact_info": {"liked_count": "5000", "collected_count": "100"},
                                },
                            },
                            {
                                "model_type": "note",
                                "note_card": {
                                    "note_id": "same-author",
                                    "user": {"user_id": "u1", "nickname": "小号"},
                                    "interact_info": {"liked_count": "1200"},
                                },
                            },
                            {
                                "model_type": "note",
                                "note_card": {
                                    "note_id": "big-account",
                                    "user": {"user_id": "u2", "nickname": "大号"},
                                    "interact_info": {"liked_count": "9000"},
                                },
                            },
                        ]
                    }
                },
            )

        def get_user_info(self, user_id):
            self.__class__.calls.append(user_id)
            fans = {"u1": 3000, "u2": 500000}[user_id]
            return True, "ok", {"data": {"basic_info": {"user_id": user_id, "nickname": user_id, "fans": fans}}}

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "enrich-owner")
    FakeEnrichAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeEnrichAdapter
    try:
        response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "keyword": "低卡早餐",
                "enrich_authors": True,
                "max_fans": 10000,
                "min_likes": 1000,
                "min_like_fan_ratio": 0.5,
                "sort_by": "like_fan_ratio",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert [item["note_id"] for item in payload["items"]] == ["viral"]
        assert payload["raw_total"] == 3
        assert payload["filtered_out"] == 2
        assert payload["filtered_total"] == 1
        assert payload["items"][0]["author_fans"] == 3000
        assert payload["items"][0]["like_fan_ratio"] == 1.6667
        assert payload["enrichment"]["profiles_fetched"] == 2
        assert sorted(FakeEnrichAdapter.calls) == ["u1", "u2"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)


def test_notes_low_fan_viral_metrics_are_saved_and_filterable(tmp_path):
    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "low-fan-owner")
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = client.post(
            "/api/notes/batch-save",
            headers=headers,
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "viral",
                        "title": "低粉爆款",
                        "author_id": "author-viral",
                        "author_fans": 3000,
                        "likes": 6000,
                        "collects": 1000,
                        "comments": 200,
                        "shares": 50,
                    },
                    {
                        "note_id": "big-account",
                        "title": "大号笔记",
                        "author_id": "author-big",
                        "author_fans": 500000,
                        "likes": 20000,
                        "collects": 3000,
                        "comments": 500,
                        "shares": 100,
                    },
                    {
                        "note_id": "weak",
                        "title": "低互动",
                        "author_id": "author-weak",
                        "author_fans": 2000,
                        "likes": 100,
                    },
                ],
            },
        )
        assert response.status_code == 200
        saved = {item["note_id"]: item for item in response.json()["items"]}
        assert saved["viral"]["author_fans"] == 3000
        assert saved["viral"]["likes"] == 6000
        assert saved["viral"]["like_fan_ratio"] == 2.0
        assert saved["viral"]["engagement_rate"] == 2.4167
        assert saved["viral"]["metrics_fetched_at"]

        listing = client.get(
            "/api/notes",
            params={
                "platform": "xhs",
                "max_fans": 10000,
                "min_likes": 1000,
                "min_like_fan_ratio": 0.5,
                "sort_by": "like_fan_ratio",
            },
            headers=headers,
        )
        assert listing.status_code == 200
        assert [item["note_id"] for item in listing.json()["items"]] == ["viral"]

        by_likes = client.get(
            "/api/notes",
            params={"platform": "xhs", "sort_by": "likes"},
            headers=headers,
        )
        assert [item["note_id"] for item in by_likes.json()["items"]] == ["big-account", "viral", "weak"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_card_png_upload_flows_into_publish_job_assets(tmp_path, monkeypatch):
    """Card studio uploads a PNG to a draft; sending the draft copies it to the job."""
    import base64
    from types import SimpleNamespace

    from backend.app.api import files as files_api

    settings = SimpleNamespace(storage_dir=str(tmp_path / "storage"))
    monkeypatch.setattr(files_api, "get_settings", lambda: settings)

    # 1x1 transparent PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("card-chain")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        draft = client.post(
            "/api/drafts",
            headers=headers,
            json={"platform": "xhs", "title": "卡片链路", "body": "正文", "intent": "publish"},
        ).json()

        from backend.app.core.database import get_db as _get_db
        from backend.app.core.security import encrypt_text as _enc
        from backend.app.models import AccountCookieVersion as _ACV
        from backend.app.models import PlatformAccount as _PA

        _db = next(app.dependency_overrides[_get_db]())
        try:
            account = _PA(
                user_id=1, platform="xhs", sub_type="pc",
                nickname="card", status="active",
            )
            _db.add(account)
            _db.flush()
            _db.add(
                _ACV(
                    platform_account_id=account.id,
                    encrypted_cookies=_enc("a1=x; web_session=y"),
                )
            )
            _db.commit()
            account_id = account.id
        finally:
            _db.close()

        uploaded = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("xhs-card-01.png", png, "image/png")},
        )
        assert uploaded.status_code == 200
        upload_data = uploaded.json()
        assert upload_data["asset_type"] == "image"

        attached = client.post(
            f"/api/drafts/{draft['id']}/assets",
            headers=headers,
            json={
                "asset_type": "image",
                "url": upload_data["download_url"],
                "local_path": upload_data["file_name"],
            },
        )
        assert attached.status_code == 200

        # 账号必填：没有账号的任务进队列后点确认才报错，用户会以为已经排好。
        job = client.post(
            f"/api/drafts/{draft['id']}/send-to-publish",
            headers=headers,
            json={"publish_mode": "immediate", "platform_account_id": account_id},
        )
        assert job.status_code == 200, job.text

        assets = client.get(f"/api/publish/jobs/{job.json()['id']}/assets", headers=headers)
        assert assets.status_code == 200
        items = assets.json()["items"]
        assert len(items) == 1
        assert items[0]["asset_type"] == "image"
        assert items[0]["file_path"] == upload_data["download_url"]

        # the copied path must resolve to a real file through the media route
        media = client.get(items[0]["file_path"], headers=headers)
        assert media.status_code == 200
        assert media.content == png
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_register_media_file_as_card_asset_is_owner_scoped(tmp_path, monkeypatch):
    """Card exports register into the shared asset library with an ownership check."""
    import base64
    from types import SimpleNamespace

    from backend.app.api import ai as ai_api

    settings = SimpleNamespace(storage_dir=str(tmp_path / "storage"))
    media_dir = (tmp_path / "storage" / "media")
    media_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("asset-owner")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        me = client.get("/api/auth/me", headers=headers).json()
        user_id = me["id"]
        file_name = f"xhs-upload-u{user_id}-card.png"
        (media_dir / file_name).write_bytes(png)

        registered = client.post(
            "/api/ai/images/assets/register",
            headers=headers,
            json={
                "file_name": file_name,
                "prompt": "卡片导出",
                "kind": "card",
                "params": {"page": 1, "total": 2},
            },
        )
        assert registered.status_code == 200
        asset = registered.json()
        assert asset["file_path"] == f"/api/files/media/{file_name}"
        assert asset["params"]["kind"] == "card"

        listing = client.get("/api/ai/images/assets", headers=headers)
        assert listing.status_code == 200
        assert any(item["id"] == asset["id"] for item in listing.json()["items"])

        forbidden = client.post(
            "/api/ai/images/assets/register",
            headers=headers,
            json={"file_name": "xhs-upload-u999-not-mine.png", "kind": "card"},
        )
        assert forbidden.status_code == 403
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_account_persona_and_draft_account_binding(tmp_path):
    """画像已下线；账号与草稿的绑定关系仍然有效，且写操作仍走 Skill。"""
    db_dependency, token, account_id = _create_pc_account_with_cookie(tmp_path, "persona-owner")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # 画像接口返回 410，并指向新的唯一来源。
        gone = client.get(f"/api/accounts/{account_id}/persona", headers=headers)
        assert gone.status_code == 410
        assert "创作 Skill" in gone.json()["detail"]

        draft = client.post(
            "/api/drafts",
            headers=headers,
            json={
                "platform": "xhs",
                "title": "绑定账号草稿",
                "body": "正文",
                "platform_account_id": account_id,
            },
        )
        assert draft.status_code == 200
        assert draft.json()["platform_account_id"] == account_id

        listed = client.get("/api/drafts?platform=xhs", headers=headers)
        assert listed.json()["items"][0]["platform_account_id"] == account_id
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_agent_prepare_publish_waits_for_confirmation(tmp_path, monkeypatch):
    import json

    from backend.app.api.ai import get_text_ai_client
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob

    monkeypatch.setattr("backend.app.api.agent._ASYNC_ENABLED", False)

    db_dependency, token, account_id = _create_pc_account_with_cookie(tmp_path, "agent-publish-owner")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        client.post(
            "/api/model-configs",
            headers=headers,
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-agent-publish",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-agent-publish",
                "is_default": True,
            },
        )
        draft = client.post(
            "/api/drafts",
            headers=headers,
            json={
                "platform": "xhs",
                "title": "待发布草稿",
                "body": "正文",
                "platform_account_id": account_id,
            },
        ).json()

        class FakePlanner:
            def complete(self, **kwargs):
                return json.dumps(
                    {
                        "thought": "准备发布",
                        "action": "prepare_publish",
                        "args": {"draft_id": draft["id"]},
                    },
                    ensure_ascii=False,
                )

        app.dependency_overrides[get_text_ai_client] = lambda: FakePlanner()
        created = client.post(
            "/api/agent/runs",
            headers=headers,
            json={"goal": "准备发布这篇草稿", "account_id": account_id},
        )
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "awaiting_confirmation"
        assert run["platform_account_id"] == account_id

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(PublishJob).count() == 0
        finally:
            db.close()

        confirmed = client.post(
            f"/api/agent/runs/{run['id']}/confirm-publish",
            headers=headers,
            json={},
        )
        assert confirmed.status_code == 200
        payload = confirmed.json()
        assert payload["run"]["status"] == "completed"
        assert payload["job"]["id"] > 0
        assert payload["job"]["platform_account_id"] == account_id
        assert payload["job"]["source_draft_id"] == draft["id"]

        db = next(app.dependency_overrides[get_db]())
        try:
            job = db.query(PublishJob).one()
            assert job.platform_account_id == account_id
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_generate_from_images_creates_draft_with_assets(tmp_path):
    from backend.app.api.ai import get_image_ai_client, get_text_ai_client

    class FakeImageClient:
        def describe_image(self, **kwargs):
            return "一杯酸奶燕麦杯，桌面俯拍，自然光，旁边有蓝莓"

    class FakeTextClient:
        def generate_note(self, **kwargs):
            assert "酸奶燕麦杯" in kwargs["reference"]
            return {"title": "5 分钟早餐", "body": "今天做了酸奶燕麦杯。"}

    db_dependency, token, account_id = _create_pc_account_with_cookie(tmp_path, "image-copy-owner")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        for model_payload in (
            {
                "name": "Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-image-copy",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-text",
                "is_default": True,
            },
            {
                "name": "Image",
                "model_type": "image",
                "provider": "openai-compatible",
                "model_name": "vision-model",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-image",
                "is_default": True,
            },
        ):
            created = client.post("/api/model-configs", headers=headers, json=model_payload)
            assert created.status_code == 200

        app.dependency_overrides[get_text_ai_client] = lambda: FakeTextClient()
        app.dependency_overrides[get_image_ai_client] = lambda: FakeImageClient()

        response = client.post(
            "/api/ai/generate-from-images",
            headers=headers,
            json={
                "platform": "xhs",
                "images": [
                    {
                        "file_name": "xhs-upload-u1-a.png",
                        "url": "/api/files/media/xhs-upload-u1-a.png",
                    }
                ],
                "instruction": "早餐",
                "account_id": account_id,
            },
        )
        assert response.status_code == 200
        draft = response.json()
        assert draft["title"] == "5 分钟早餐"
        assert draft["platform_account_id"] == account_id

        assets = client.get(f"/api/drafts/{draft['id']}/assets", headers=headers)
        assert assets.status_code == 200
        assert len(assets.json()["items"]) == 1
        assert assets.json()["items"][0]["url"] == "/api/files/media/xhs-upload-u1-a.png"
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(get_image_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)

