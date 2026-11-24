"""Two scores, two questions — the API must say which is which.

`fit` answers "does this match *this account*". `craft` answers "is this well
written by general standards". They were both labelled as if they measured the
same thing, and the numbers disagree by design:

    draft imitating the author (no numeric title, no emoji)  craft 60.7
    generic draft with "3个场景" and emoji                    craft 67.3

Reporting both as "score" without scope made the better-fitting draft look worse.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AccountPositioning, PlatformAccount, User
from backend.app.services.skill_score_service import _craft, _fit


def test_generic_rubric_declares_its_scope():
    result = _craft(
        "3个场景，决定你用哪款AI编程工具",
        "先说结论，然后分三个场景讲清楚判断标准。最后留个问题。",
        ["AI工具", "AI编程", "效率工具"],
        "list",
        image_count=0,
        media_known=False,
        has_video=False,
    )
    assert result["scope"] == "generic"
    assert result["scope_label"] == "通用写作规范"
    assert "不考虑账号定位" in result["scope_note"]


def test_fit_declares_a_different_scope_or_absence():
    """fit must not claim to be a generic score, and must not score without data."""
    empty = _fit("t", "b", [], "long", positioning=None)
    assert empty["applicable"] is False
    assert empty.get("scope") != "generic"


def test_generic_rubric_rewards_a_numbered_title_over_an_author_faithful_one():
    """The known trade-off, pinned so nobody "fixes" it by accident.

    This author uses numeric titles in 2% of posts. A draft that copies him is
    therefore *penalised* by the generic rubric — which is correct behaviour for
    a generic rubric, and exactly why it must not be read as a fit score.
    """
    author_faithful = _craft(
        "别急着换AI编程工具，先分清三个场景",
        "先说结论。然后按场景讲判断标准。最后留个问题。",
        ["AI工具", "AI编程", "效率工具"],
        "long",
        image_count=0,
        media_known=False,
        has_video=False,
    )
    generic = _craft(
        "3个场景，决定你用哪款AI编程工具",
        "先说结论。然后按场景讲判断标准。最后留个问题。",
        ["AI工具", "AI编程", "效率工具"],
        "long",
        image_count=0,
        media_known=False,
        has_video=False,
    )
    assert generic["total"] >= author_faithful["total"], (
        "通用规范本来就偏好数字标题；若这条不再成立，说明权重被改动了，"
        "需要重新确认 fit 与 craft 的分工"
    )
