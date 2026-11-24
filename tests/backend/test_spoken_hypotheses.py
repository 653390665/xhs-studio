"""口播假设集：检测器行为、媒介选择、对照组的体裁共性判定。"""
from __future__ import annotations

from backend.app.services.evidence_distill_service import (
    _select_hypotheses,
    apply_two_batch_replication,
    split_batches,
)
from backend.app.services.spoken_hypotheses import (
    SPOKEN_HYPOTHESES,
    detect_spoken_breath_rhythm,
    detect_spoken_cta_close,
    detect_spoken_negative_hook,
    detect_spoken_numbered_list,
    detect_spoken_open_with_result,
    detect_spoken_resource_hook,
    detect_spoken_steps,
    detect_spoken_you_command,
)
from backend.app.services.style_evidence import (
    CorpusDoc,
    attach_genre_baseline,
    evaluate_corpus,
    rules_for_prompt,
)


def test_open_with_result_rejects_self_intro():
    assert detect_spoken_open_with_result("大家好，我是小王，今天聊聊AI") == 0.0
    assert detect_spoken_open_with_result("答案很明显：普通人现在学AI完全来得及") == 1.0


def test_steps_need_two_distinct_markers():
    assert detect_spoken_steps("首先打开设置，然后点击通知") == 1.0
    assert detect_spoken_steps("首先打开设置就可以了") == 0.0


def test_you_command_needs_two_instructions():
    assert detect_spoken_you_command("你打开设置，你点击系统") == 1.0
    assert detect_spoken_you_command("你打开设置") == 0.0


def test_negative_hook_only_counts_the_opening_third():
    body = "千万不要再盲目学AI了。" + "这是一段中性的说明文字，" * 20
    assert detect_spoken_negative_hook(body) == 1.0
    tail = "这是一段中性的说明文字，" * 20 + "千万不要再盲目学AI了。"
    assert detect_spoken_negative_hook(tail) == 0.0, "结尾的禁令不算开场钩子"


def test_cta_close_reads_the_last_unit():
    assert detect_spoken_cta_close("讲完了。\n评论区打出AI学习") == 1.0
    assert detect_spoken_cta_close("讲完了。\n希望你今天有收获") == 0.0


def test_resource_hook():
    assert detect_spoken_resource_hook("全套资料我整理好了") == 1.0
    assert detect_spoken_resource_hook("今天讲讲这个工具") == 0.0


def test_numbered_list_requires_the_items():
    complete = "五条指令。第一条打开设置。第二条点击系统。第三条选择通知。第四条关闭。第五条完成。"
    assert detect_spoken_numbered_list(complete) == 1.0
    claimed_only = "五条指令，输入以下内容就行。"
    assert detect_spoken_numbered_list(claimed_only) == 0.0


def test_breath_rhythm_uses_raw_lines_not_joined_units():
    short_lines = "\n".join(["这是十个字左右"] * 10)
    long_lines = "\n".join(["这是一段明显超过十五个字的完整句子用来测试断句"] * 10)
    assert detect_spoken_breath_rhythm(short_lines) == 1.0
    assert detect_spoken_breath_rhythm(long_lines) == 0.0


def test_spoken_set_is_selected_only_for_all_spoken_corpora():
    spoken = [CorpusDoc(key="a", body="x" * 100, meta={"medium": "spoken"})]
    written = [CorpusDoc(key="b", body="x" * 100, meta={"medium": "written"})]
    mixed = spoken + written

    assert _select_hypotheses(spoken, "auto")[0] == "spoken"
    assert _select_hypotheses(written, "auto")[0] == "text"
    assert _select_hypotheses(mixed, "auto")[0] == "text"
    assert _select_hypotheses(written, "spoken")[0] == "spoken"


def test_control_marks_genre_conventions_and_skips_injection():
    report = {
        "items": [
            {
                "key": "spoken_open_result",
                "claim": "开场直给结论",
                "source": "theory",
                "dimension": "开头",
                "verdict": "hard_rule",
                "coverage": 0.9,
                "support": 9,
                "total": 10,
                "reason": "",
                "rule": "开头直给结论",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {"hard_rule": 1},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [
            {
                "key": "spoken_open_result",
                "coverage": 0.85,
                "support": 17,
                "total": 20,
            }
        ],
        "corpus": {"usable": 20},
    }

    attach_genre_baseline(report, control, label="对照作者")

    item = report["items"][0]
    assert item["genre_convention"] is True
    assert item["control_coverage"] == 0.85
    assert report["summary"]["genre_convention"] == 1
    assert report["summary"]["hard_rule"] == 0, "体裁共性不能再算成本人的硬规则"
    assert rules_for_prompt(report) == [], "两边都成立的习惯不能当个人风格注入"


def test_control_does_not_flag_a_rule_only_the_control_follows():
    """Main 15% vs control 60% is a difference, not a shared convention."""
    report = {
        "items": [
            {
                "key": "spoken_numbered_list",
                "claim": "数字清单",
                "source": "theory",
                "dimension": "结构",
                "verdict": "design_choice",
                "coverage": 0.15,
                "support": 4,
                "total": 27,
                "reason": "",
                "rule": "列出 N 项",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [{"key": "spoken_numbered_list", "coverage": 0.6, "support": 6, "total": 10}],
        "corpus": {"usable": 10},
    }

    attach_genre_baseline(report, control, label="对照作者")

    assert report["items"][0]["genre_convention"] is False


def test_a_minority_habit_above_the_control_becomes_a_preference():
    """41% question hooks vs 0% control is a signature, not a design choice."""
    report = {
        "items": [
            {
                "key": "sp_hook_question",
                "claim": "问句开场",
                "source": "theory",
                "dimension": "开头",
                "verdict": "design_choice",
                "coverage": 0.44,
                "support": 12,
                "total": 27,
                "reason": "",
                "rule": "开头用问句",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [{"key": "sp_hook_question", "coverage": 0.0, "support": 0, "total": 10}],
        "corpus": {"usable": 10},
    }

    attach_genre_baseline(report, control, label="对照作者")

    item = report["items"][0]
    assert item["verdict"] == "preference"
    assert item["preference"] is True
    assert item["preference_confidence"] == "low", "10 篇对照 + p=0.066 只能算探索性"
    assert report["summary"]["preference"] == 1

    # Without a second batch this remains a candidate and must not be injected.
    assert rules_for_prompt(report) == []
    item["preference_status"] = "confirmed"
    assert rules_for_prompt(report)[0].startswith("- 偏好（探索性）：")


def test_a_small_gap_stays_a_design_choice():
    report = {
        "items": [
            {
                "key": "sp_hook_story",
                "claim": "故事开场",
                "source": "theory",
                "dimension": "开头",
                "verdict": "design_choice",
                "coverage": 0.3,
                "support": 8,
                "total": 27,
                "reason": "",
                "rule": "开头讲故事",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [{"key": "sp_hook_story", "coverage": 0.25, "support": 2, "total": 10}],
        "corpus": {"usable": 10},
    }

    attach_genre_baseline(report, control, label="对照作者")

    assert report["items"][0]["verdict"] == "design_choice"


def test_a_large_gap_without_significance_is_not_a_preference():
    """8/15 vs 2/10: 33 points apart, but Fisher p=0.21 — noise at this size."""
    report = {
        "items": [
            {
                "key": "sp_hook_number",
                "claim": "数字开场",
                "source": "theory",
                "dimension": "开头",
                "verdict": "design_choice",
                "coverage": 8 / 15,
                "support": 8,
                "total": 15,
                "reason": "",
                "rule": "开头报数字",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [{"key": "sp_hook_number", "coverage": 0.2, "support": 2, "total": 10}],
        "corpus": {"usable": 10},
    }

    attach_genre_baseline(report, control, label="对照作者")

    item = report["items"][0]
    assert item["verdict"] == "design_choice"
    assert item["control_p"] > 0.10


def test_control_keeps_rules_the_author_does_more_than_the_control():
    report = {
        "items": [
            {
                "key": "spoken_steps",
                "claim": "步骤化",
                "source": "theory",
                "dimension": "结构",
                "verdict": "hard_rule",
                "coverage": 0.9,
                "support": 9,
                "total": 10,
                "reason": "",
                "rule": "用步骤词串起来",
                "counter_rule": "",
                "note": "",
                "samples": [],
                "counter_examples": [],
            }
        ],
        "summary": {"hard_rule": 1},
        "corpus": {},
        "thresholds": {},
    }
    control = {
        "items": [{"key": "spoken_steps", "coverage": 0.4, "support": 8, "total": 20}],
        "corpus": {"usable": 20},
    }

    attach_genre_baseline(report, control, label="对照作者")

    assert report["items"][0]["genre_convention"] is False
    assert rules_for_prompt(report), "主作者显著更高的规则应保留"


def test_all_spoken_hypotheses_are_resolvable():
    from backend.app.services.spoken_hypotheses import SPOKEN_DETECTORS

    assert len(SPOKEN_HYPOTHESES) == 8
    for hypothesis in SPOKEN_HYPOTHESES:
        assert hypothesis.detector in SPOKEN_DETECTORS


# --- 两批复现 ---------------------------------------------------------------

_AUDIENCE_BODY = "打工人听我一句，AI 工具别一上来就装一堆，先从每天都要干的活里挑一件，用顺了再考虑别的。"
_PLAIN_BODY = "AI 工具别一上来就装一堆，先从每天都要干的活里挑一件，用顺了再慢慢考虑换别的工具。"


def _batch(job_id: int, audience: int, total: int = 10):
    docs = []
    for index in range(total):
        body = _AUDIENCE_BODY if index < audience else _PLAIN_BODY
        docs.append(
            CorpusDoc(
                key=f"j{job_id}-{index}",
                title="t",
                body=body,
                meta={"medium": "spoken", "job_id": job_id},
            )
        )
    return docs


def test_split_batches_groups_by_job_id():
    batches = split_batches(_batch(1, 4) + _batch(2, 4))
    assert [job_id for job_id, _ in batches] == [1, 2]
    assert [len(group) for _, group in batches] == [10, 10]


def test_preference_without_a_second_batch_stays_a_candidate():
    docs = _batch(1, 6, 20)
    control = _batch(99, 0)
    report = evaluate_corpus(docs, hypotheses=SPOKEN_HYPOTHESES)
    attach_genre_baseline(
        report,
        evaluate_corpus(control, hypotheses=SPOKEN_HYPOTHESES),
        label="基线",
    )
    payload = {"report": report}

    apply_two_batch_replication(payload, docs, control, SPOKEN_HYPOTHESES)

    item = next(i for i in report["items"] if i["key"] == "sp_hook_audience")
    assert item["verdict"] == "preference"
    assert item["preference_status"] == "candidate"
    assert payload["batch_plan"]["needed_confirmation_docs"] == 10
    assert "再采 10 条" in payload["batch_plan"]["note"]
    lines = rules_for_prompt(report)
    assert not any("点名受众" in line for line in lines), "单批偏好不能注入"


def test_preference_is_confirmed_when_the_second_batch_repeats_it():
    docs = _batch(1, 4) + _batch(2, 4)
    control = _batch(99, 0)
    report = evaluate_corpus(docs, hypotheses=SPOKEN_HYPOTHESES)
    attach_genre_baseline(
        report,
        evaluate_corpus(control, hypotheses=SPOKEN_HYPOTHESES),
        label="基线",
    )
    payload = {"report": report}

    apply_two_batch_replication(payload, docs, control, SPOKEN_HYPOTHESES)

    item = next(i for i in report["items"] if i["key"] == "sp_hook_audience")
    assert item["preference_status"] == "confirmed"
    assert item["discovery_coverage"] == 0.4
    assert item["confirmation_coverage"] == 0.4
    assert payload["batch_plan"]["mode"] == "two_batch"
    assert any("偏好" in line for line in rules_for_prompt(report))


def test_preference_is_demoted_when_the_second_batch_does_not_repeat_it():
    docs = _batch(1, 6) + _batch(2, 0)
    control = _batch(99, 0)
    report = evaluate_corpus(docs, hypotheses=SPOKEN_HYPOTHESES)
    attach_genre_baseline(
        report,
        evaluate_corpus(control, hypotheses=SPOKEN_HYPOTHESES),
        label="基线",
    )
    payload = {"report": report}

    apply_two_batch_replication(payload, docs, control, SPOKEN_HYPOTHESES)

    item = next(i for i in report["items"] if i["key"] == "sp_hook_audience")
    assert item["preference_status"] == "candidate"
    assert item["verdict"] == "design_choice"
    lines = rules_for_prompt(report)
    assert not any("点名受众" in line for line in lines)
