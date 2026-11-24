"""Auto-publish caps and Creator metrics fallback."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import Note, PublishJob, User
from backend.app.services.auto_publish_guard import (
    AUTO_PUBLISH_DAILY_LIMIT,
    AUTO_PUBLISH_MIN_INTERVAL_MINUTES,
    auto_publish_block_reason,
)
from backend.app.services.note_metrics_refresh_service import refresh_one_note


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'guard.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _job(user_id: int, account_id: int, published_at) -> PublishJob:
    return PublishJob(
        user_id=user_id,
        platform_account_id=account_id,
        platform="xhs",
        title="t",
        body="b",
        status="published",
        published_at=published_at,
        created_at=published_at,
    )


def test_auto_publish_daily_limit(tmp_path):
    db = _session(tmp_path)
    try:
        now = datetime(2026, 10, 24, 12, 0)
        for index in range(AUTO_PUBLISH_DAILY_LIMIT):
            db.add(_job(1, 10, now - timedelta(minutes=120 + index)))
        db.commit()

        reason = auto_publish_block_reason(db, 1, 10, now=now)

        assert reason is not None
        assert "上限" in reason
    finally:
        db.close()


def test_auto_publish_min_interval(tmp_path):
    db = _session(tmp_path)
    try:
        now = datetime(2026, 10, 24, 12, 0)
        db.add(_job(1, 10, now - timedelta(minutes=AUTO_PUBLISH_MIN_INTERVAL_MINUTES - 10)))
        db.commit()

        reason = auto_publish_block_reason(db, 1, 10, now=now)

        assert reason is not None
        assert "分钟" in reason
    finally:
        db.close()


def test_auto_publish_allows_when_no_recent_jobs(tmp_path):
    db = _session(tmp_path)
    try:
        now = shanghai_now()
        db.add(_job(1, 10, now - timedelta(days=1)))
        db.commit()

        assert auto_publish_block_reason(db, 1, 10, now=now) is None
    finally:
        db.close()


def test_creator_note_without_pc_account_advances_timestamp(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="creator-only", password_hash="x")
        db.add(user)
        db.flush()
        note = Note(
            user_id=user.id,
            platform_account_id=1,
            platform="xhs",
            note_id="creator-note-1",
            title="自己的笔记",
            content="正文",
            source_type="creator",
        )
        db.add(note)
        db.commit()

        refreshed = refresh_one_note(db, user, note)
        db.commit()

        assert refreshed.metrics_fetched_at is not None
        assert "PC" in (refreshed.raw_json or {}).get("metrics_error", "")
    finally:
        db.close()
