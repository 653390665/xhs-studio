"""P0-4：排期路径也要有速率保护。

`auto_publish_guard`（3 条/天 + 60 分钟间隔）原来只挂在自动运营路径
（`scheduler_service.py` 的 `_execute_auto_task_background`）。排期路径
（`run_due_publish_jobs`）无上限：同一分钟到点的 10 条会连发 10 条。

人手动点「确认发布」时，连发是他自己按的，不需要闸；调度器替他按的时候
必须有。所以闸只在 `require_auto_publish=True`（无人值守）时生效。
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
from backend.app.services.scheduler_service import run_due_publish_jobs


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
    user = User(username="p0-4", password_hash="x")
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
    setting = RiskControlSetting(
        user_id=user.id,
        auto_publish_enabled=True,
        auto_create_publish_job_enabled=True,
    )
    db.add(setting)
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


def make_due_job(db, user, account, minutes=5):
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title="排期任务",
        body="这是一段足够长的正文，用来通过发布前的长度检查",
        publish_mode="scheduled",
        status="pending",
        scheduled_at=shanghai_now() - timedelta(minutes=minutes),
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


def already_published_today(db, user, account, count):
    for i in range(count):
        db.add(
            PublishJob(
                user_id=user.id,
                platform_account_id=account.id,
                platform="xhs",
                title=f"今天已发 {i}",
                body="正文",
                publish_mode="immediate",
                status="published",
                published_at=shanghai_now() - timedelta(minutes=10 + i),
                created_at=shanghai_now() - timedelta(minutes=10 + i),
            )
        )
    db.commit()


def test_daily_cap_stops_the_scheduled_path(db, owner):
    user, account = owner
    already_published_today(db, user, account, 3)
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
    assert job.status == "pending", "今日已发 3 条上限，到点任务仍然发出去了"
    assert RecordingAdapter.calls == []
    assert "上限" in job.publish_error
    assert result["waiting_count"] >= 1


def test_min_interval_stops_two_in_a_minute(db, owner):
    user, account = owner
    first = make_due_job(db, user, account, minutes=5)
    second = make_due_job(db, user, account, minutes=4)
    RecordingAdapter.calls = []

    result = run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
        require_auto_publish=True,
    )

    db.refresh(first)
    db.refresh(second)
    statuses = {first.status, second.status}
    assert len(RecordingAdapter.calls) == 1, (
        f"连发了 {len(RecordingAdapter.calls)} 条——间隔检查没生效"
    )
    assert "pending" in statuses, "被间隔挡住的那条应留在 pending 等人处理"
    assert result["waiting_count"] >= 1


def test_manual_path_is_not_capped(db, owner):
    """人点 `/api/tasks/run-due` 时不该被自动发布的限额挡住。"""
    user, account = owner
    already_published_today(db, user, account, 3)
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
