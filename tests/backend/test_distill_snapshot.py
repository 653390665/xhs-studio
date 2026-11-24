"""冻结蒸馏水准：任何检测器行为变化都必须显式反映在这里。

这个文件的目的不是"再测一遍功能"，而是让**静默漂移不可能发生**。

背景：2026-10-29 一天内连续发现 5 个检测器缺陷（actor 当具体细节、
「他说」当引语、最后一行当收尾、_TIME 缺「今天」、断言词表过窄）。
每一次都是"换一份语料才发现"，因为没有任何东西固定住既有行为。

因此这里做两件事：

1. **确定性**：同一份语料跑两次，报告必须逐字节相同。
2. **黄金快照**：一份属性已知的合成语料，其摘要与逐条判定被写死。
   如果某个检测器被改动，这里会失败——那不是噪声，是提醒你：
   行为变了，去确认是有意的，然后把新数字更新到这里并说明理由。

**更新快照的规则**：只有当你能解释"为什么新行为更对"时才改，
并且要在同一次提交里写清原因。数字变了但说不清原因的，一律视为回归。
"""
from __future__ import annotations

import json

import pytest

from backend.app.services.style_evidence import CorpusDoc, evaluate_corpus
from backend.app.services.style_hypotheses import HYPOTHESES

# 合成语料：每篇的属性是刻意设计的，覆盖"HARD / TENDENCY / DESIGN"三档。
# 注意：这不是真实笔记，只是让每个检测器都有明确、可复现的输入。
POSTS = [
    # 0-4：个人叙事，带时间、地点、引语、身体反应、反转、金句收尾
    (
        "跟我妈吵完那一架，我才明白自己在怕什么",
        "上周三在公司楼下，我跟我妈吵了一架，她说：你这样下去不行的。"
        "我手心全是汗。不是我不努力，而是我真的不知道往哪走。"
        "后来我想明白了，先动起来比想清楚更重要。你会慢慢找到路的。",
    ),
    (
        "在医院走廊等结果的那两个小时",
        "去年冬天在医院走廊等结果，朋友跟我说：别自己吓自己。"
        "我坐在那儿，心跳得厉害。其实不是怕结果，是怕没人陪。"
        "所以那之后我学会了一件事：先说出口，别硬扛。有人陪着，难的事也会变轻。",
    ),
    (
        "第一次做线下活动，来了 15 个人",
        "那天下午我胃一直不舒服，开场前手一直在抖。"
        "有人问我：你怎么敢开始？我说因为我算过最差的结果。"
        "讲完第一段就放松了。不是所有准备都要完美，先上场才有后来。",
    ),
    (
        "上个月我把用了三年的工具全换掉了",
        "同事说我折腾。其实我只是发现，工具越多我越慢。"
        "所以现在只留三个。少一点，反而快一点。",
    ),
    (
        "前天晚上十点，我一个人在办公室改方案",
        "领导发消息：明天再说。我没回。"
        "那天我哭了一场，然后关电脑回家。"
        "后来明白，不是所有事都值得当天做完。留一点给明天。",
    ),
    # 5-9：产品/方法型，结构清晰、数字多、无身体感受
    (
        "2026 年 AI 编程工具怎么选：三个场景",
        "场景一，从零起项目。看生成能力和能否执行命令。"
        "场景二，改老代码。看项目级上下文和 IDE 支持。"
        "场景三，团队评审。看权限、日志、代码能否出内网。"
        "结论：先分类你的活，再选工具。",
    ),
    (
        "五个免费工具，覆盖写稿全流程",
        "1. 选题：用搜索看真实提问。2. 起草：先列结构再填内容。"
        "3. 配图：固定两个模板轮换。4. 剪辑：批量套字幕样式。"
        "5. 复盘：只看收藏和评论。",
    ),
    (
        "用 AI 做周报，省下两个小时",
        "第 1 步，把这周的事列成流水账。第 2 步，让它按结果分组。"
        "第 3 步，把过程删掉只留结论。第 4 步，自己改语气。"
        "注意：别把内部数据贴进去。",
    ),
    (
        "三个信号，判断一个 AI 工具值不值得留",
        "一，免费额度能不能做完一个完整项目。二，导出文件能不能直接进下一步。"
        "三，学它要不要超过一周。三条有两条不满足，就别留。",
    ),
    (
        "2026 年做内容，先想清楚这三件事",
        "写给谁、解决什么、凭什么信你。三个都答不上来，先别更新。"
        "答上来了，再考虑形式和频率。",
    ),
]

TITLE = "测试语料"
DOCS = [
    CorpusDoc(key=f"p{i}", title=t, body=b, role="baseline")
    for i, (t, b) in enumerate(POSTS)
]

# 冻结值：由当前检测器产生，逐条锁定。
# 变更时必须能解释"为什么新行为更对"。
FROZEN_SUMMARY = {
    "hard_rule": 1,
    "tendency": 0,
    "preference": 0,
    "design_choice": 18,
    "insufficient": 0,
}

FROZEN_VERDICTS = {
    "result_first": "design_choice",
    "contrast": "design_choice",
    "specific_detail": "design_choice",
    "mechanism": "design_choice",
    "short_units": "hard_rule",
    "quoted_speech": "design_choice",
    "somatic": "design_choice",
    "declarative_close": "design_choice",
    "transactional_cta": "design_choice",
    "second_person": "design_choice",
    "inventory_format": "design_choice",
    "hook_number": "design_choice",
    "hook_question": "design_choice",
    "hook_identity": "design_choice",
    "hook_contrast": "design_choice",
    "hook_emoji": "design_choice",
    "paragraph_rhythm": "design_choice",
    "emoji_use": "design_choice",
    "bullet_layout": "design_choice",
}


def _report():
    return evaluate_corpus(DOCS)


# --- 1. 确定性 --------------------------------------------------------------


def test_report_is_deterministic():
    """同一输入两次，报告必须完全一致（含顺序）。"""
    a = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_all_hypotheses_appear_exactly_once():
    report = _report()
    keys = [item["key"] for item in report["items"]]
    assert len(keys) == len(HYPOTHESES)
    assert len(set(keys)) == len(keys), "有重复规则"


# --- 2. 黄金快照 ------------------------------------------------------------


def test_summary_is_frozen():
    report = _report()
    assert report["summary"] == FROZEN_SUMMARY, (
        "蒸馏结论变了。先确认是新检测器更准确，还是行为漂移。\n"
        f"实际：{report['summary']}"
    )


def test_verdicts_are_frozen():
    report = _report()
    actual = {item["key"]: item["verdict"] for item in report["items"]}
    assert actual == FROZEN_VERDICTS


def test_coverage_values_are_stable():
    """覆盖率精确到 1%，同样冻结——它才是会漂的那一层。"""
    report = _report()
    actual = {item["key"]: round(item["coverage"], 2) for item in report["items"]}
    expected = {key: actual[key] for key in FROZEN_VERDICTS}  # 首轮固定，见下
    # 首次运行会写入实际值；之后任何变化都会失败。
    frozen_file = __file__.replace(".py", "_values.json")
    import json as _json
    import pathlib

    path = pathlib.Path(frozen_file)
    if not path.exists():
        path.write_text(_json.dumps(expected, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip("首次运行：已记录基线覆盖率")
    baseline = _json.loads(path.read_text(encoding="utf-8"))
    assert actual == baseline, (
        "覆盖率变化了。若确认是有意修正，删除 "
        f"{path.name} 后重跑以重建基线，并在提交说明里写清原因。"
    )


# --- 3. 反脆弱性（历史缺陷的回归入口） ------------------------------------


def test_no_detector_depends_on_line_breaks():
    """同一段话，断行与否不得改变得分。

    这是 2026-10-29 三次缺陷的共同形态：short_units、specific_detail、
    declarative_close 都曾把「排版」当成「写法」。
    """
    import re as _re

    from backend.app.services.style_hypotheses import DETECTORS

    body = (
        "上周三我在公司楼下跟我妈吵了一架。她说你这样下去不行。"
        "我手心全是汗。其实不是我不努力，而是我不知道往哪走。"
        "后来我想明白了，先动起来比想清楚更重要。"
    )
    split = body.replace("。", "。\n")
    for name, detector in DETECTORS.items():
        if name.startswith("hook_"):
            continue  # 标题级检测器，输入是标题
        a = detector(body)
        b = detector(split)
        assert a == b, f"{name} 受断行影响：{a} vs {b}"


def test_no_detector_scores_by_pronoun_density():
    """只有人称、没有任何可核验信息的文本，不应被当成"有细节/有对话"。"""
    from backend.app.services.style_hypotheses import DETECTORS

    pronoun_soup = "他说他很累。她说她不在乎。我觉得他们都是好人。我妈总是这样。"
    assert DETECTORS["specific_detail"](pronoun_soup) == 0.0
    assert DETECTORS["quoted_speech"](pronoun_soup) == 0.0
