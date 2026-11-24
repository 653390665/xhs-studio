"""Diagnostics endpoint: recent API errors, failed tasks, account/template issues."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import ApiLog, AutoTask, PlatformAccount, Task

client = TestClient(app)


def _override_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostics.db'}",
        connect_args={"check_same_thread": False},
    )
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


def test_diagnostics_lists_actionable_failures(tmp_path):
    db_dependency = _override_database(tmp_path)
    register = client.post(
        "/api/auth/register",
        json={"username": "diagnostics-owner", "password": "secret123"},
    )
    assert register.status_code == 200
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    db = next(app.dependency_overrides[get_db]())
    try:
        db.add_all(
            [
                ApiLog(
                    user_id=1,
                    platform="xhs",
                    endpoint="/api/xhs/broken",
                    status="warning",
                    meta={"method": "GET", "status_code": 400},
                ),
                Task(
                    user_id=1,
                    platform="xhs",
                    task_type="ai_generate_note",
                    status="failed",
                    error_type="model_error",
                ),
                PlatformAccount(
                    user_id=1,
                    platform="xhs",
                    sub_type="pc",
                    external_user_id="expired-account",
                    nickname="过期账号",
                    status="expired",
                ),
                AutoTask(
                    user_id=1,
                    name="失效模板任务",
                    keywords=["Excel"],
                    pc_account_id=1,
                    creator_account_id=2,
                    template_id=999999,
                    status="active",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    try:
        response = client.get(
            "/api/system/diagnostics?days=7",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["summary"]["api_errors"] == 1
        assert data["summary"]["failed_tasks"] == 1
        assert data["summary"]["account_issues"] == 1
        assert data["summary"]["template_issues"] == 1
        assert data["api_errors"][0]["endpoint"] == "/api/xhs/broken"
        assert data["failed_tasks"][0]["error_type"] == "model_error"
        assert data["template_issues"][0]["reason"] == "模板不存在"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
