"""Publish feedback: a published job must appear in the content library."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import AgentMemory, Note, NoteAsset, PlatformAccount, PublishAsset, PublishJob, User
from backend.app.services.publish_feedback_service import save_published_note


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'publish-feedback.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _fixture(db, *, external_note_id: str = "note-abc"):
    user = User(username="feedback-user", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="creator",
        external_user_id="author-1",
        nickname="阿桑",
        profile_json='{"fans": 3200}',
    )
    db.add(account)
    db.flush()
    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        title="发布标题",
        body="发布正文",
        status="published",
        external_note_id=external_note_id,
        published_at=shanghai_now(),
    )
    db.add(job)
    db.flush()
    db.add(
        PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="/api/files/media/card-01.png",
        )
    )
    db.add(
        PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="https://cdn.example.com/card-02.png",
        )
    )
    db.commit()
    return user, account, job


def test_published_job_is_saved_into_library(tmp_path):
    db = _session(tmp_path)
    try:
        user, account, job = _fixture(db)

        note = save_published_note(db, job, account)
        db.commit()

        assert note is not None
        assert note.user_id == user.id
        assert note.note_id == "note-abc"
        assert note.title == "发布标题"
        assert note.author_name == "阿桑"
        assert note.author_fans == 3200
        assert note.raw_json["origin"] == "publish"
        assert note.raw_json["publish_job_id"] == job.id
        assert note.raw_json["note_url"] == "https://www.xiaohongshu.com/explore/note-abc"

        assets = db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id)).all()
        assert len(assets) == 2
        assert {asset.local_path for asset in assets} == {"card-01.png", ""}
        assert any(asset.url == "https://cdn.example.com/card-02.png" for asset in assets)
    finally:
        db.close()


def test_publish_feedback_is_idempotent(tmp_path):
    db = _session(tmp_path)
    try:
        _user, account, job = _fixture(db)

        first = save_published_note(db, job, account)
        db.commit()
        second = save_published_note(db, job, account)
        db.commit()

        assert first is not None and second is not None
        assert first.id == second.id
        assert len(db.scalars(select(Note)).all()) == 1
        assert len(db.scalars(select(NoteAsset).where(NoteAsset.note_id == first.id)).all()) == 2
    finally:
        db.close()


def test_publish_feedback_skips_jobs_without_note_id(tmp_path):
    db = _session(tmp_path)
    try:
        _user, account, job = _fixture(db, external_note_id="")

        assert save_published_note(db, job, account) is None
        db.commit()
        assert db.scalars(select(Note)).all() == []
    finally:
        db.close()


def test_publish_feedback_updates_existing_note_and_appends_new_assets(tmp_path):
    db = _session(tmp_path)
    try:
        _user, account, job = _fixture(db)
        save_published_note(db, job, account)
        db.commit()

        job.title = "改过的标题"
        job.body = "改过的正文"
        db.add(
            PublishAsset(
                publish_job_id=job.id,
                asset_type="image",
                file_path="/api/files/media/card-03.png",
            )
        )
        db.commit()

        note = save_published_note(db, job, account)
        db.commit()

        assert note.title == "改过的标题"
        assert note.content == "改过的正文"
        assets = db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id)).all()
        assert len(assets) == 3
        assert {asset.local_path for asset in assets} == {"card-01.png", "", "card-03.png"}
    finally:
        db.close()


def test_publish_feedback_writes_performance_memory(tmp_path):
    db = _session(tmp_path)
    try:
        _user, account, job = _fixture(db)

        save_published_note(db, job, account)
        db.commit()

        memory = db.scalars(select(AgentMemory).where(AgentMemory.kind == "performance")).one()
        assert memory.key == f"note:{job.external_note_id}"
        assert memory.platform_account_id == account.id
        assert memory.value["title"] == "发布标题"
        assert memory.value["job_id"] == job.id
        assert memory.value["likes"] == 0
    finally:
        db.close()
