"""「待发布」只有一个口径：接口层实测。

`test_injection_chain.py` 断言的是源码结构（定义在一处、调用方存在）。
这一份跑真实 HTTP，钉住**数字本身**：

* 今日页 `pending_publishes` = pending + scheduled，不含 publishing；
* 发布队列返回的 `counts` 是整表算的，不受 `page_size` / `status` 筛选影响；
* 助手页 `pending_publish_jobs` 不再被 `.limit(5)` 截断。

诊断 I9 的原始表现是「同一个待发布，三个页面三个数字」。这三个数字里只有
发布页那个接近对，另外两个都错——所以不能只改一处。
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
        f"sqlite:///{tmp_path / 'queue-counts.db'}",
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
    return get_db


def _register(username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _seed_jobs(tmp_path, username: str, statuses: list[str]):
    """建一个账号 + 一批指定状态的发布任务，返回 (token, account_id)。"""
    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount, PublishJob, User

    token = _register(username)
    db = next(app.dependency_overrides[get_db]())
    try:
        user = db.query(User).filter(User.username == username).one()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            external_user_id=f"{username}-uid",
            nickname=f"{username} 的号",
            status="active",
        )
        db.add(account)
        db.flush()
        for index, status in enumerate(statuses):
            db.add(
                PublishJob(
                    user_id=user.id,
                    platform_account_id=account.id,
                    platform="xhs",
                    title=f"{status} #{index}",
                    body="正文",
                    publish_mode="immediate",
                    status=status,
                )
            )
        db.commit()
        return token, account.id
    finally:
        db.close()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 定义


def test_pending_count_excludes_publishing(tmp_path):
    """正在发的不算「等你确认」。

    旧实现（今日页）把 publishing 算进待发布：界面说 3 条待确认，点进去
    只有 1 条有确认按钮——另外 2 条已经在发了。
    """
    db_dependency = _override_database(tmp_path)
    try:
        token, _ = _seed_jobs(
            tmp_path,
            "queue-mixed",
            ["pending", "scheduled", "publishing", "published", "failed"],
        )
        response = client.get("/api/xhs/analytics/overview", headers=_headers(token))
        assert response.status_code == 200, response.text
        payload = response.json()
        # pending + scheduled = 2；publishing 单独计数
        assert payload["pending_publishes"] == 2, payload
        assert payload["publishing_jobs"] == 1, payload
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_queue_counts_are_whole_table_not_one_page(tmp_path):
    """`page_size=1` 时统计仍然要数全表。

    前端以前在 `items`（后端分页后的行）上 count，第 21 条起根本不进统计。
    """
    db_dependency = _override_database(tmp_path)
    try:
        token, _ = _seed_jobs(
            tmp_path,
            "queue-paged",
            ["pending"] * 6 + ["published"] * 3,
        )
        response = client.get(
            "/api/publish/jobs?page_size=1", headers=_headers(token)
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        # 只返回一行
        assert len(payload["items"]) == 1
        # 但统计是整表
        assert payload["counts"]["pending"] == 6
        assert payload["counts"]["published"] == 3
        assert payload["counts"]["total"] == 9
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_queue_counts_ignore_status_filter(tmp_path):
    """筛「失败」时仍要看到「待确认 6 条」。

    统计跟着筛选走的话，用户一点「失败」，待确认就变成 0，看起来像队列空了。
    """
    db_dependency = _override_database(tmp_path)
    try:
        token, _ = _seed_jobs(
            tmp_path,
            "queue-filtered",
            ["pending"] * 6 + ["failed"] * 2,
        )
        response = client.get(
            "/api/publish/jobs?status=failed", headers=_headers(token)
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 2
        assert payload["counts"]["pending"] == 6
        assert payload["counts"]["failed"] == 2
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_agent_count_is_not_limited_to_five(tmp_path):
    """助手页以前 `len(publish_jobs)` 而查询带 `.limit(5)`：30 条显示 5。"""
    db_dependency = _override_database(tmp_path)
    try:
        token, _ = _seed_jobs(
            tmp_path,
            "queue-agent",
            ["pending"] * 9,
        )
        # 助手总览：/api/agent/overview → _workbench_overview
        response = client.get("/api/agent/overview", headers=_headers(token))
        assert response.status_code == 200, response.text
        payload = response.json()
        counts = payload.get("counts") or payload
        assert counts["pending_publish_jobs"] == 9, payload
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_cancelled_is_not_pending(tmp_path):
    """取消掉的不该继续挂在「待确认」里。"""
    db_dependency = _override_database(tmp_path)
    try:
        token, _ = _seed_jobs(
            tmp_path, "queue-cancelled", ["pending", "cancelled", "cancelled"]
        )
        response = client.get("/api/publish/jobs", headers=_headers(token))
        payload = response.json()
        assert payload["counts"]["pending"] == 1
        assert payload["counts"]["cancelled"] == 2
    finally:
        app.dependency_overrides.pop(db_dependency, None)
