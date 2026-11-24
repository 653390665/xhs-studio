"""送发布的状态机：预检、账号必填、改稿后行为。

这四条都是 2026-11-18 在活库上复现出来的。修法记录：

* 预检原来是 ``if payload.publish_mode == "scheduled"``——只有定时才查。
  空标题/空正文/零素材的草稿能直接进队列（status=pending），点确认才 400，
  而那条 job 既没有 publish_error 也不能重试，唯一出路是「取消」。
  现在两种模式都跑 ``preflight_publish_job``。
* 不带 ``platform_account_id`` 也能建 job，队列显示「待确认」，
  点确认才报「请先选择发布账号」。现在建 job 前就拒绝。
* ``_find_active_publish_job_for_draft`` 把 ``published`` 也算活跃任务，
  改完稿再送发布拿回的是旧 job（标题还是上一版）。
  现在 published 不算；但账号/时间/内容任一变化时返回 409，
  因为静默新建会让用户以为旧任务被替换了。
* 删草稿只把 ``source_draft_id`` 置 NULL，job 仍 pending。见
  ``test_deleting_draft_does_not_leave_a_dead_pending_job``（仍 xfail）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.api import drafts as drafts_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import encrypt_text
from backend.app.models import (
    AccountCookieVersion,
    AiDraft,
    DraftAsset,
    PlatformAccount,
    PublishJob,
    User,
)


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'publish.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="a", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    # 预检要求账号有可用 Cookie：没有就会报 error，这属于另一条规则，
    # 不能让它在「送发布状态机」这组测试里挡路。
    db.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text("a1=test; web_session=s"),
        )
    )
    db.commit()

    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c, Session, user, account
    db.close()


def _draft(Session, user, title="标题", body="正文" * 50, *, with_image=True):
    """建一篇草稿。默认带一张图——预检要求至少一个素材。"""
    db = Session()
    row = AiDraft(user_id=user.id, platform="xhs", title=title, body=body)
    db.add(row)
    db.commit()
    db.refresh(row)
    if with_image:
        db.add(
            DraftAsset(
                draft_id=row.id,
                asset_type="image",
                url="https://example.test/cover.webp",
                local_path="",
                sort_order=0,
            )
        )
        db.commit()
    draft_id = row.id
    db.close()
    return draft_id


def test_immediate_send_runs_preflight_for_empty_draft(client):
    """空标题/空正文的稿子不该进队列（素材可以后补，文字不行）。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="", body="", with_image=False)

    response = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )

    assert response.status_code == 400, response.text
    assert "标题不能为空" in response.text or "正文为空" in response.text

    db = Session()
    jobs = db.scalars(select(PublishJob)).all()
    db.close()
    assert jobs == [], "预检失败时不该留下任何 job"


def test_send_accepts_draft_without_assets(client):
    """素材可以进队列后再补：发布队列有「加素材」接口。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="有字没图", body="正文" * 50, with_image=False)

    response = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"


def test_send_requires_an_account(client):
    """没有账号就不该建 job：否则点确认时才报错，用户以为已经排好。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user)

    response = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"publish_mode": "immediate"},
    )

    assert response.status_code == 400
    assert "账号" in response.text


def test_resending_unchanged_draft_is_idempotent(client):
    """内容没变、账号没变、时间没变 → 复用同一条 job，不重复建。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user)

    first = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    assert first.status_code == 200, first.text

    second = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    db = Session()
    assert len(db.scalars(select(PublishJob)).all()) == 1
    db.close()


def test_republishing_after_edit_is_refused_not_silently_stale(client):
    """改完稿再送发布，不能悄悄返回旧的 pending job。

    旧实现直接返回那条 job（标题还是上一版），界面提示「已送进队列」，
    用户以为改后的内容排上了。现在返回 409，让用户显式取消旧任务再送。
    """
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="第一版", body="正文" * 50)

    first = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    assert first.status_code == 200, first.text

    c.patch(f"/api/drafts/{draft_id}", json={"title": "第二版"})
    second = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )

    assert second.status_code == 409, second.text
    assert "已经有一条待发任务" in second.text

    db = Session()
    jobs = db.scalars(select(PublishJob)).all()
    db.close()
    assert len(jobs) == 1, "被拒绝时不该留下第二条 job"
    assert jobs[0].title == "第一版"


def test_republishing_after_publish_creates_a_new_job(client):
    """已经发出去之后，改稿再送必须能建新任务。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="第一版", body="正文" * 50)

    first = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    assert first.status_code == 200, first.text
    first_job = first.json()

    db = Session()
    job = db.get(PublishJob, first_job["id"])
    job.status = "published"
    db.commit()
    db.close()

    c.patch(f"/api/drafts/{draft_id}", json={"title": "第二版"})
    second = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )

    assert second.status_code == 200, second.text
    second_job = second.json()
    assert second_job["id"] != first_job["id"], "改稿后送发布返回了旧 job"
    assert second_job["title"] == "第二版"


def test_deleting_draft_cancels_its_unfinished_jobs(client):
    """删草稿不能留一条永远发不出去的 pending 任务。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="待删", body="正文" * 50)

    created = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]

    assert c.delete(f"/api/drafts/{draft_id}").status_code == 200

    db = Session()
    job = db.get(PublishJob, job_id)
    db.close()
    assert job is None or job.status == "cancelled", (
        f"删草稿后 job 仍是 {job.status if job else '-'}"
    )
    if job is not None:
        assert job.publish_error, "取消后要说明原因，否则用户不知道它为什么没发"


def test_deleting_draft_keeps_published_history(client):
    """已发布的记录要保留（只是断开来源），不能一起取消。"""
    c, Session, user, account = client
    draft_id = _draft(Session, user, title="已发", body="正文" * 50)

    created = c.post(
        f"/api/drafts/{draft_id}/send-to-publish",
        json={"platform_account_id": account.id, "publish_mode": "immediate"},
    )
    job_id = created.json()["id"]

    db = Session()
    job = db.get(PublishJob, job_id)
    job.status = "published"
    db.commit()
    db.close()

    assert c.delete(f"/api/drafts/{draft_id}").status_code == 200

    db = Session()
    job = db.get(PublishJob, job_id)
    db.close()
    assert job is not None
    assert job.status == "published", "已发布的历史不该被改成 cancelled"
    assert job.source_draft_id is None, "来源要断开，避免悬空引用"
