"""Manual auto-task runs can be queued and polled without blocking the request."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from backend.app.api import auto_tasks
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import AutoTask, PlatformAccount, Task, User

client = TestClient(app)


def _override_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auto-task-async.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return engine, get_db


def _register(username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_run_async_enqueues_without_running_inline(tmp_path, monkeypatch):
    engine, db_dependency = _override_database(tmp_path)
    token = _register("auto-async-owner")
    headers = {"Authorization": f"Bearer {token}"}
    submitted = []

    monkeypatch.setattr(
        auto_tasks._AUTO_TASK_EXECUTOR,
        "submit",
        lambda fn, *args: submitted.append((fn, args)),
    )
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            pc = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="pc",
                nickname="pc",
                status="active",
            )
            creator = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="creator",
                nickname="creator",
                status="active",
            )
            db.add_all([pc, creator])
            db.flush()
            auto_task = AutoTask(
                user_id=1,
                name="后台任务",
                keywords=["早餐"],
                pc_account_id=pc.id,
                creator_account_id=creator.id,
                schedule_type="manual",
                status="active",
            )
            db.add(auto_task)
            db.commit()
            task_id = auto_task.id
        finally:
            db.close()

        risk = client.put(
            "/api/settings/risk-controls",
            headers=headers,
            json={
                "auto_ops_enabled": True,
                "competitor_rewrite_enabled": True,
                "acknowledge_risk": True,
            },
        )
        assert risk.status_code == 200, risk.text

        response = client.post(
            f"/api/auto-tasks/{task_id}/run-async",
            headers=headers,
        )

        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["task_id"]

        db = next(app.dependency_overrides[get_db]())
        try:
            tracking = db.get(Task, payload["task_id"])
            assert tracking is not None
            assert tracking.task_type == "auto_ops_run"
            assert tracking.status == "pending"
            assert tracking.payload["auto_task_id"] == task_id
        finally:
            db.close()

        assert len(submitted) == 1
        assert submitted[0][1][0] == payload["task_id"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        engine.dispose()


def test_background_worker_stores_result_and_completes(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auto-task-worker.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(auto_tasks, "SessionLocal", testing_session)

    fake_result = {"draft": {"id": 9}, "publish_job": None}
    monkeypatch.setattr(
        auto_tasks,
        "_execute_auto_task_run",
        lambda *args, **kwargs: fake_result,
    )

    db = testing_session()
    try:
        user = User(username="worker-owner", password_hash="x")
        db.add(user)
        db.flush()
        auto_task = AutoTask(
            user_id=user.id,
            name="worker",
            keywords=["早餐"],
            pc_account_id=1,
            creator_account_id=2,
            schedule_type="manual",
            status="active",
        )
        db.add(auto_task)
        db.flush()
        tracking = Task(
            user_id=user.id,
            platform="xhs",
            task_type="auto_ops_run",
            status="pending",
            progress=0,
            payload={"auto_task_id": auto_task.id},
        )
        db.add(tracking)
        db.commit()
        tracking_id = tracking.id
        auto_task_id = auto_task.id
        user_id = user.id
    finally:
        db.close()

    auto_tasks._run_auto_task_background(tracking_id, auto_task_id, user_id, lambda cookies: None)

    db = testing_session()
    try:
        tracking = db.get(Task, tracking_id)
        assert tracking.status == "completed"
        assert tracking.progress == 100
        assert tracking.payload["result"] == fake_result
        assert tracking.finished_at is not None
    finally:
        db.close()
        engine.dispose()
