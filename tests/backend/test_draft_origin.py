"""A draft created from a topic must stay traceable to that topic.

Before this, every generator wrote origin="agent", so the draft queue could not
tell "选题转草稿" apart from "对话生成", and the topic was never marked used —
risking duplicate drafts from the same topic.
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AiDraft, ModelConfig, PlatformAccount, TopicIdea, User
from backend.app.services.agent_service import _generate_draft


class _FakeClient:
    """Returns a fixed note body; no network."""

    def generate_note(self, **kwargs):
        return {"title": "选题生成的标题", "body": "正文内容", "tags": ["标签"]}


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'topic_draft.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_topic_draft_keeps_origin_and_marks_topic_used(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="topic-draft", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id, platform="xhs", sub_type="pc", nickname="号", status="active"
        )
        db.add(account)
        db.flush()
        topic = TopicIdea(
            user_id=user.id,
            platform_account_id=account.id,
            title="一人公司接单",
            type="pain",
            type_label="痛点型",
            growth_task="拉新",
            status="new",
        )
        db.add(topic)
        db.flush()
        model = ModelConfig(
            user_id=user.id,
            name="m",
            model_type="text",
            provider="openai-compatible",
            model_name="x",
            base_url="http://x",
            is_default=True,
        )
        db.add(model)
        db.commit()

        result = _generate_draft(
            db,
            user,
            {
                "topic": topic.title,
                "topic_id": topic.id,
                "account_id": account.id,
            },
            _FakeClient(),
            model,
            "key",
            account.id,
        )

        draft = db.get(AiDraft, result["draft_id"])
        assert draft.origin == "topic", "选题转草稿必须有自己的来源标记"
        assert draft.topic_id == topic.id

        db.refresh(topic)
        assert topic.status == "used", "同一选题不应被反复生成"
    finally:
        db.close()


def test_plain_agent_draft_keeps_agent_origin(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="agent-draft", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id, platform="xhs", sub_type="pc", nickname="号", status="active"
        )
        db.add(account)
        db.flush()
        model = ModelConfig(
            user_id=user.id,
            name="m",
            model_type="text",
            provider="openai-compatible",
            model_name="x",
            base_url="http://x",
            is_default=True,
        )
        db.add(model)
        db.commit()

        result = _generate_draft(
            db,
            user,
            {"topic": "随手写一篇", "account_id": account.id},
            _FakeClient(),
            model,
            "key",
            account.id,
        )

        draft = db.get(AiDraft, result["draft_id"])
        assert draft.origin == "agent"
        assert draft.topic_id is None
    finally:
        db.close()
