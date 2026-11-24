"""自检补口：标题/正文/标签的确定性检查 + 结构模板覆盖度。

为什么这些要单独测：它们都是「便宜且从不漏」的规则，
但每一条都直接对应用户会踩的真实坑（标题超 20 字发不出去、正文里有
「标题：」残留、标签重复、模板选了没照着写）。规则本身很好改坏，
所以逐条钉住。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AiDraft, User, ViralTemplate
from backend.app.services.publish_preflight_service import (
    _copy_checks,
    _structure_checks,
    _tag_name_checks,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pf.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="pf-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def levels(checks, key):
    return [c["level"] for c in checks if c["key"] == key]


# --- 标题 -------------------------------------------------------------------


def test_title_over_limit_is_an_error_not_a_warning():
    """超过 20 字发不出去，不是「建议改」——这条以前是 warning。"""
    checks = _copy_checks("这是一个二十三个字的标题用来验证长度检查是否生效", "正文" * 60)
    assert levels(checks, "title_length") == ["error"]


def test_title_at_exactly_twenty_chars_passes():
    title = "一二三四五六七八九十一二三四五六七八九十"
    assert len(title) == 20
    checks = _copy_checks(title, "正文" * 60)
    assert "title_length" not in [c["key"] for c in checks]


def test_title_with_newline_is_an_error():
    checks = _copy_checks("前半句\n后半句", "正文" * 60)
    assert levels(checks, "title_newline") == ["error"]


def test_title_ending_with_period_is_a_warning():
    checks = _copy_checks("这是一个标题。", "正文" * 60)
    assert levels(checks, "title_punct") == ["warning"]


def test_question_mark_ending_is_not_flagged():
    """问号是标题的正常写法，不能误伤。"""
    checks = _copy_checks("为什么没人告诉你这件事？", "正文" * 60)
    assert "title_punct" not in [c["key"] for c in checks]


def test_empty_title_is_an_error():
    checks = _copy_checks("", "正文" * 60)
    assert levels(checks, "title") == ["error"]


# --- 正文 -------------------------------------------------------------------


def test_body_over_hard_limit_is_an_error():
    checks = _copy_checks("标题", "字" * 9000)
    assert levels(checks, "body_max") == ["error"]


def test_body_over_comfort_zone_is_a_warning():
    checks = _copy_checks("标题", "字" * 1500)
    assert levels(checks, "body_comfort") == ["warning"]


def test_body_too_short_is_a_warning():
    checks = _copy_checks("标题", "太短")
    assert levels(checks, "body_length") == ["warning"]


def test_single_paragraph_body_is_flagged():
    body = "这是一整块没有任何分段的正文，手机上一屏看不到边界。" * 6
    checks = _copy_checks("标题", body)
    assert levels(checks, "body_paragraphs") == ["warning"]


def test_multi_paragraph_body_is_not_flagged():
    body = ("第一段讲结论。\n\n第二段给三条动作。\n\n第三段一句反问收尾。") * 4
    checks = _copy_checks("标题", body)
    assert "body_paragraphs" not in [c["key"] for c in checks]


def test_title_marker_leaking_into_body_is_an_error():
    checks = _copy_checks("标题", "标题：真正标题\n\n正文从这里开始。" + "补" * 200)
    assert levels(checks, "body_title_leak") == ["error"]


def test_normal_body_has_no_errors():
    body = "第一段讲结论。\n\n第二段给三条动作。\n\n第三段一句反问收尾。" * 4
    checks = _copy_checks("带团队第一年我踩过的三个坑", body)
    assert [c for c in checks if c["level"] == "error"] == []


# --- 标签 -------------------------------------------------------------------


def test_no_tags_is_a_warning():
    checks = _tag_name_checks([])
    assert levels(checks, "tags") == ["warning"]


def test_three_tags_pass():
    checks = _tag_name_checks(["成长", "复盘", "职场"])
    assert "tags_count" not in [c["key"] for c in checks]


def test_duplicate_tags_are_reported():
    checks = _tag_name_checks(["成长", "成长", "复盘"])
    assert levels(checks, "tags_dup") == ["warning"]


def test_overlong_tag_is_reported():
    checks = _tag_name_checks(["成长", "复盘", "职" * 25])
    assert levels(checks, "tags_long") == ["warning"]


# --- 结构模板 ---------------------------------------------------------------


def test_draft_without_template_has_no_structure_check(db):
    session, user = db
    draft = AiDraft(user_id=user.id, platform="xhs", title="标题", body="正文" * 40)
    session.add(draft)
    session.commit()
    assert _structure_checks(session, user, draft) == []


def test_draft_with_non_positional_template_is_skipped(db):
    """卡片式模板没有开头/中段/结尾，不能假装能检查。"""
    session, user = db
    template = ViralTemplate(
        user_id=user.id,
        name="卡片模板",
        payload={"kind": "card"},
        source_note_ids=[],
    )
    session.add(template)
    session.flush()
    draft = AiDraft(
        user_id=user.id,
        platform="xhs",
        title="标题",
        body="正文" * 40,
        template_id=template.id,
    )
    session.add(draft)
    session.commit()
    assert _structure_checks(session, user, draft) == []


def test_another_users_template_is_ignored(db):
    session, user = db
    other = User(username="other", password_hash="x")
    session.add(other)
    session.commit()
    template = ViralTemplate(
        user_id=other.id,
        name="别人的模板",
        payload={"kind": "positional"},
        source_note_ids=[],
    )
    session.add(template)
    session.flush()
    draft = AiDraft(
        user_id=user.id,
        platform="xhs",
        title="标题",
        body="正文" * 40,
        template_id=template.id,
    )
    session.add(draft)
    session.commit()
    assert _structure_checks(session, user, draft) == []
