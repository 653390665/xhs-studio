"""Draft origin, matrix similarity gate and loop metrics."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.drafts import _serialize_draft
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import AiDraft, Note, PublishJob, User
from backend.app.services.loop_metrics_service import compute_loop_metrics
from backend.app.services.publish_preflight_service import preflight_publish_job


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'attribution.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_draft_serialization_exposes_origin_and_skill():
    draft = AiDraft(
        id=1,
        user_id=1,
        platform="xhs",
        title="标题",
        body="正文",
        origin="matrix",
        pipeline_id="p1",
        skill_version="v0.3",
        review_status="pending",
        created_at=shanghai_now(),
    )

    payload = _serialize_draft(draft)

    assert payload["origin"] == "matrix"
    assert payload["pipeline_id"] == "p1"
    assert payload["skill_version"] == "v0.3"


def test_matrix_similarity_blocks_publish_preflight(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="matrix-user", password_hash="x")
        db.add(user)
        db.flush()
        first = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="A",
            body="完全相同的正文，用来验证矩阵查重。" * 5,
            origin="matrix",
            pipeline_id="matrix-run-1",
        )
        second = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="B",
            body=first.body,
            origin="matrix",
            pipeline_id="matrix-run-1",
        )
        db.add_all([first, second])
        db.flush()
        job = PublishJob(
            user_id=user.id,
            platform="xhs",
            title=first.title,
            body=first.body,
            source_draft_id=first.id,
            publish_mode="immediate",
        )
        db.add(job)
        db.commit()

        result = preflight_publish_job(db, user, job, enforce_future_schedule=False)

        checks = {item["key"]: item for item in result["checks"]}
        assert checks["matrix_similarity"]["level"] == "error"
    finally:
        db.close()


def test_loop_metrics_counts_origins_and_success_rate(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="loop-user", password_hash="x")
        db.add(user)
        db.flush()
        db.add_all(
            [
                AiDraft(user_id=user.id, platform="xhs", title="1", body="a", origin="manual"),
                AiDraft(user_id=user.id, platform="xhs", title="2", body="b", origin="ai", skill_version="v1"),
                AiDraft(user_id=user.id, platform="xhs", title="3", body="c", origin="matrix"),
            ]
        )
        db.add_all(
            [
                PublishJob(
                    user_id=user.id,
                    platform="xhs",
                    title="ok",
                    body="a",
                    status="published",
                    skill_version="v1",
                    pillar="一人公司",
                    published_at=shanghai_now(),
                ),
                PublishJob(user_id=user.id, platform="xhs", title="bad", body="b", status="failed"),
            ]
        )
        db.add(
            Note(
                user_id=user.id,
                platform_account_id=1,
                platform="xhs",
                note_id="own-1",
                title="我的笔记",
                content="x",
                source_type="creator",
                metrics_fetched_at=shanghai_now(),
            )
        )
        db.commit()

        metrics = compute_loop_metrics(db, user, days=7)

        assert metrics["drafts_created"] == 3
        assert metrics["jobs_created"] == 2
        assert metrics["jobs_published"] == 1
        assert metrics["jobs_failed"] == 1
        assert metrics["publish_success_rate"] == 50.0
        assert metrics["refresh_rate"] == 100.0
        assert dict((item["origin"], item["count"]) for item in metrics["by_origin"]) == {
            "manual": 1,
            "ai": 1,
            "matrix": 1,
        }
        assert metrics["by_skill_version"] == [{"version": "v1", "count": 1}]
        assert metrics["by_pillar"] == [{"pillar": "一人公司", "count": 1}]

        scoped = compute_loop_metrics(db, user, days=7, account_id=2)
        assert scoped["drafts_created"] == 0
        assert scoped["jobs_created"] == 0
        assert scoped["own_notes"] == 0
    finally:
        db.close()
