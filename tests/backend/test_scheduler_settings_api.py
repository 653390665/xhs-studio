"""P0-2 收口：在界面改调度器开关，要真的落地并生效。

配置加载链已经补上（`config.py` 读 `user_settings.json`）。这里补上「写」的
半边：`GET/PUT /api/settings/scheduler`。

四个必须成立的点：

1. 写文件 → `get_settings.cache_clear()` → 再读到的就是新值；
2. 停/起 `app.state.scheduler` 时不能 kill 到一半——`shutdown(wait=True)`
   让正在跑的那一轮跑完；
3. 部署里用环境变量指定了状态时，界面不能悄悄覆盖（返回 409 说明原因）；
4. 状态接口如实报告 `enabled` / `running`，界面上那行提示才有意义。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.app.core.config as config_module
from backend.app.core.config import get_settings
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.api import scheduler_settings as sched_api


class FakeScheduler:
    """记录 start/shutdown，不真的起线程。"""

    def __init__(self):
        self.running = False
        self.shutdown_calls: list[bool] = []

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.shutdown_calls.append(wait)
        self.running = False

    def get_jobs(self):
        return []


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sch.db'}", connect_args={"check_same_thread": False}
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
    monkeypatch.setattr(
        config_module, "_load_yaml_config", lambda: {"scheduler_enabled": False}
    )
    monkeypatch.setattr(config_module, "_dotenv_keys", lambda: set())
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    get_settings.cache_clear()

    built: list[FakeScheduler] = []

    def fake_start(interval):
        fake = FakeScheduler()
        fake.start()
        built.append(fake)
        return fake

    monkeypatch.setattr(
        "backend.app.services.scheduler_service.start_due_publish_scheduler",
        fake_start,
    )

    app = FastAPI()
    app.include_router(sched_api.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    app.state.scheduler = None

    with TestClient(app) as c:
        yield c, app, settings_file, built
    db.close()
    get_settings.cache_clear()


def test_scheduler_starts_disabled(ctx):
    c, _app, _path, _built = ctx
    payload = c.get("/api/settings/scheduler").json()

    assert payload["enabled"] is False
    assert payload["running"] is False


def test_enabling_writes_the_file_and_clears_the_cache(ctx):
    c, app, path, built = ctx

    response = c.put(
        "/api/settings/scheduler", json={"enabled": True, "interval_seconds": 45}
    )
    assert response.status_code == 200, response.text

    assert path.is_file(), "开关没写到 user_settings.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["scheduler_enabled"] is True
    assert saved["scheduler_interval_seconds"] == 45

    settings = get_settings()
    assert settings.scheduler_enabled is True, "cache 没清，读到还是旧值"
    assert settings.scheduler_interval_seconds == 45
    assert len(built) == 1 and app.state.scheduler is built[0]
    assert app.state.scheduler.running is True


def test_disabling_stops_the_running_scheduler_and_waits(ctx):
    c, app, _path, built = ctx
    c.put("/api/settings/scheduler", json={"enabled": True})
    running = app.state.scheduler
    assert running.running is True

    response = c.put("/api/settings/scheduler", json={"enabled": False})
    assert response.status_code == 200, response.text

    assert running.running is False
    assert running.shutdown_calls == [True], "shutdown 必须等正在跑的那一轮结束"
    assert app.state.scheduler is None


def test_interval_must_be_sane(ctx):
    c, _app, _path, _built = ctx

    assert (
        c.put("/api/settings/scheduler", json={"interval_seconds": 1}).status_code
        == 422
    )
    assert (
        c.put("/api/settings/scheduler", json={"interval_seconds": 99999}).status_code
        == 422
    )


def test_env_var_wins_and_the_ui_says_so(ctx):
    """部署时用环境变量指定了调度器状态：界面不能悄悄改掉。"""
    c, _app, path, _built = ctx
    import os

    os.environ["SCHEDULER_ENABLED"] = "false"
    try:
        response = c.put("/api/settings/scheduler", json={"enabled": True})
        assert response.status_code == 409
        assert "环境变量" in response.json()["detail"]
        assert not path.is_file(), "被拒绝了还写了文件"
        assert c.get("/api/settings/scheduler").json()["editable"] is False
    finally:
        os.environ.pop("SCHEDULER_ENABLED", None)


def test_status_reports_what_is_actually_running(ctx):
    c, app, _path, built = ctx
    app.state.scheduler = FakeScheduler()
    app.state.scheduler.running = True

    payload = c.get("/api/settings/scheduler").json()
    assert payload["enabled"] is False, "文件里没开，就得如实报 false"
    assert payload["running"] is True, "调度器在跑，也不能瞒着"
