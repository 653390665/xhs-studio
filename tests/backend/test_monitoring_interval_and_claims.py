"""Two ways the UI described something the code did not do.

1. Monitoring targets: the form wrote ``config.refresh_interval_minutes`` but the
   scheduler reads the ``crawl_interval_minutes`` column. Nothing copied one to
   the other, so a target set to 10 minutes crawled every 60 — and the screen read
   ``config`` back, so it confidently displayed 10.

2. Skill library: the panel claimed 「写稿、选题、排期、视觉任务会自动挑选最相关的
   3–4 个」. ``module_skill_text`` is only called for draft / topic / visual, and
   its limit is 3, so "排期 auto-routes" and "3–4" were both untrue.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.main import app


client = TestClient(app)


def _override_database(tmp_path):
    from backend.app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'interval.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return get_db


def _token(username: str) -> str:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


# --- monitoring refresh interval -------------------------------------------


def test_creating_a_target_copies_the_interval_to_the_scheduler_column(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {_token('interval-owner')}"}
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers=headers,
            json={
                "target_type": "keyword",
                "name": "AI",
                "value": "AI",
                "config": {"refresh_interval_minutes": 10},
            },
        )
        assert created.status_code == 200
        body = created.json()

        assert body["config"]["refresh_interval_minutes"] == 10
        # The column the scheduler actually reads must agree.
        assert body["crawl_interval_minutes"] == 10, (
            "调度器读 crawl_interval_minutes，创建时必须同步写入"
        )
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_updating_the_interval_keeps_both_in_sync(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {_token('interval-updater')}"}
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers=headers,
            json={"target_type": "keyword", "value": "AI", "name": "AI"},
        ).json()

        updated = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers=headers,
            json={"config": {"refresh_interval_minutes": 25}},
        )
        assert updated.status_code == 200
        assert updated.json()["crawl_interval_minutes"] == 25
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_interval_below_the_floor_is_clamped(tmp_path):
    """Crawling every minute would trip risk control."""
    db_dependency = _override_database(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {_token('interval-floor')}"}
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers=headers,
            json={
                "target_type": "keyword",
                "value": "AI",
                "name": "AI",
                "config": {"refresh_interval_minutes": 1},
            },
        ).json()

        assert created["crawl_interval_minutes"] == 5
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_renaming_without_an_interval_does_not_reset_it(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {_token('interval-rename')}"}
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers=headers,
            json={
                "target_type": "keyword",
                "value": "AI",
                "name": "AI",
                "config": {"refresh_interval_minutes": 15},
            },
        ).json()

        renamed = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers=headers,
            json={"name": "AI 赛道"},
        ).json()

        assert renamed["crawl_interval_minutes"] == 15
    finally:
        app.dependency_overrides.pop(db_dependency, None)


# --- the skill library's claims -------------------------------------------


def test_crawl_interval_sync_is_idempotent():
    """Calling the helper twice must not drift the value."""
    from backend.app.api.platforms.xhs.monitoring import _sync_crawl_interval
    from backend.app.models import MonitoringTarget

    target = MonitoringTarget(
        user_id=1, platform="xhs", target_type="keyword", name="x", value="x"
    )
    target.crawl_interval_minutes = 60

    _sync_crawl_interval(target, {"refresh_interval_minutes": 12})
    assert target.crawl_interval_minutes == 12
    _sync_crawl_interval(target, {"refresh_interval_minutes": 12})
    assert target.crawl_interval_minutes == 12


def test_sync_ignores_junk_values():
    from backend.app.api.platforms.xhs.monitoring import _sync_crawl_interval
    from backend.app.models import MonitoringTarget

    target = MonitoringTarget(
        user_id=1, platform="xhs", target_type="keyword", name="x", value="x"
    )
    target.crawl_interval_minutes = 60

    for junk in (None, "", "abc", {}, []):
        _sync_crawl_interval(target, {"refresh_interval_minutes": junk})
        assert target.crawl_interval_minutes == 60, f"{junk!r} 不该改动间隔"

    _sync_crawl_interval(target, None)
    assert target.crawl_interval_minutes == 60


def test_only_three_modules_are_auto_injected():
    """Pins the claim the panel now makes: draft/topic/visual only, limit 3."""
    import inspect

    from backend.app.services import skill_library_service

    source = inspect.getsource(skill_library_service.module_skill_text)
    assert "limit: int = 3" in source

    modules = {item["key"]: item for item in skill_library_service.MODULES}
    injected = {key for key, item in modules.items() if item.get("auto_injected")}
    assert injected == {"draft", "topic", "visual"}, (
        "Skill 库的文案必须与真实注入的模块一致"
    )
    assert "schedule" not in injected, "排期从不自动注入"
