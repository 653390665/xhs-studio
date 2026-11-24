"""API coverage for the P1 next-step flow: topic schedule + draft visual brief."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import (
    AiDraft,
    DraftAsset,
    DraftChatMessage,
    DraftVersion,
    TopicIdea,
    User,
)

client = TestClient(app)


def test_topic_schedule_and_visual_brief_api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'next-step.db'}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "next-step-user", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        db = TestingSessionLocal()
        try:
            user = db.scalars(select(User).where(User.username == "next-step-user")).one()
            topic = TopicIdea(
                user_id=user.id,
                title="排期 API 选题",
                type="pain",
                type_label="痛点型",
                growth_task="拉新",
                status="new",
            )
            draft = AiDraft(
                user_id=user.id,
                platform="xhs",
                title="视觉简报 API 草稿",
                body="这是一篇用于验证视觉简报接口的草稿正文。",
                origin="manual",
            )
            db.add_all([topic, draft])
            db.commit()
            topic_id = topic.id
            draft_id = draft.id
            db.add_all(
                [
                    DraftAsset(
                        draft_id=draft.id,
                        asset_type="image",
                        url="https://example.test/cover.jpg",
                    ),
                    DraftChatMessage(
                        user_id=user.id,
                        draft_id=draft.id,
                        role="user",
                        content="把标题改短一点",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        scheduled = client.patch(
            f"/api/xhs/topics/{topic_id}/schedule",
            json={"scheduled_for": "2026-11-02T10:00:00+08:00"},
            headers=headers,
        )
        assert scheduled.status_code == 200
        assert scheduled.json()["scheduled_for"] == "2026-11-02T10:00:00"
        assert scheduled.json()["status"] == "new"

        listed = client.get("/api/xhs/topics", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["scheduled_for"] == "2026-11-02T10:00:00"

        brief = client.post(
            f"/api/drafts/{draft_id}/visual-brief",
            json={"style": ""},
            headers=headers,
        )
        assert brief.status_code == 200
        payload = brief.json()
        assert payload["draft_id"] == draft_id
        assert payload["cover"]["ratio"] == "3:4"
        assert payload["cover"]["prompt"]
        assert payload["illustration"]["ratio"] == "16:9"
        assert payload["sequence"]

        cleared = client.patch(
            f"/api/xhs/topics/{topic_id}/schedule",
            json={"scheduled_for": None},
            headers=headers,
        )
        assert cleared.status_code == 200
        assert cleared.json()["scheduled_for"] is None

        updated = client.patch(
            f"/api/drafts/{draft_id}",
            json={"title": "视觉简报 API 草稿（已编辑）"},
            headers=headers,
        )
        assert updated.status_code == 200

        deleted = client.delete(f"/api/drafts/{draft_id}", headers=headers)
        assert deleted.status_code == 200
        assert client.get("/api/drafts", headers=headers).json()["total"] == 0

        db = TestingSessionLocal()
        try:
            assert db.scalars(select(DraftVersion)).all() == []
            assert db.scalars(select(DraftAsset)).all() == []
            assert db.scalars(select(DraftChatMessage)).all() == []
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)
