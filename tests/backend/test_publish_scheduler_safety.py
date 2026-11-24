"""Scheduled publish safety: time normalization, asset upload, risk gates."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import to_shanghai_naive
from backend.app.models import (
    AccountCookieVersion,
    AiDraft,
    AutoTask,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    Task,
    User,
)
from backend.app.services.publish_asset_service import upload_pending_assets
from backend.app.services.scheduler_service import _execute_auto_task_background


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scheduler.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


class FakeAdapter:
    def __init__(self):
        self.uploaded: list[tuple[str, str]] = []

    def upload_media(self, file_path: str, asset_type: str):
        self.uploaded.append((file_path, asset_type))
        return {"fileIds": "media-1"}


def test_aware_utc_is_normalized_to_shanghai_wall_clock():
    value = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)

    assert to_shanghai_naive(value) == datetime(2026, 10, 24, 10, 0)


def test_naive_datetime_is_treated_as_shanghai():
    value = datetime(2026, 10, 24, 10, 0)

    assert to_shanghai_naive(value) == value


def test_upload_pending_assets_marks_uploaded(tmp_path):
    db = _session(tmp_path)
    try:
        asset = PublishAsset(
            publish_job_id=1,
            asset_type="image",
            file_path="/api/files/media/demo.jpg",
            upload_status="pending",
        )
        db.add(asset)
        db.commit()
        adapter = FakeAdapter()

        upload_pending_assets(db, adapter, [asset])

        assert adapter.uploaded == [("/api/files/media/demo.jpg", "image")]
        assert asset.upload_status == "uploaded"
        assert asset.creator_media_id == "media-1"
    finally:
        db.close()


def test_upload_pending_assets_skips_video(tmp_path):
    db = _session(tmp_path)
    try:
        asset = PublishAsset(
            publish_job_id=1,
            asset_type="video",
            file_path="/api/files/media/demo.mp4",
            upload_status="pending",
        )
        db.add(asset)
        db.commit()
        adapter = FakeAdapter()

        upload_pending_assets(db, adapter, [asset])

        assert adapter.uploaded == []
        assert asset.upload_status == "pending"
    finally:
        db.close()


def test_background_auto_task_does_nothing_when_risk_controls_are_off(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="auto-user", password_hash="x")
        db.add(user)
        db.flush()
        task = AutoTask(
            user_id=user.id,
            name="risk-off",
            keywords=["早餐"],
            pc_account_id=1,
            creator_account_id=2,
            schedule_type="interval",
            status="active",
        )
        db.add(task)
        db.commit()

        _execute_auto_task_background(db, task)
        db.refresh(task)

        assert task.last_run_at is not None
        assert db.scalars(select(AiDraft)).all() == []
        assert db.scalars(select(PublishJob)).all() == []
    finally:
        db.close()


def test_auto_task_publish_uses_the_shared_pipeline(tmp_path, monkeypatch):
    db = _session(tmp_path)
    try:
        user = User(username="auto-publisher", password_hash="x")
        db.add(user)
        db.flush()
        pc = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="pc",
            status="active",
        )
        creator = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="creator",
            nickname="creator",
            status="active",
        )
        db.add_all([pc, creator])
        db.flush()
        for account in (pc, creator):
            db.add(
                AccountCookieVersion(
                    platform_account_id=account.id,
                    encrypted_cookies=encrypt_text("a1=test; web_session=session"),
                )
            )
        task = AutoTask(
            user_id=user.id,
            name="publish-through-service",
            keywords=["早餐"],
            pc_account_id=pc.id,
            creator_account_id=creator.id,
            schedule_type="interval",
            status="active",
        )
        db.add(task)
        db.commit()

        controls = SimpleNamespace(
            auto_ops_enabled=True,
            competitor_rewrite_enabled=True,
            copy_source_images_enabled=True,
            auto_create_publish_job_enabled=True,
            auto_publish_enabled=True,
        )
        monkeypatch.setattr(
            "backend.app.services.scheduler_service.get_risk_controls",
            lambda *args, **kwargs: controls,
        )
        cookies = "a1=test; web_session=session"
        monkeypatch.setattr(
            "backend.app.services.account_cookies.latest_cookies",
            lambda *args, **kwargs: cookies,
        )
        monkeypatch.setattr(
            "backend.app.services.publish_service.latest_cookies",
            lambda *args, **kwargs: cookies,
        )
        monkeypatch.setattr(
            "backend.app.adapters.xhs.pc_api_adapter.XhsPcApiAdapter.search_note",
            lambda self, keyword, page=1: (True, "", {}),
        )
        monkeypatch.setattr(
            "backend.app.api.platforms.xhs.crawl._data_items",
            lambda raw: [{}],
        )
        monkeypatch.setattr(
            "backend.app.api.platforms.xhs.pc._normalize_search_item",
            lambda item: {
                "title": "早餐灵感",
                "content": "这是一段足够长的自动任务正文，用来通过发布前的正文长度检查。",
                "likes": 10,
                "collects": 5,
                "comments": 2,
                "shares": 1,
                "image_urls": ["https://example.com/source.png"],
            },
        )
        monkeypatch.setattr(
            "backend.app.services.scheduler_service._get_text_model_for_user",
            lambda db, user_id: (None, ""),
        )
        monkeypatch.setattr(
            "backend.app.services.auto_publish_guard.auto_publish_block_reason",
            lambda *args, **kwargs: "",
        )
        monkeypatch.setattr(
            "backend.app.adapters.xhs.creator_api_adapter.XhsCreatorApiAdapter.upload_media",
            lambda self, path, kind: {"fileIds": ["file-1"]},
        )
        monkeypatch.setattr(
            "backend.app.adapters.xhs.creator_api_adapter.XhsCreatorApiAdapter.post_note",
            lambda self, note_info: {"note_id": "auto-note-1"},
        )
        monkeypatch.setattr(
            "backend.app.services.publish_feedback_service.save_published_note",
            lambda *args, **kwargs: SimpleNamespace(id=7),
        )

        _execute_auto_task_background(db, task)

        db.refresh(task)
        job = db.scalars(select(PublishJob)).one()
        asset = db.scalars(select(PublishAsset)).one()
        publish_task = db.scalars(
            select(Task).where(Task.task_type == "creator_publish_auto")
        ).one()
        assert job.status == "published"
        assert job.external_note_id == "auto-note-1"
        assert asset.upload_status == "uploaded"
        assert asset.file_path == "https://example.com/source.png"
        assert publish_task.status == "completed"
        assert publish_task.payload["auto_task_id"] == task.id
        assert task.total_published == 1
        assert task.last_run_at is not None
    finally:
        db.close()
