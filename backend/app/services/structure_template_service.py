"""Structure templates: what goes at the opening, middle and close.

The old template builder counted words and frequencies, which loses order: two
posts with the same elements but a different sequence produced the same template.
This one measures positions:

* opening — the first content unit, classified by hook type
* middle — steps / list / single-topic
* closing — CTA / resource / judgement / none

The output is a skeleton with percentages, plus the most common combination.
It describes content expression, not personal voice.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from backend.app.services.excel_hypotheses import (
    detect_excel_failure,
    detect_excel_taunt,
)
from backend.app.services.spoken_hypotheses import (
    detect_hook_audience,
    detect_hook_authority,
    detect_hook_curiosity,
    detect_hook_number,
    detect_hook_question,
    detect_hook_story,
)
from backend.app.services.style_evidence import CorpusDoc
from backend.app.services.writing_signals import content_units

_OPENING_RULES: list[tuple[str, Any]] = [
    ("反问/嘲讽", detect_excel_taunt),
    ("疑问句", detect_hook_question),
    ("点名受众", detect_hook_audience),
    ("数字清单", detect_hook_number),
    ("故事/时间", detect_hook_story),
    ("权威背书", detect_hook_authority),
    ("悬念", detect_hook_curiosity),
]

_STEPS = re.compile(r"(第[一二三四五]步|首先|然后|接着|最后|点击|选择|输入|选中)")
_LIST = re.compile(r"(这个可以|第一个|第一款|一是|二是|三款|五个|几种)")
_CTA = ("点赞", "收藏", "关注", "评论区", "学会了吗", "转发", "双击", "私信")
_RESOURCE = ("整理好了", "全套", "领取", "评论区打", "私信我", "发给你", "免费送")
_TAG_ONLY = re.compile(r"^(?:#[^#\s]+\s*)+$")
# The hypothesis detector for 「失败场景」 is deliberately narrow: it validates
# the exact "让你…结果…" form used in the corpus statistics. A structure
# template is broader — "排序按钮点了没反应" or "弹出报错" is the same opening
# move even without that syntax. Using the narrow detector here would mark a
# draft that followed the template as a miss.
_PROBLEM = re.compile(
    r"(没反应|没成功|报错|错误|失败|不能|无法|不对|乱了|全乱|打不开|卡住|崩溃|"
    r"弹.{0,8}一句|弹窗|提示.{0,12}(错误|失败)|踩坑|坑过|头疼|麻烦|纹丝不动)"
)
# A failure scene can also be "结果文字跑到下一行 / 按删除却把上面删了".
# This is deliberately separate from the hypothesis detector: the template
# classifier cares about the opening move, not the exact corpus phrasing.
_FAILURE_SCENE = re.compile(
    r"(结果|却|居然|反而).{0,24}(删|跑|跳|乱|不动|只能|复制|粘贴|报错|没反应|卡|失败)"
)
# Positive evidence for a direct conclusion. Without this, the old fallback
# silently turned every unrecognized opening into "直接给结论".
_DIRECT = re.compile(
    r"(教你|一招|这个可以|这个是|只需|以前用|现在用|Ctrl|Alt|Shift|快捷键|"
    r"第一个|一步|直接|就是|其实|结论|核心|记住|建议|重点是|真相)"
)
_MIDDLE_ELEMENTS: list[tuple[str, re.Pattern[str]]] = [
    ("操作步骤", _STEPS),
    (
        "效果/结果",
        re.compile(r"(这样|就能|不会再|不会报错|以后|从此|搞定|解决|省事|省很多)"),
    ),
    ("原理/原因", re.compile(r"(因为|原因|原理|本质上|其实|为什么|是因为|逻辑|核心是)")),
    (
        "易错/适用条件",
        re.compile(r"(注意|容易|踩坑|坑|如果|适合|不适合|前提|否则|小心|别急|只能|不要)"),
    ),
    (
        "备选方案",
        re.compile(r"(或者|另一种|也可以|替代|备选|还有一种|方法二|第二种|跨列居中)"),
    ),
]


def _opening_of(doc: CorpusDoc) -> tuple[str, str, float]:
    units = content_units(doc.body or "")
    head = units[0] if units else (doc.body or "")[:60]
    if (
        detect_excel_failure(head) >= 0.5
        or _PROBLEM.search(head)
        or _FAILURE_SCENE.search(head)
    ):
        return "失败场景", head, 1.0
    for label, detector in _OPENING_RULES:
        if detector(head) >= 0.5:
            return label, head, 1.0
    if _DIRECT.search(head):
        return "直接给结论", head, 0.7
    return "其他/未分类", head, 0.0


def _body_pattern(doc: CorpusDoc) -> tuple[str, float]:
    body = doc.body or ""
    if _STEPS.search(body):
        return "操作步骤", 1.0
    if _LIST.search(body):
        return "清单/并列", 1.0
    return "单点讲解", 0.5


def _closing_of(doc: CorpusDoc) -> tuple[str, str, float]:
    # A trailing hashtag line is not a closing move. Corpus bodies sometimes
    # keep it, and then every post looks like it ends on a "judgement".
    units = [
        unit for unit in content_units(doc.body or "")
        if not _TAG_ONLY.match(unit.strip())
    ]
    last = units[-1] if units else ""
    # A closing move can span the last two sentences: models often write
    # 「先收藏…」 and then append a question. Looking only at the final sentence
    # turns that into a judgement and reports a false miss.
    tail = units[-2:]
    for unit in reversed(tail):
        if any(word in unit for word in _CTA):
            return "求赞/收藏/关注", unit, 1.0
    for unit in reversed(tail):
        if any(word in unit for word in _RESOURCE):
            return "资源钩子", unit, 1.0
    if len(last.strip()) >= 6:
        # Any non-empty sentence becomes a judgement; that is a weak signal.
        return "判断/金句", last, 0.5
    return "无明确收尾", last, 0.0


def _pct(count: int, total: int) -> int:
    return round(count / total * 100) if total else 0


def _likes_of(doc: CorpusDoc) -> int:
    """Likes alone, for the low-follower ratio.

    ``engagement`` is like+collect+comment+share, which is the right unit for
    "how much response did this get" but the wrong one for "zan/fans": the public
    convention compares **likes** to followers. Using the sum would make every
    note look stronger than the ratio people actually quote.
    """
    return int(doc.meta.get("likes") or 0)


def _age_days(value: Any) -> int | None:
    from datetime import date, datetime

    from backend.app.core.time import shanghai_now

    if isinstance(value, datetime):
        published = value.date()
    elif isinstance(value, date):
        published = value
    else:
        return None
    return max(0, (shanghai_now().date() - published).days)


def analyze_middle_elements(docs: list[CorpusDoc]) -> list[dict[str, Any]]:
    """Count the recurring elements inside the body, not just its shape.

    These are descriptive corpus frequencies. They are kept separate from the
    optional quality enhancement: a draft may add a caveat or an alternative
    because it is more useful, even when the corpus rarely does.
    """
    usable = [doc for doc in docs if len((doc.body or "").strip()) >= 40]
    total = len(usable)
    results: list[dict[str, Any]] = []
    for label, pattern in _MIDDLE_ELEMENTS:
        count = sum(1 for doc in usable if pattern.search(doc.body or ""))
        if count:
            results.append({"label": label, "count": count, "pct": _pct(count, total)})
    return results


def _top(counter: Counter[str], total: int, n: int = 3) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count, "pct": _pct(count, total)}
        for label, count in counter.most_common(n)
    ]


def _tags(titles: Iterable[str]) -> list[str]:
    counter: Counter[str] = Counter()
    for title in titles:
        for tag in re.findall(r"#([^#\s]+)", title or ""):
            counter[tag] += 1
    return [tag for tag, _ in counter.most_common(10)]


def _expected_labels(template: dict[str, Any], position: str, limit: int = 2) -> list[str]:
    labels: list[str] = []
    for item in template.get(position) or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def check_structure_coverage(
    text: str,
    template: dict[str, Any],
    *,
    title: str = "",
) -> dict[str, Any]:
    """Measure a generated draft against the template's three positions.

    ``coverage`` is strict: the draft must use the most common label at each
    position. ``soft_coverage`` also accepts the runner-up, because a template
    describes a distribution, not a single allowed shape. Both are reported so
    a low strict score is not mistaken for a broken draft.
    """
    body = (text or "").strip()
    if len(body) < 40:
        raise ValueError("正文至少 40 字才能判断结构。")
    if not isinstance(template, dict) or template.get("kind") != "positional":
        raise ValueError("这个模板不是按开头/中段/结尾拆的位置模板。")

    doc = CorpusDoc(key="draft", title=title, body=body)
    opening_label, _, opening_confidence = _opening_of(doc)
    body_label, body_confidence = _body_pattern(doc)
    closing_label, _, closing_confidence = _closing_of(doc)
    actual = {
        "opening": opening_label,
        "body": body_label,
        "closing": closing_label,
    }
    confidences = {
        "opening": opening_confidence,
        "body": body_confidence,
        "closing": closing_confidence,
    }

    positions: list[dict[str, Any]] = []
    strict = 0
    soft = 0
    for position in ("opening", "body", "closing"):
        expected = _expected_labels(template, position)
        if not expected:
            continue
        detected = actual[position]
        strict_match = detected == expected[0]
        soft_match = detected in expected
        strict += int(strict_match)
        soft += int(soft_match)
        positions.append(
            {
                "position": position,
                "detected": detected,
                "expected": expected[0],
                "alternatives": expected[1:],
                "strict_match": strict_match,
                "soft_match": soft_match,
                "confidence": confidences[position],
            }
        )

    total = len(positions)
    skeletons = [
        str(item.get("label") or "")
        for item in (template.get("skeletons") or [])
        if isinstance(item, dict) and item.get("label")
    ][:3]
    actual_skeleton = " → ".join(actual[position] for position in ("opening", "body", "closing"))

    patterns = dict(_MIDDLE_ELEMENTS)
    middle_elements: list[dict[str, Any]] = []
    for item in template.get("middle_elements") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        label = str(item["label"])
        pattern = patterns.get(label)
        middle_elements.append(
            {
                "label": label,
                "pct": item.get("pct"),
                "present": bool(pattern.search(body)) if pattern else False,
            }
        )
    middle_present = sum(1 for item in middle_elements if item["present"])

    return {
        "coverage": _pct(strict, total),
        "soft_coverage": _pct(soft, total),
        "matched": strict,
        "soft_matched": soft,
        "total": total,
        "positions": positions,
        "actual_skeleton": actual_skeleton,
        "expected_skeletons": skeletons,
        "skeleton_match": actual_skeleton in skeletons,
        "middle_elements": middle_elements,
        "middle_element_coverage": (
            _pct(middle_present, len(middle_elements)) if middle_elements else None
        ),
    }


def build_structure_template(
    docs: list[CorpusDoc],
    *,
    name: str = "",
    rule: "LowFollowerRule | None" = None,
) -> dict[str, Any]:
    """Build a position-aware structure template from a corpus.

    ``rule`` selects which documents count as the corpus. Without it this used to
    take *every* document with 40+ characters, which made a template the average
    layout of a 181,811-like post and a 2-like post — neither a breakout pattern
    nor an author's voice. Because ``CorpusDoc.engagement`` was collected but never
    read, the output looked identical regardless of whether the input was all hits
    or all misses.

    With a rule, only notes that qualify as low-follower breakouts are measured,
    and the count that were excluded is reported so the result cannot be mistaken
    for "everything in this corpus".
    """
    from backend.app.services.low_follower import (
        MIN_TEMPLATE_DOCS,
        describe_miss,
    )

    active = rule
    candidates = [doc for doc in docs if len((doc.body or "").strip()) >= 40]

    selected: list[CorpusDoc] = []
    unmeasured = 0
    if active is None:
        # No rule: keep the historical behaviour of measuring every usable doc.
        # The HTTP layer defaults to ``low_follower``; this default exists so
        # direct callers and existing tests do not silently change meaning.
        selected = candidates
    else:
        for doc in candidates:
            fans = int(doc.meta.get("author_fans") or 0)
            known = bool(doc.meta.get("fans_known"))
            likes = _likes_of(doc)
            if not known or fans <= 0:
                unmeasured += 1
                continue
            days = _age_days(doc.meta.get("published_at"))
            if active.accepts(fans, likes, days):
                selected.append(doc)

        if len(selected) < MIN_TEMPLATE_DOCS:
            message = describe_miss(
                total=len(candidates),
                measured=len(candidates) - unmeasured,
                passed=len(selected),
                rule=active,
            )
            raise ValueError(message or f"符合条件的样本不足 {MIN_TEMPLATE_DOCS} 篇。")

    usable = selected
    if len(usable) < MIN_TEMPLATE_DOCS:
        raise ValueError("至少需要 3 篇可用文稿才能提取结构模板。")

    openings: Counter[str] = Counter()
    bodies: Counter[str] = Counter()
    closings: Counter[str] = Counter()
    opening_examples: dict[str, str] = {}
    closing_examples: dict[str, str] = {}
    skeletons: Counter[str] = Counter()

    for doc in usable:
        opening, opening_text, _opening_confidence = _opening_of(doc)
        body, _body_confidence = _body_pattern(doc)
        closing, closing_text, _closing_confidence = _closing_of(doc)
        openings[opening] += 1
        bodies[body] += 1
        closings[closing] += 1
        opening_examples.setdefault(opening, opening_text)
        closing_examples.setdefault(closing, closing_text)
        skeletons[f"{opening} → {body} → {closing}"] += 1

    total = len(usable)
    top_open = _top(openings, total)
    top_body = _top(bodies, total)
    top_close = _top(closings, total)
    top_skeleton = [
        {"label": label, "count": count, "pct": _pct(count, total)}
        for label, count in skeletons.most_common(3)
    ]
    middle_elements = analyze_middle_elements(usable)

    structure: list[str] = [
        f"开头：{top_open[0]['label']}（{top_open[0]['pct']}%）"
        + (f"，其次 {top_open[1]['label']}（{top_open[1]['pct']}%）" if len(top_open) > 1 else "")
        + f"。例：{opening_examples.get(top_open[0]['label'], '')[:40]}",
        f"中段：{top_body[0]['label']}（{top_body[0]['pct']}%）"
        + (f"，其次 {top_body[1]['label']}（{top_body[1]['pct']}%）" if len(top_body) > 1 else ""),
        f"结尾：{top_close[0]['label']}（{top_close[0]['pct']}%）"
        + f"。例：{closing_examples.get(top_close[0]['label'], '')[:40]}",
        f"最常见组合：{top_skeleton[0]['label']}（{top_skeleton[0]['pct']}%）",
    ]

    recommendations = [
        f"开头优先用「{top_open[0]['label']}」，覆盖 {top_open[0]['pct']}%；"
        + (f"其次「{top_open[1]['label']}」{top_open[1]['pct']}%。" if len(top_open) > 1 else ""),
        f"中段以「{top_body[0]['label']}」为主，覆盖 {top_body[0]['pct']}%。",
        f"结尾用「{top_close[0]['label']}」，覆盖 {top_close[0]['pct']}%。",
    ]

    return {
        "version": 1,
        "kind": "positional",
        "name": name,
        "documents": total,
        "source_count": total,
        "opening": top_open,
        "body": top_body,
        "closing": top_close,
        "skeletons": top_skeleton,
        "middle_elements": middle_elements,
        "structure": structure,
        # Opening labels are not title formulas. A positional template has no
        # title analysis, so leave this empty instead of mislabelling the first
        # structure position.
        "title_formulas": [],
        "keywords": [],
        "hashtags": _tags(doc.title for doc in usable),
        "example_titles": [doc.title for doc in usable[:3]],
        "cta_examples": [text for text in closing_examples.values() if text][:3],
        "note_summaries": [],
        "common_hook_patterns": [],
        "recommendations": recommendations,
        # Which notes this template was actually built from. Without this the
        # number "104 篇" and "21 篇" look the same in the UI, and a template
        # computed from every note (hits and misses averaged together) is
        # indistinguishable from one built from breakouts only.
        "selection": (
            {
                "rule": active.label(),
                "max_fans": active.max_fans,
                "min_likes": active.min_likes,
                "min_like_fan_ratio": active.min_like_fan_ratio,
                "within_days": active.within_days,
                "candidates": len(candidates),
                "selected": len(selected),
                "excluded_unmeasured": unmeasured,
                "excluded_by_rule": len(candidates) - unmeasured - len(selected),
            }
            if active is not None
            else {
                "rule": "全部（未按低粉爆款筛选）",
                "candidates": len(candidates),
                "selected": len(selected),
                "excluded_unmeasured": 0,
                "excluded_by_rule": 0,
            }
        ),
        "avg_score": 0,
    }


__all__ = ["build_structure_template", "check_structure_coverage"]
