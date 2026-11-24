"""The shared publish pipeline: manual, scheduler, and auto must agree.

Each caller keeps its own state semantics, but upload/options/preflight/post
must be the same code. These tests pin the differences that are intentional and
the shared behavior that is not.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now, shanghai_timestamp_ms
from backend.app.models import (
    AccountCookieVersion,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    Task,
    User,
)
from backend.app.services.publish_service import (
    PublishService,
    PublishUploadError,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'publish-service.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def owner(db):
    user = User(username="publish-service-user", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="creator",
        nickname="creator",
        status="active",
    )
    db.add(account)
    db.flush()
    db.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text("a1=test; web_session=session"),
        )
    )
    db.commit()
    return user, account


class RecordingAdapter:
    instances: list["RecordingAdapter"] = []

    def __init__(self, cookies: str):
        self.cookies = cookies
        self.uploaded: list[tuple[str, str]] = []
        self.posted: list[dict] = []
        RecordingAdapter.instances.append(self)

    def upload_media(self, file_path: str, asset_type: str):
        self.uploaded.append((file_path, asset_type))
        return {"fileIds": ["file-1"], "creator_media_id": "media-1"}

    def post_note(self, note_info: dict):
        self.posted.append(note_info)
        return {"note_id": "external-note-1"}

    def resolve_media_bytes(self, file_path: str):
        return b"video"


def make_job(db, user, account, *, status="pending", publish_mode="immediate", scheduled_at=None):
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title="测试标题",
        body="这是一段足够长的正文，用来通过发布前的长度检查，并且不会触发短正文提醒。",
        publish_mode=publish_mode,
        status=status,
        scheduled_at=scheduled_at,
        publish_options='{"topics":["测试"],"privacy_type":1}',
    )
    db.add(job)
    db.flush()
    db.add(
        PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="https://example.com/cover.png",
            upload_status="uploaded",
            creator_media_id="media-1",
            creator_upload_info='{"fileIds":["file-1"]}',
        )
    )
    db.commit()
    db.refresh(job)
    return job


def test_manual_schedule_passes_post_time_and_keeps_scheduled_status(db, owner, monkeypatch):
    user, account = owner
    scheduled_at = shanghai_now() + timedelta(hours=2)
    job = make_job(
        db,
        user,
        account,
        publish_mode="scheduled",
        scheduled_at=scheduled_at,
    )
    feedback_calls = []
    monkeypatch.setattr(
        "backend.app.services.publish_feedback_service.save_published_note",
        lambda *args, **kwargs: feedback_calls.append((args, kwargs)),
    )
    RecordingAdapter.instances = []

    outcome = PublishService(db, user, RecordingAdapter).publish(
        job,
        task_type="creator_publish",
        platform_post_time=True,
        enforce_future_schedule=True,
        claim_before_media=False,
        mark_failed_before_post=False,
    )

    adapter = RecordingAdapter.instances[0]
    assert outcome.job.status == "scheduled"
    assert adapter.posted[0]["postTime"] == shanghai_timestamp_ms(
        scheduled_at.replace(tzinfo=None)
    )
    assert adapter.posted[0]["topics"] == ["测试"]
    assert adapter.posted[0]["type"] == 1
    asset_id = db.scalars(
        select(PublishAsset.id).where(PublishAsset.publish_job_id == job.id)
    ).one()
    assert feedback_calls == [], "平台侧定时任务此时还没有真正发布"
    assert outcome.task is not None and outcome.task.status == "completed"
    assert outcome.task.payload["asset_ids"] == [asset_id]


def test_local_schedule_publishes_now_and_writes_feedback(db, owner, monkeypatch):
    user, account = owner
    job = make_job(
        db,
        user,
        account,
        publish_mode="scheduled",
        scheduled_at=shanghai_now() - timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "backend.app.services.publish_feedback_service.save_published_note",
        lambda *args, **kwargs: SimpleNamespace(id=99),
    )
    RecordingAdapter.instances = []

    outcome = PublishService(db, user, RecordingAdapter).publish(
        job,
        task_type="creator_publish_scheduler",
        platform_post_time=False,
        enforce_future_schedule=False,
        claim_before_media=True,
        mark_failed_before_post=True,
    )

    adapter = RecordingAdapter.instances[0]
    assert outcome.job.status == "published"
    assert adapter.posted[0]["postTime"] is None
    assert outcome.library_note_id == 99
    assert outcome.task is not None
    assert outcome.task.payload["library_note_id"] == 99


class FailingUploadAdapter(RecordingAdapter):
    def upload_media(self, file_path: str, asset_type: str):
        raise RuntimeError("upload denied")


def test_pending_asset_is_uploaded_once_before_post(db, owner):
    user, account = owner
    job = _make_pending_asset_job(db, user, account)
    RecordingAdapter.instances = []

    outcome = PublishService(db, user, RecordingAdapter).publish(
        job,
        task_type="creator_publish_scheduler",
        platform_post_time=False,
        enforce_future_schedule=False,
        claim_before_media=True,
        mark_failed_before_post=True,
    )

    adapter = RecordingAdapter.instances[0]
    asset = db.scalars(
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id)
    ).one()
    assert adapter.uploaded == [("https://example.com/cover.png", "image")]
    assert asset.upload_status == "uploaded"
    assert asset.creator_upload_info == '{"fileIds": ["file-1"], "creator_media_id": "media-1"}'
    assert adapter.posted[0]["image_file_infos"][0]["fileIds"] == ["file-1"]
    assert outcome.job.status == "published"


def _make_pending_asset_job(db, user, account):
    job = make_job(db, user, account)
    asset = db.scalars(
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id)
    ).one()
    asset.upload_status = "pending"
    asset.creator_upload_info = "{}"
    db.commit()
    return job


def test_manual_upload_failure_leaves_job_pending(db, owner):
    user, account = owner
    job = _make_pending_asset_job(db, user, account)
    RecordingAdapter.instances = []

    with pytest.raises(PublishUploadError):
        PublishService(db, user, FailingUploadAdapter).publish(
            job,
            task_type="creator_publish",
            platform_post_time=True,
            enforce_future_schedule=True,
            claim_before_media=False,
            mark_failed_before_post=False,
        )

    db.refresh(job)
    assert job.status == "pending"
    assert job.publish_error == ""
    assert db.scalars(select(Task)).all() == []


def test_unattended_upload_failure_marks_job_and_task_failed(db, owner):
    user, account = owner
    job = _make_pending_asset_job(db, user, account)

    with pytest.raises(PublishUploadError):
        PublishService(db, user, FailingUploadAdapter).publish(
            job,
            task_type="creator_publish_auto",
            platform_post_time=False,
            enforce_future_schedule=False,
            claim_before_media=True,
            mark_failed_before_post=True,
        )

    db.refresh(job)
    assert job.status == "failed"
    assert "素材上传失败" in job.publish_error
    task = db.scalars(select(Task)).one()
    assert task.status == "failed"
    assert task.progress == 100
    assert "素材上传失败" in task.payload["error"]
