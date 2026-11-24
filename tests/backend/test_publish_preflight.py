"""Server-side publish preflight checks (no network)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.app.models  # noqa: F401
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
from backend.app.services.publish_preflight_service import preflight_publish_job


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="preflight-user", password_hash="x")
    session.add(user)
    session.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="creator",
        nickname="测试账号",
        status="active",
    )
    session.add(account)
    session.flush()
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text('{"web_session":"x"}'),
        )
    )
    session.commit()
    session.refresh(user)
    session.refresh(account)
    try:
        yield session, user, account
    finally:
        session.close()


def _job(session, user, account, *, title="早餐 3 个 5 分钟方案", body="正文" * 30, scheduled=None):
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title=title,
        body=body,
        publish_mode="scheduled" if scheduled else "immediate",
        publish_options='{"topics":["早餐","打工人","通勤"]}',
        scheduled_at=scheduled,
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_preflight_blocks_missing_assets(db):
    session, user, account = db
    job = _job(session, user, account)

    result = preflight_publish_job(session, user, job)

    assert result["ok"] is False
    assert any(item["key"] == "assets" for item in result["errors"])


def test_preflight_blocks_mixed_media(db):
    session, user, account = db
    job = _job(session, user, account)
    session.add(PublishAsset(publish_job_id=job.id, asset_type="image", file_path="https://example.com/a.jpg"))
    session.add(PublishAsset(publish_job_id=job.id, asset_type="video", file_path="https://example.com/a.mp4"))
    session.commit()

    result = preflight_publish_job(session, user, job)

    assert result["ok"] is False
    assert any(item["key"] == "assets_mixed" for item in result["errors"])


def test_preflight_warns_about_sensitive_words(db):
    session, user, account = db
    job = _job(session, user, account, title="全网最好的早餐方案")
    session.add(PublishAsset(publish_job_id=job.id, asset_type="image", file_path="https://example.com/a.jpg"))
    session.commit()

    result = preflight_publish_job(session, user, job)

    assert result["ok"] is True
    assert any(item["key"] == "sensitive" for item in result["warnings"])


def test_preflight_passes_valid_job(db):
    session, user, account = db
    job = _job(
        session,
        user,
        account,
        scheduled=shanghai_now() + timedelta(days=1),
    )
    session.add(PublishAsset(publish_job_id=job.id, asset_type="image", file_path="https://example.com/a.jpg"))
    session.commit()

    result = preflight_publish_job(session, user, job)

    assert result["ok"] is True
    assert result["error_count"] == 0
