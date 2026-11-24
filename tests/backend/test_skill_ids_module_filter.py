"""P2-15：显式 skill_ids 必须按模块过滤。

写稿页的 Skill 选择器列出全部模块；用户勾了「封面锚点」（visual）之后，
原实现用 ``effective_items(db, user, account_id=...)``（没有 module）取行，
再以「本模块启用的扩展 Skill：写稿」的标签渲染——图片方法论被当成写作规则。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import SkillLibraryItem, User
from backend.app.services.skill_library_service import module_skill_text


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sk.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _item(db, user, *, slug, module, body):
    row = SkillLibraryItem(
        user_id=user.id,
        slug=slug,
        name=slug,
        description="",
        module=module,
        triggers="",
        content_md=body,
        source="",
        license="",
        enabled=True,
        sort_order=10,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_explicit_pick_of_another_module_is_dropped(db):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    draft = _item(db, user, slug="draft-a", module="draft", body="# 去 AI 味\n要像人写的。")
    visual = _item(db, user, slug="cover-a", module="visual", body="# 封面锚点\n3:4 构图。")

    text = module_skill_text(
        db, user, "draft", skill_ids=[draft.id, visual.id], account_id=None
    )

    assert "去 AI 味" in text
    assert "3:4 构图" not in text, "视觉技能混进了文字 prompt"
    assert "1 篇" in text, "被丢弃的勾选项要明说，不能让勾选框变成谎话"


def test_explicit_pick_within_the_module_still_works(db):
    user = User(username="u2", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    a = _item(db, user, slug="a", module="draft", body="# A\n规则甲。")
    b = _item(db, user, slug="b", module="draft", body="# B\n规则乙。")

    text = module_skill_text(db, user, "draft", skill_ids=[a.id, b.id], account_id=None)

    assert "规则甲" in text and "规则乙" in text
    assert "不可用" not in text


def test_explicit_visual_pick_in_visual_module_is_kept(db):
    """视觉模块自己点名时不受影响。"""
    user = User(username="u3", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    visual = _item(db, user, slug="cover", module="visual", body="# 封面\n3:4。")

    text = module_skill_text(db, user, "visual", skill_ids=[visual.id], account_id=None)

    assert "3:4" in text


def test_all_picks_foreign_returns_explanatory_line(db):
    """全被模块过滤掉时，要说明原因，而不是静默返回空串。"""
    user = User(username="u4", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    visual = _item(db, user, slug="v", module="visual", body="# 封面\n3:4。")

    text = module_skill_text(db, user, "draft", skill_ids=[visual.id], account_id=None)

    assert "都不可用" in text
    assert "写稿" in text, "要指出是模块不匹配"
