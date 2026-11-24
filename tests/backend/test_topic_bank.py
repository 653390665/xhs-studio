"""Seven-type topic bank: model path, template fallback, grouping fields."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, ModelConfig, PlatformAccount, User
from backend.app.services.topic_bank_service import (
    TOPIC_TYPES,
    generate_topic_bank,
    list_saved_topics,
    save_topics,
    serialize_topic,
    update_topic_schedule,
    update_topic_status,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'topics.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    user = User(username="topic-user", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="选题账号",
        status="active",
    )
    db.add(account)
    db.flush()
    # 画像表已作废：内容支柱改由创作 Skill 提供。
    db.add(
        StyleProfile(
            user_id=user.id,
                        account_id=account.id,
            name="选题账号 Skill",
            
            status="applied",
            skill_md=(
                "# 选题账号 Skill\n\n## 2. 内容支柱\n\n"
                "| 支柱 | 说明 |\n|---|---|\n"
                "| **A. 获客** | 独立顾问怎么找到客户 |\n"
                "| **B. 交付** | 接单后的交付流程 |\n"
                "| **C. 定价** | 报价与议价 |\n\n"
                "## 8. 禁区\n- 不承诺收益\n"
            ),
        )
    )
    db.commit()
    return db, user, account


class FakeClient:
    def complete(self, **kwargs):
        return json.dumps(
            {
                "topics": [
                    {
                        "title": "独立顾问获客，别先做名片",
                        "type": "counter",
                        "growth_task": "拉新",
                        "need": "获得新知",
                        "why": "挑战默认做法，适合做系列开篇",
                    },
                    {
                        "title": "3 个获客动作，我用了半年",
                        "type": "number",
                        "growth_task": "建立信任",
                        "need": "学习提升",
                        "why": "有数字和真实使用周期",
                    },
                ]
            },
            ensure_ascii=False,
        )


def test_topic_bank_falls_back_to_seven_types_without_model(tmp_path):
    db, user, account = _session(tmp_path)
    try:
        result = generate_topic_bank(
            db, user, account_id=account.id, theme="获客", per_type=2, use_llm=False
        )
        assert result["engine"] == "template"
        assert result["count"] == len(TOPIC_TYPES) * 2
        assert {item["type"] for item in result["items"]} == {item["key"] for item in TOPIC_TYPES}
        assert all(item["growth_task"] in {"拉新", "建立信任", "强化标签"} for item in result["items"])
        assert all(item["title"] for item in result["items"])
    finally:
        db.close()


def test_topic_bank_uses_model_and_validates_types(tmp_path):
    db, user, account = _session(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="fake",
                model_type="text",
                provider="openai",
                model_name="fake",
                is_default=True,
            )
        )
        db.commit()
        result = generate_topic_bank(
            db,
            user,
            account_id=account.id,
            theme="获客",
            per_type=2,
            use_llm=True,
            client=FakeClient(),
        )
        assert result["engine"] == "model"
        assert result["count"] == 2
        assert {item["type"] for item in result["items"]} == {"counter", "number"}
        assert result["items"][0]["type_label"]
    finally:
        db.close()


def test_topic_bank_falls_back_when_model_returns_bad_json(tmp_path):
    db, user, account = _session(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="fake",
                model_type="text",
                provider="openai",
                model_name="fake",
                is_default=True,
            )
        )
        db.commit()

        class BadClient:
            def complete(self, **kwargs):
                return "not json"

        result = generate_topic_bank(
            db,
            user,
            account_id=account.id,
            theme="获客",
            per_type=1,
            use_llm=True,
            client=BadClient(),
        )
        assert result["engine"] == "template"
        assert result["count"] == len(TOPIC_TYPES)
    finally:
        db.close()


def test_save_topics_dedupes_and_updates_status(tmp_path):
    db, user, account = _session(tmp_path)
    try:
        items = [
            {"title": "选题 A", "type": "pain", "type_label": "痛点型", "growth_task": "拉新"},
            {"title": "选题 B", "type": "number", "type_label": "数字型", "growth_task": "建立信任"},
            {"title": "选题 A", "type": "pain", "type_label": "痛点型", "growth_task": "拉新"},
        ]
        first = save_topics(db, user, account_id=account.id, items=items)
        assert first == {"saved": 2, "skipped": 1}

        second = save_topics(db, user, account_id=account.id, items=items)
        assert second == {"saved": 0, "skipped": 3}

        rows = list_saved_topics(db, user, account_id=account.id)
        assert {row.title for row in rows} == {"选题 A", "选题 B"}

        updated = update_topic_status(db, user, rows[0].id, "used")
        assert updated.status == "used"
        assert list_saved_topics(db, user, account_id=account.id, status="used")
    finally:
        db.close()


def test_topic_schedule_roundtrip_and_serialization(tmp_path):
    db, user, account = _session(tmp_path)
    try:
        save_topics(
            db,
            user,
            account_id=account.id,
            items=[
                {"title": "排期选题 A", "type": "pain", "type_label": "痛点型", "growth_task": "拉新"}
            ],
        )
        topic = list_saved_topics(db, user, account_id=account.id)[0]
        assert topic.scheduled_for is None
        assert serialize_topic(topic)["scheduled_for"] is None

        planned = datetime(2026, 11, 2, 10, 0)
        updated = update_topic_schedule(db, user, topic.id, planned)
        assert updated.scheduled_for == planned
        serialized = serialize_topic(updated)
        assert serialized["scheduled_for"] == "2026-11-02T10:00:00"
        assert serialized["status"] == "new"

        cleared = update_topic_schedule(db, user, topic.id, None)
        assert cleared.scheduled_for is None
    finally:
        db.close()


def test_agent_topic_tool_can_save_to_pool(tmp_path):
    from backend.app.services.agent_service import _generate_topic_bank_tool

    db, user, account = _session(tmp_path)
    try:
        result = _generate_topic_bank_tool(
            db,
            user,
            {
                "account_id": account.id,
                "theme": "获客",
                "per_type": 1,
                "use_llm": False,
                "save": True,
            },
            None,
            account.id,
        )
        assert result["saved"] == len(TOPIC_TYPES)
        assert result["count"] == len(TOPIC_TYPES)
        assert len(list_saved_topics(db, user, account_id=account.id)) == len(TOPIC_TYPES)
    finally:
        db.close()
