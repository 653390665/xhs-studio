"""P0-1 方案 A：到点自动发必须显式打开「自动发布」。

界面三处承诺（`Publish.tsx:55/96/303`）：

    排了时间，到点仍需确认（不会自动发）
    排好的时间也要你手动确认一次，后台不会偷偷发出去
    发布是唯一会对外的动作。所以这条链路上没有任何"自动发"的开关。

代码事实：`run_due_publish_jobs` 全文没有 `get_risk_controls`，
`auto_publish_enabled` 只在自动运营路径被读。也就是说这三句话今天为真，
**只因为 `SCHEDULER_ENABLED=false`**。一旦为了 cookie 体检或指标刷新打开
调度器，所有排期任务会到点真发。

修法：无人值守路径传 `require_auto_publish=True`，没开开关就把到点任务
留在 `pending` 等人确认；手动 `/api/tasks/run-due` 保持 False（人已经点了）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    RiskControlSetting,
    User,
)
from backend.app.services.scheduler_service import (
    run_due_publish_jobs,
    run_due_publish_jobs_for_all_users,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def owner(db):
    user = User(username="p0-1", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="a", status="active"
    )
    db.add(account)
    db.flush()
    db.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text("a1=test; web_session=s"),
        )
    )
    db.commit()
    db.refresh(account)
    return user, account


class RecordingAdapter:
    calls: list[dict] = []

    def __init__(self, cookies):
        self.cookies = cookies

    def upload_media(self, path, kind):
        return {"creator_media_id": "m1"}

    def post_note(self, note_info):
        RecordingAdapter.calls.append(note_info)
        return {"data": {"note_id": "fake-note"}}


def make_due_job(db, user, account):
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title="到点的排期任务",
        body="这是一段足够长的正文，用来通过发布前的长度检查",
        publish_mode="scheduled",
        status="pending",
        scheduled_at=shanghai_now() - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.add(
        PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="/tmp/a.png",
            upload_status="uploaded",
            creator_upload_info='{"fileIds": ["f1"]}',
            creator_media_id="m1",
        )
    )
    db.commit()
    return job


def enable_auto_publish(db, user):
    setting = db.query(RiskControlSetting).filter_by(user_id=user.id).first()
    if setting is None:
        setting = RiskControlSetting(user_id=user.id)
        db.add(setting)
    setting.auto_publish_enabled = True
    setting.auto_create_publish_job_enabled = True
    db.commit()
    return setting


# --- 无人值守：没有开关就不许发 ---------------------------------------------


def test_unattended_run_leaves_due_job_pending_without_the_switch(db, owner):
    user, account = owner
    job = make_due_job(db, user, account)
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=True,
    )

    db.refresh(job)
    assert job.status == "pending", "没开「自动发布」却把内容发出去了"
    assert RecordingAdapter.calls == [], "平台侧收到了不该有的发布"
    assert result["executed_count"] == 0
    assert result["waiting_count"] == 1
    assert "自动发布" in result["skipped_reason"]


def test_unattended_run_publishes_once_the_switch_is_on(db, owner):
    user, account = owner
    job = make_due_job(db, user, account)
    enable_auto_publish(db, user)
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=True,
    )

    db.refresh(job)
    assert job.status == "published"
    assert result["executed_count"] == 1
    assert len(RecordingAdapter.calls) == 1


def test_all_users_path_is_safe_by_default(db, owner):
    """定时器走的是 for_all_users，它必须默认安全。"""
    user, account = owner
    job = make_due_job(db, user, account)
    RecordingAdapter.calls = []

    result = run_due_publish_jobs_for_all_users(
        db=db,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
    )

    db.refresh(job)
    assert job.status == "pending"
    assert RecordingAdapter.calls == []
    assert result["waiting_count"] == 1


# --- 手动路径：人已经点了，不该再被开关挡住 ---------------------------------


def test_manual_run_due_still_publishes_without_the_switch(db, owner):
    """`POST /api/tasks/run-due` 是人点的，不能被无人值守的规则挡住。"""
    user, account = owner
    job = make_due_job(db, user, account)
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=False,
    )

    db.refresh(job)
    assert job.status == "published"
    assert result["executed_count"] == 1


def test_no_due_job_reports_zero_waiting(db, owner):
    user, account = owner
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=True,
    )

    assert result["executed_count"] == 0
    assert result["waiting_count"] == 0


def test_future_job_is_not_counted_as_waiting(db, owner):
    """没到点的不算「等你确认」——它只是还没到。"""
    user, account = owner
    job = make_due_job(db, user, account)
    job.scheduled_at = shanghai_now() + timedelta(hours=3)
    db.commit()
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=True,
    )

    assert result["waiting_count"] == 0
