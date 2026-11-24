"""浏览器采集：令牌鉴权、去重、时长过滤、建任务。"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import CaptureToken, DouyinExtractJob, DouyinWork, User
from backend.app.services.capture_service import (
    CaptureError,
    create_capture_job,
    plan_capture,
)
from backend.app.services.capture_token_service import (
    create_token,
    hash_token,
    resolve_user,
    revoke_token,
)

client = TestClient(app)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capture.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    user = User(username="capture-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    return session, user


def _work(work_id: str, *, duration: float = 30, play: str = "https://example.invalid/v.mp4"):
    return {
        "work_id": work_id,
        "desc": f"作品 {work_id}",
        "duration": duration,
        "play": play,
        "likes": 10,
        "create_time": 1790000000,
    }


# --- 令牌 -------------------------------------------------------------------


def test_token_is_stored_hashed_and_resolves(tmp_path):
    session, user = _session(tmp_path)
    row, raw = create_token(session, user, name="我的浏览器")

    assert raw.startswith("xhs_cap_")
    assert row.token_hash == hash_token(raw)
    assert raw not in row.token_hash
    assert row.token_prefix == raw[:14]

    resolved = resolve_user(session, raw)
    assert resolved is not None and resolved.id == user.id
    assert session.get(CaptureToken, row.id).last_used_at is not None

    assert resolve_user(session, "wrong") is None
    session.close()


def test_revoked_token_cannot_resolve(tmp_path):
    session, user = _session(tmp_path)
    row, raw = create_token(session, user)

    assert revoke_token(session, user, row.id) is True
    assert resolve_user(session, raw) is None
    assert revoke_token(session, user, row.id) is False
    session.close()


# --- 过滤与去重 ---------------------------------------------------------------


def test_plan_filters_duration_duplicates_and_existing(tmp_path):
    session, user = _session(tmp_path)
    session.add(
        DouyinWork(
            job_id=1,
            user_id=user.id,
            work_id="already",
            status="transcribed",
        )
    )
    session.commit()

    plan = plan_capture(
        session,
        user,
        [
            _work("new"),
            _work("new"),  # 重复
            _work("already"),  # 已有
            _work("long", duration=120),
            _work("broken", play=""),
        ],
    )

    assert [item["work_id"] for item in plan["items"]] == ["new"]
    assert plan["filtered_duplicate"] == 1
    assert plan["skipped_existing"] == 1
    assert plan["filtered_duration"] == 1
    assert plan["filtered_invalid"] == 1
    session.close()


def test_unknown_duration_is_kept_because_the_probe_can_still_read_it(tmp_path):
    session, user = _session(tmp_path)

    plan = plan_capture(session, user, [_work("unknown", duration=0)])

    assert [item["work_id"] for item in plan["items"]] == ["unknown"]
    session.close()


def test_no_new_work_raises_with_reasons(tmp_path):
    session, user = _session(tmp_path)
    with __import__("pytest").raises(CaptureError) as exc:
        create_capture_job(
            session,
            user,
            author_name="测试作者",
            author_sec_uid="sec",
            works=[_work("long", duration=200)],
        )
    assert "超出" in str(exc.value)
    session.close()


# --- 端到端接口 ---------------------------------------------------------------


def _override_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capture-api.db'}", connect_args={"check_same_thread": False}
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
    return engine, TestingSession


def test_capture_api_requires_a_token(tmp_path):
    _override_db(tmp_path)
    try:
        response = client.post("/api/douyin/capture", json={"works": [_work("1")]})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def _register_and_access_token(username: str) -> str:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_extension_info_points_at_the_bundled_folder(tmp_path):
    _override_db(tmp_path)
    try:
        access = _register_and_access_token("extension-owner")
        response = client.get(
            "/api/douyin/capture/extension",
            headers={"Authorization": f"Bearer {access}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["exists"] is True
        assert body["path"].replace("\\", "/").endswith(
            "browser-extension/douyin-capture"
        )
        assert body["name"]
        assert body["version"]
    finally:
        app.dependency_overrides.clear()


def test_extension_folder_can_be_opened_from_the_app(tmp_path, monkeypatch):
    _override_db(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        "backend.app.api.platforms.douyin.capture.os.startfile",
        lambda path: opened.append(path),
        raising=False,
    )
    try:
        access = _register_and_access_token("extension-open-owner")
        response = client.post(
            "/api/douyin/capture/extension/open",
            headers={"Authorization": f"Bearer {access}"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert opened and opened[0].replace("\\", "/").endswith(
            "browser-extension/douyin-capture"
        )
    finally:
        app.dependency_overrides.clear()


def test_capture_api_creates_a_job_and_rejects_a_second_run(tmp_path):
    engine, TestingSession = _override_db(tmp_path)
    try:
        register = client.post(
            "/api/auth/register", json={"username": "captureapi", "password": "secret123"}
        )
        assert register.status_code == 200
        access = register.json()["access_token"]

        token_response = client.post(
            "/api/capture-tokens",
            headers={"Authorization": f"Bearer {access}"},
            json={"name": "插件"},
        )
        assert token_response.status_code == 201
        capture_token = token_response.json()["token"]

        payload = {
            "author_name": "测试作者",
            "author_sec_uid": "sec",
            "auto_start": False,
            "works": [
                _work("111"),
                _work("111"),
                _work("222", duration=120),
                _work("333", play=""),
            ],
        }
        response = client.post(
            "/api/douyin/capture",
            headers={"Authorization": f"Bearer {capture_token}"},
            json=payload,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["accepted"] == 1
        assert body["filtered_duplicate"] == 1
        assert body["filtered_duration"] == 1
        assert body["filtered_invalid"] == 1

        db = TestingSession()
        job = db.get(DouyinExtractJob, body["job_id"])
        assert job is not None and job.total == 1
        works = db.scalars(select(DouyinWork).where(DouyinWork.job_id == job.id)).all()
        assert [work.work_id for work in works] == ["111"]
        db.close()

        second = client.post(
            "/api/douyin/capture",
            headers={"Authorization": f"Bearer {capture_token}"},
            json={"author_name": "测试作者", "works": [_work("111")], "auto_start": False},
        )
        assert second.status_code == 400
        assert "已采集" in second.json()["detail"]
    finally:
        app.dependency_overrides.clear()
