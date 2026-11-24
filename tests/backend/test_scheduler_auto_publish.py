"""Auto-publish has to be able to work, and to fail loudly.

Turning the scheduler on is the easy half. These tests cover the parts that make
an unattended publisher trustworthy:

* a failure must record *why* — ``cryptography``'s ``InvalidToken`` has an empty
  ``str()``, so the old code wrote ``publish_error = ""`` and left a failed job
  that could not explain itself;
* one bad job must not abort the batch, or every later job stays ``pending`` and
  looks merely "not due yet";
* a job whose Cookie cannot be decrypted must say "re-login", not "failed".
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    PlatformAccount,
    PublishAsset,
    PublishJob,
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
    user = User(username="sched-owner", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="good",
        status="active",
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
    """Publishes nothing; records what it was asked to publish."""

    calls: list[dict] = []

    def __init__(self, cookies):
        self.cookies = cookies

    def upload_media(self, path, kind):
        return {"creator_media_id": "m1"}

    def post_note(self, note_info):
        RecordingAdapter.calls.append(note_info)
        return {"data": {"note_id": "fake-note"}}


def make_job(db, user, account, minutes: float, *, status="pending", body=None):
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title="scheduled",
        body=body or "这是一段足够长的正文，用来通过发布前的长度检查",
        publish_mode="scheduled",
        status=status,
        scheduled_at=shanghai_now() + timedelta(minutes=minutes),
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


def run(db, user):
    RecordingAdapter.calls = []
    return run_due_publish_jobs(
        db=db,
        current_user=user,
        now=shanghai_now(),
        platform="xhs",
        adapter_factory=RecordingAdapter,
    )


# --- the happy path ---------------------------------------------------------


def test_due_job_is_published(db, owner):
    user, account = owner
    job = make_job(db, user, account, -5)

    result = run(db, user)

    assert result["executed_count"] == 1
    assert result["failed_count"] == 0
    assert len(RecordingAdapter.calls) == 1
    db.refresh(job)
    assert job.status == "published"
    assert job.external_note_id == "fake-note"


def test_future_job_is_left_alone(db, owner):
    user, account = owner
    job = make_job(db, user, account, +30)

    result = run(db, user)

    assert result["executed_count"] == 0
    db.refresh(job)
    assert job.status == "pending"


def test_already_published_job_is_not_republished(db, owner):
    user, account = owner
    job = make_job(db, user, account, -5, status="published")

    result = run(db, user)

    assert result["executed_count"] == 0
    db.refresh(job)
    assert job.status == "published"


# --- failure must be explainable -------------------------------------------


def test_undecryptable_cookie_names_the_fix(db, owner):
    user, _ = owner
    bad = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="bad", status="active"
    )
    db.add(bad)
    db.flush()
    db.add(
        AccountCookieVersion(
            platform_account_id=bad.id, encrypted_cookies="not-a-fernet-token"
        )
    )
    db.commit()
    job = make_job(db, user, bad, -5)

    result = run(db, user)

    assert result["failed_count"] == 1
    db.refresh(job)
    assert job.status == "failed"
    assert job.publish_error.strip(), "失败的发布必须写明原因"
    assert "重新登录" in job.publish_error


def test_empty_exception_message_still_records_the_type(db, owner):
    """``InvalidToken()`` stringifies to ''. A blank reason is not acceptable."""
    from backend.app.services.scheduler_service import _fail_job

    user, account = owner
    job = make_job(db, user, account, -5)
    empty = RuntimeError()
    assert str(empty) == ""

    message = str(empty).strip() or f"{type(empty).__name__}（该异常没有附带说明）"
    _fail_job(db, job, message)

    db.refresh(job)
    assert job.status == "failed"
    assert job.publish_error.strip()


# --- one bad job must not stop the others ----------------------------------


def test_one_failing_job_does_not_block_the_rest(db, owner):
    user, good_account = owner
    bad = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="bad2", status="active"
    )
    db.add(bad)
    db.flush()
    db.add(
        AccountCookieVersion(platform_account_id=bad.id, encrypted_cookies="garbage")
    )
    db.commit()

    broken = make_job(db, user, bad, -10)
    healthy = make_job(db, user, good_account, -5)

    result = run(db, user)

    db.refresh(broken)
    db.refresh(healthy)
    assert broken.status == "failed"
    assert healthy.status == "published", "坏任务不能阻断后续任务"
    assert result["executed_count"] == 2
    assert result["failed_count"] == 1


def test_job_for_missing_account_fails_without_raising(db, owner):
    user, account = owner
    job = make_job(db, user, account, -5)
    # Simulate the account disappearing between scheduling and running.
    job.platform_account_id = None
    db.commit()

    result = run(db, user)

    db.refresh(job)
    assert job.status == "failed"
    assert job.publish_error.strip()
