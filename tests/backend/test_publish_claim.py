from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AiDraft, PublishJob, User
from backend.app.api.drafts import _find_active_publish_job_for_draft
from backend.app.services.publish_claim_service import claim_publish_job


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'claim.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_claim_publish_job_allows_exactly_one_winner(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="claim-user", password_hash="x")
        db.add(user)
        db.flush()
        job = PublishJob(user_id=user.id, platform="xhs", status="pending")
        db.add(job)
        db.commit()

        assert claim_publish_job(db, job.id, "pending") is True
        assert claim_publish_job(db, job.id, "pending") is False

        db.refresh(job)
        assert job.status == "publishing"
    finally:
        db.close()


def test_active_publish_job_is_reused_for_same_draft(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="reuse-user", password_hash="x")
        db.add(user)
        db.flush()
        draft = AiDraft(user_id=user.id, platform="xhs", title="t", body="b")
        db.add(draft)
        db.flush()
        job = PublishJob(
            user_id=user.id,
            source_draft_id=draft.id,
            platform="xhs",
            status="pending",
        )
        db.add(job)
        db.commit()

        assert _find_active_publish_job_for_draft(db, user.id, draft.id).id == job.id

        job.status = "cancelled"
        db.commit()
        assert _find_active_publish_job_for_draft(db, user.id, draft.id) is None
    finally:
        db.close()
