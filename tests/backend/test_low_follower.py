"""低粉爆款：一份口径、一个筛选器、不再有两套事实。

行业定义不统一（粉丝 <200 到 ≤5000 都有），但共识是**判定看比率不看绝对值**：
粉丝量少于赞量，说明内容是平台推起来的，不是粉丝基数托起来的。

这些测试盯三件事：

1. 口径只有一处（``low_follower.DEFAULT_RULE``），阈值改动不影响别处的语义。
2. 粉丝数「未知」不等于 0。0 会通过任何上限检查，把未知变成最强信号。
3. 结构模板只吃筛出来的样本，并在 payload 里写清筛了多少、为什么。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.core.time import shanghai_now
from backend.app.services.low_follower import (
    DEFAULT_RULE,
    LEGACY_WIDE_RULE,
    MIN_TEMPLATE_DOCS,
    STRICT_RULE,
    LowFollowerRule,
    describe_miss,
    summarize,
)
from backend.app.services.structure_template_service import build_structure_template
from backend.app.services.style_evidence import CorpusDoc

FAIL_OPENING = (
    "让你把表格拖上去，结果你拖了半天也没拖上去。你不是说自己精通办公软件吗？那我问你。"
    "你先点击表格，然后选择布局。点赞收藏，学会了吗。#Excel #办公技巧"
)


def _doc(key: str, *, fans: int, likes: int, days_old: int | None = 3, body: str = FAIL_OPENING):
    meta = {
        "author_fans": fans,
        "fans_known": fans > 0,
        "likes": likes,
        "published_at": (
            None if days_old is None else shanghai_now() - timedelta(days=days_old)
        ),
    }
    return CorpusDoc(key=key, title=f"标题{key}", body=body, meta=meta)


# --------------------------------------------------------------------------- #
# 口径
# --------------------------------------------------------------------------- #


def test_default_rule_is_the_middle_tier():
    assert DEFAULT_RULE.max_fans == 5000
    assert DEFAULT_RULE.min_likes == 500
    assert DEFAULT_RULE.min_like_fan_ratio == 1.0


def test_rule_accepts_a_low_follower_breakout():
    assert DEFAULT_RULE.accepts(fans=183, likes=7325)


def test_rule_rejects_a_big_account_with_the_same_likes():
    """The whole point: same likes, different fan base, different meaning."""
    assert DEFAULT_RULE.accepts(fans=183, likes=7325)
    assert not DEFAULT_RULE.accepts(fans=80_000, likes=7325)


def test_rule_rejects_when_ratio_is_below_one():
    assert not DEFAULT_RULE.accepts(fans=4000, likes=3999)


def test_unknown_fans_must_not_be_passed_as_zero():
    """0 fans would satisfy every upper bound — callers must check "known" first."""
    assert not DEFAULT_RULE.accepts(fans=0, likes=10_000)


def test_recency_window_excludes_unknown_and_old():
    rule = LowFollowerRule(max_fans=5000, min_likes=500, min_like_fan_ratio=1.0, within_days=7)
    assert rule.accepts(fans=500, likes=1000, days_old=3)
    assert not rule.accepts(fans=500, likes=1000, days_old=30)
    assert not rule.accepts(fans=500, likes=1000, days_old=None), "未知日期不算近期"


def test_thresholds_are_ordered_by_strictness():
    assert STRICT_RULE.max_fans < DEFAULT_RULE.max_fans < LEGACY_WIDE_RULE.max_fans


def test_label_states_every_number():
    """The UI must never show 「低粉爆款」 without saying what it filtered on."""
    label = DEFAULT_RULE.label()
    assert "5,000" in label and "500" in label and "1" in label


# --------------------------------------------------------------------------- #
# 解释为什么是空的
# --------------------------------------------------------------------------- #


def test_miss_explains_when_no_fans_were_measured():
    message = describe_miss(total=40, measured=0, passed=0, rule=DEFAULT_RULE)
    assert "粉丝数都没有采到" in message
    assert "补采作者信息" in message


def test_miss_explains_partial_measurement():
    message = describe_miss(total=40, measured=12, passed=1, rule=DEFAULT_RULE)
    assert "只有 12 篇" in message
    assert "不是不合格，是未知" in message


def test_miss_is_silent_when_enough_passed():
    assert describe_miss(total=40, measured=40, passed=5, rule=DEFAULT_RULE) == ""


def test_summarize_separates_unmeasured_from_failed():
    items = [
        {"author_fans": 183, "likes": 7325},   # passes
        {"author_fans": 80000, "likes": 7325},  # measured, too big
        {"author_fans": 0, "likes": 9000},      # unknown
    ]
    stats = summarize(items, DEFAULT_RULE)
    assert stats["total"] == 3
    assert stats["measured"] == 2
    assert stats["unmeasured"] == 1
    assert stats["passed"] == 1
    assert stats["rule"]["label"] == DEFAULT_RULE.label()


# --------------------------------------------------------------------------- #
# 结构模板只用筛出来的样本
# --------------------------------------------------------------------------- #


def test_template_uses_only_low_follower_notes():
    docs = [_doc(f"hit{i}", fans=300, likes=5000) for i in range(3)]
    docs += [_doc(f"big{i}", fans=200_000, likes=90_000) for i in range(5)]

    payload = build_structure_template(docs, rule=DEFAULT_RULE)

    assert payload["selection"]["selected"] == 3
    assert payload["selection"]["excluded_by_rule"] == 5
    assert payload["documents"] == 3, "大号不能被算进结构统计"


def test_template_refuses_when_nothing_qualifies():
    docs = [_doc(f"big{i}", fans=200_000, likes=90_000) for i in range(5)]
    with pytest.raises(ValueError) as excinfo:
        build_structure_template(docs, rule=DEFAULT_RULE)
    assert "不足" in str(excinfo.value)


def test_template_refuses_when_fans_were_never_measured():
    docs = [
        CorpusDoc(key=f"d{i}", title="t", body=FAIL_OPENING, meta={"likes": 9000})
        for i in range(6)
    ]
    with pytest.raises(ValueError) as excinfo:
        build_structure_template(docs, rule=DEFAULT_RULE)
    assert "粉丝数都没有采到" in str(excinfo.value)


def test_template_without_rule_keeps_old_behaviour():
    """A direct caller passing no rule must not silently change meaning."""
    docs = [_doc("a", fans=300, likes=5000), _doc("b", fans=200_000, likes=90_000)]
    docs.append(CorpusDoc(key="c", title="t", body=FAIL_OPENING, meta={}))
    payload = build_structure_template(docs)
    assert payload["documents"] == 3
    assert payload["selection"]["rule"].startswith("全部")


def test_template_reports_both_exclusion_reasons():
    docs = [_doc(f"hit{i}", fans=300, likes=5000) for i in range(3)]
    docs += [_doc("big", fans=200_000, likes=90_000)]
    docs += [CorpusDoc(key="unknown", title="t", body=FAIL_OPENING, meta={"likes": 9000})]
    payload = build_structure_template(docs, rule=DEFAULT_RULE)
    selection = payload["selection"]
    assert selection["candidates"] == 5
    assert selection["selected"] == 3
    assert selection["excluded_unmeasured"] == 1
    assert selection["excluded_by_rule"] == 1


def test_min_template_docs_is_three():
    assert MIN_TEMPLATE_DOCS == 3
