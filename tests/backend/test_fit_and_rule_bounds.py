"""Three fixes from the first real generation run.

1. `fit` gave 100/S to a draft while `craft` and `note-score` both said B. It
   never read the account's positioning — it matched hardcoded AI keywords, so
   any AI-topic draft reached S. Every dimension it claims to measure (pillars,
   audience, taboos) is defined *by* the positioning; with no positioning there
   is nothing to compare against.

2. The rhythm rule said "10 个以上内容单元" with no upper bound, so the model cut
   the draft into 27 units — the 91st percentile of the author's own output.

3. `emoji_use` sits at 5% for this author, yet the draft used three emoji (95th
   percentile). A habit that is measurably absent should be injected as a
   negative constraint, not ignored.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AccountPositioning, PlatformAccount, User
from backend.app.services.skill_score_service import _fit


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fit.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="fit-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


# --- 1. fit refuses to score without positioning ---------------------------


def test_fit_is_not_applicable_without_positioning():
    result = _fit("标题", "正文内容", ["tag"], "long", positioning=None)
    assert result["applicable"] is False
    assert result["total"] is None
    assert "无法评估" in result["summary"]
    assert result["dimensions"] == []


def test_fit_is_not_applicable_when_positioning_is_blank(db):
    session, user = db
    blank = AccountPositioning(user_id=user.id, platform_account_id=1)
    result = _fit("标题", "正文", [], "long", positioning=blank)
    assert result["applicable"] is False


def test_fit_scores_against_the_declared_pillars(db):
    session, user = db
    positioning = AccountPositioning(
        user_id=user.id,
        platform_account_id=1,
        positioning="AI 工具实测",
        audience="独立开发者",
        main_topics=["AI工具", "一人公司"],
        taboos=["不承诺收益"],
    )
    hit = _fit("AI工具怎么选", "写给独立开发者", [], "long", positioning=positioning)
    miss = _fit("早餐怎么做", "今天吃什么", [], "long", positioning=positioning)

    assert hit["applicable"] is True
    assert hit["total"] > miss["total"], "命中支柱应当高于完全不相关的稿子"


def test_fit_penalises_a_declared_taboo(db):
    session, user = db
    positioning = AccountPositioning(
        user_id=user.id,
        platform_account_id=1,
        positioning="AI 工具实测",
        audience="独立开发者",
        main_topics=["AI工具"],
        taboos=["承诺收益"],
    )
    clean = _fit("AI工具怎么选", "讲清楚判断标准", [], "long", positioning=positioning)
    dirty = _fit("AI工具怎么选", "承诺收益，三个月回本", [], "long", positioning=positioning)

    assert dirty["total"] < clean["total"], "触碰自己写的禁区必须扣分"


def test_fit_cannot_reach_s_without_matching_anything(db):
    """The old scorer's floor was 70 and ceiling 100 for any AI topic."""
    session, user = db
    positioning = AccountPositioning(
        user_id=user.id,
        platform_account_id=1,
        positioning="AI 工具实测",
        audience="独立开发者",
        main_topics=["AI工具"],
        taboos=["承诺收益"],
    )
    result = _fit("周末去哪玩", "城市散步路线", [], "long", positioning=positioning)
    assert result["total"] < 70, "不相关的稿子不该及格"


# --- 2. rhythm rule carries an upper bound --------------------------------


def test_rhythm_rule_states_the_measured_range():
    """The rule must state an upper bound; the numbers come from the corpus."""
    from backend.app.services.style_hypotheses import HYPOTHESES

    rule = next(h for h in HYPOTHESES if h.key == "paragraph_rhythm").rule
    assert "10" in rule
    assert "{median}" in rule and "{p90}" in rule, "上限必须由语料实测填入，不能写死"


def test_rhythm_rule_uses_this_corpus_numbers():
    from backend.app.services.style_evidence import CorpusDoc, evaluate_hypothesis
    from backend.app.services.style_hypotheses import HYPOTHESIS_BY_KEY

    docs = [
        CorpusDoc(key=f"d{i}", title="t", body="\n".join(["这是十来个字的一句口播"] * 30))
        for i in range(6)
    ]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["paragraph_rhythm"], docs)
    assert "{median}" not in item["rule"]
    assert "本语料中位" in item["rule"]


# --- 3. near-absent habits become negative constraints --------------------


def test_near_absent_rule_with_counter_rule_is_injected():
    from backend.app.services.style_evidence import rules_for_prompt

    report = {
        "items": [
            {
                "key": "emoji_use",
                "verdict": "design_choice",
                "coverage": 0.05,
                "rule": "用 emoji 当结构标记。",
                "counter_rule": "这个作者正文几乎不用 emoji，保持纯文字。",
            }
        ]
    }
    lines = rules_for_prompt(report)
    assert len(lines) == 1
    assert lines[0].startswith("- 不要：")
    assert "emoji" in lines[0]


def test_design_choice_without_counter_rule_is_still_not_injected():
    from backend.app.services.style_evidence import rules_for_prompt

    report = {
        "items": [
            {
                "key": "somatic",
                "verdict": "design_choice",
                "coverage": 0.02,
                "rule": "写身体感受。",
                "counter_rule": "",
            }
        ]
    }
    assert rules_for_prompt(report) == []


def test_a_common_design_choice_is_not_turned_into_a_negative_rule():
    """30% is not "absent" — injecting "don't do it" would fight the author."""
    from backend.app.services.style_evidence import rules_for_prompt

    report = {
        "items": [
            {
                "key": "inventory_format",
                "verdict": "design_choice",
                "coverage": 0.30,
                "rule": "用清单。",
                "counter_rule": "别硬拆清单。",
            }
        ]
    }
    assert rules_for_prompt(report) == []
