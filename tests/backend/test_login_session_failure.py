"""The login poll must end, not loop.

When the platform refused the QR exchange the API answered 500 and left the
session at ``scanned``. The UI polls every two seconds and stops only on
``confirmed``/``expired``, so it replayed an already-spent exchange until the
panel was closed — turning a transient block into a sustained one.

These tests pin the contract the UI relies on: a refused login produces a
readable message and a terminal session status.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.main import app


client = TestClient(app)


def _override_database(tmp_path):
    from backend.app.core.database import get_db, Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'login_blocked.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return get_db


class BlockedPcLoginAdapter:
    """Reports risk control, the way the real adapter does after the fix."""

    def create_qrcode(self):
        return {
            "cookies": {"a1": "temp-a1"},
            "qr_id": "qr-blocked",
            "code": "code-blocked",
            "qr_url": "https://example.test/qr",
        }

    def check_qrcode_status(self, qr_id, code, cookies):
        return {
            "status": "blocked",
            "cookies": cookies,
            "state": {},
            "blocked_status_code": 471,
        }

    def get_user_info(self, cookies):  # pragma: no cover - must not be reached
        raise AssertionError("a blocked login must never fetch user info")

    def release(self, qr_id):
        return None


class CrashingPcLoginAdapter(BlockedPcLoginAdapter):
    def check_qrcode_status(self, qr_id, code, cookies):
        raise RuntimeError("socket closed mid-flight")


def _token(username: str) -> str:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_blocked_login_returns_a_readable_error_not_a_500(tmp_path):
    from backend.app.api.login_sessions import get_pc_login_adapter
    from backend.app.models import LoginSession

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: BlockedPcLoginAdapter()
    try:
        token = _token("blocked-operator")
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/xhs/login-sessions/pc/qrcode", headers=headers).json()

        response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}", headers=headers
        )

        assert response.status_code == 429, "风控拦截必须是可读的 429，不是 500"
        detail = response.json()["detail"]
        assert "风控" in detail
        assert "471" in detail
        assert detail != "Internal Server Error"

        # Terminal: the next poll must not repeat the blocked exchange.
        second = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}", headers=headers
        )
        assert second.status_code == 200
        assert second.json()["status"] == "expired"

        from backend.app.core.database import get_db

        db = next(app.dependency_overrides[get_db]())
        try:
            stored = db.get(LoginSession, created["session_id"])
            assert stored.status == "expired"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)


def test_crashing_login_check_reports_the_reason(tmp_path):
    from backend.app.api.login_sessions import get_pc_login_adapter
    from backend.app.models import LoginSession

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: CrashingPcLoginAdapter()
    try:
        token = _token("crash-operator")
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/xhs/login-sessions/pc/qrcode", headers=headers).json()

        response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}", headers=headers
        )

        assert response.status_code == 502, "未预期的异常不能再伪装成 500"
        assert "socket closed mid-flight" in response.json()["detail"]

        from backend.app.core.database import get_db

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(LoginSession, created["session_id"]).status == "expired"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
