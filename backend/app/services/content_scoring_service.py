"""Deterministic content scoring for Xiaohongshu titles and notes.

No model calls: the scores are explainable rules, so they are free, instant and
testable. Six dimensions each, 100 points total.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.writing_signals import (
    OPERATION_CTAS,
    closing_moves,
    evidence_signals,
    generic_ratio,
    information_density,
)

DIGIT_RE = re.compile(r"\d")
NUMBER_WORD_RE = re.compile(r"[一二三四五六七八九十百千万半]+")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
HASHTAG_RE = re.compile(r"#([^#\s]{1,30})#?")

QUESTION_WORDS = ("为什么", "怎么", "如何", "哪些", "哪个", "吗", "呢", "？", "?")
HOOK_WORDS = (
    "别再", "千万别", "后悔", "踩坑", "避雷", "真相", "居然", "竟然", "原来", "终于",
    "第一次", "最后一次", "秘密", "隐藏", "后悔没早", "亲测", "实测", "翻车", "救命",
)
IDENTITY_WORDS = (
    "打工人", "上班族", "学生党", "宝妈", "宝爸", "新手", "小白", "普通人", "社恐",
    "敏感肌", "油皮", "干皮", "微胖", "小个子", "梨形", "学生", "应届", "自由职业",
    "程序员", "设计师", "运营", "博主", "主妇", "租房", "独居", "宝妈", "北漂",
)
CTA_WORDS = ("评论区", "留言", "告诉我", "你更", "你会", "收藏", "码住", "试试", "抄作业", "交作业")
BANNED_WORDS = ("最好", "第一", "绝对", "100%", "永久", "国家级", "顶级", "唯一", "最便宜", "包治")
STRUCTURE_MARKERS = ("1", "2", "3", "①", "②", "③", "✅", "•", "-", "步骤", "第", "首先", "其次", "最后")
AI_FLAVOR_WORDS = (
    "首先",
    "其次",
    "最后",
    "综上",
    "总而言之",
    "值得注意的是",
    "不难发现",
    "在这个",
    "赋能",
    "闭环",
    "底层逻辑",
    "认知升级",
    "情绪价值",
    "颗粒度",
    "抓手",
    "打法",
    "复利",
)
REAL_DETAIL_WORDS = ("我", "昨天", "上周", "去年", "朋友", "当时", "有一次", "后来", "那天", "早上", "晚上")


def skill_alignment_check(
    title: str, body: str, tags: list[str] | None = None
) -> list[dict[str, str]]:
    """Heuristic checks aligned with the imported WorkBuddy skills.

    These are *not* extra scores; they are the concrete checks from
    ``wb-xhs-humanize-compliance`` and ``wb-xhs-topic-bank``, surfaced so the
    user can see whether the draft follows the enabled methodology.
    """
    text = (body or "").strip()
    first = re.split(r"[\n。！？!?]", text)[0] if text else ""
    paragraphs = [line for line in text.split("\n") if line.strip()]
    checks: list[dict[str, str]] = []

    opening_ok = bool(first) and len(first) <= 100 and any(
        word in first for word in (*HOOK_WORDS, *IDENTITY_WORDS, *QUESTION_WORDS)
    )
    checks.append(
        {
            "key": "opening_5s",
            "label": "5 秒开头",
            "status": "pass" if opening_ok else "warn",
            "detail": "第一段包含钩子/身份/问题，能独立成立"
            if opening_ok
            else "第一段偏长或没有钩子，离开正文就不知道要讲什么",
        }
    )

    mechanisms = sum(1 for marker in STRUCTURE_MARKERS if marker in text)
    single_ok = len(paragraphs) <= 6 and mechanisms <= 5
    checks.append(
        {
            "key": "single_mechanism",
            "label": "单一核心机制",
            "status": "pass" if single_ok else "warn",
            "detail": "段落和要点数量可控，读者能复述讲了一件什么事"
            if single_ok
            else "段落/要点过多，建议只保留一个主机制，其余降为证据",
        }
    )

    detail_hits = len(re.findall(r"\d", text)) + sum(
        1 for word in REAL_DETAIL_WORDS if word in text
    )
    detail_ok = detail_hits >= 3
    checks.append(
        {
            "key": "real_detail",
            "label": "真人材料",
            "status": "pass" if detail_ok else "warn",
            "detail": "有具体时间/数字/经历/对话等细节"
            if detail_ok
            else "偏抽象，建议补一个真实场景、数字或对话",
        }
    )

    flavor_hits = [word for word in AI_FLAVOR_WORDS if word in text]
    flavor_ok = len(flavor_hits) <= 2
    checks.append(
        {
            "key": "humanize",
            "label": "去 AI 味",
            "status": "pass" if flavor_ok else "warn",
            "detail": "书面连接词和空泛概念较少"
            if flavor_ok
            else "出现较多书面/概念词：" + "、".join(flavor_hits[:5]),
        }
    )

    try:
        from backend.app.services.sensitive_word_service import check_local

        sensitive = check_local("\n".join([title, text, " ".join(tags or [])]))
        hit_count = int(sensitive.get("hit_count") or 0)
    except Exception:  # noqa: BLE001 - never block scoring on the checker
        hit_count = 0
    checks.append(
        {
            "key": "compliance",
            "label": "发布前合规",
            "status": "pass" if hit_count == 0 else "warn",
            "detail": "本地敏感词检查未命中" if hit_count == 0 else f"命中 {hit_count} 个候选词，需人工判断",
        }
    )
    return checks



def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _dimension(key: str, name: str, score: float, maximum: float, advice: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "score": round(_clamp(score, 0, maximum), 1),
        "max": maximum,
        "advice": advice,
    }


def score_title(title: str, body: str = "") -> dict[str, Any]:
    text = (title or "").strip()
    length = len(text)
    body_text = body or ""
    dimensions: list[dict[str, Any]] = []

    # 1) 长度
    if 12 <= length <= 22:
        dim_score, advice = 15, "长度合适"
    elif 8 <= length <= 28:
        dim_score, advice = 10, "建议控制在 12–22 字"
    else:
        dim_score, advice = 4, "标题过长或过短，建议 12–22 字"
    dimensions.append(_dimension("length", "长度", dim_score, 15, advice))

    # 2) 具体性
    has_digit = bool(DIGIT_RE.search(text) or NUMBER_WORD_RE.search(text))
    if has_digit:
        dim_score, advice = 15, "有数字/时间，具体可感"
    elif any(word in text for word in ("个", "种", "步", "天", "元", "分钟")):
        dim_score, advice = 9, "可以再加一个具体数字"
    else:
        dim_score, advice = 3, "加入数字或时间（如 3 个方法、5 分钟）"
    dimensions.append(_dimension("specific", "具体性", dim_score, 15, advice))

    # 3) 钩子
    hook_hits = [word for word in HOOK_WORDS if word in text]
    question = any(word in text for word in QUESTION_WORDS)
    if hook_hits and question:
        dim_score = 20
    elif hook_hits or question:
        dim_score = 15
    elif any(word in text for word in ("方法", "教程", "攻略", "清单")):
        dim_score = 10
    else:
        dim_score = 5
    dimensions.append(
        _dimension("hook", "钩子强度", dim_score, 20, "加疑问/反差/避雷类钩子更抓眼" if dim_score < 15 else "钩子不错")
    )

    # 4) 人群/身份
    identity_hits = [word for word in IDENTITY_WORDS if word in text]
    if identity_hits:
        dim_score, advice = 15, f"人群标签清晰（{identity_hits[0]}）"
    elif any(word in text for word in ("人", "党", "族")):
        dim_score, advice = 8, "人群可以更具体（如 打工人/学生党）"
    else:
        dim_score, advice = 3, "加一个身份标签，代入感更强"
    dimensions.append(_dimension("identity", "人群代入", dim_score, 15, advice))

    # 5) 搜索价值（与正文关键词重合）
    if body_text:
        title_grams = {text[index : index + 2] for index in range(max(0, len(text) - 1))}
        body_grams = {body_text[index : index + 2] for index in range(max(0, len(body_text) - 1))}
        overlap = len(title_grams & body_grams) / max(len(title_grams), 1)
        dim_score = _clamp(overlap * 30, 0, 15)
        advice = "标题与正文关键词呼应" if dim_score >= 9 else "标题关键词和正文偏离，注意搜索命中"
    else:
        dim_score, advice = 8, "提供正文后可评估关键词呼应"
    dimensions.append(_dimension("search", "搜索价值", dim_score, 15, advice))

    # 6) 风险与可读性
    risk_hits = [word for word in BANNED_WORDS if word in text]
    emoji_count = len(EMOJI_RE.findall(text))
    dim_score = 20
    notes: list[str] = []
    if risk_hits:
        dim_score -= 10 * min(len(risk_hits), 2)
        notes.append(f"极限词：{'、'.join(risk_hits[:3])}")
    if emoji_count > 3:
        dim_score -= 3
        notes.append("emoji 偏多")
    if length > 30:
        dim_score -= 3
        notes.append("过长")
    if not notes:
        notes.append("无风险词，可读性好")
    dimensions.append(_dimension("risk", "风险与可读性", dim_score, 20, "；".join(notes)))

    total = round(sum(item["score"] for item in dimensions), 1)
    grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C"
    suggestions = [item["advice"] for item in dimensions if item["score"] < item["max"] * 0.7]
    return {
        "title": text,
        "score": total,
        "grade": grade,
        "dimensions": dimensions,
        "suggestions": suggestions[:4] or ["标题结构完整，可以直接用"],
    }


def score_note(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    text = (body or "").strip()
    title_result = score_title(title, text)
    dimensions: list[dict[str, Any]] = []

    dimensions.append(
        _dimension(
            "title",
            "标题",
            title_result["score"] * 0.2,
            20,
            "标题评分见右侧明细" if title_result["score"] >= 70 else "标题偏弱，建议用数字+人群+结果",
        )
    )

    # 开头钩子：按「有没有抓手」判断，而不是只认词表。
    # 旧实现只匹配 别再/踩坑/后悔/原来 等词，导致「我今天想讲一个和全网都对抗
    # 的观点」「去年冬天我和伴侣爆发过一次巨大冲突」这类开场直接得 0 分——它们
    # 有明显抓手，只是不用那些词。
    first_paragraph = re.split(r"[\n。！？!?]", text)[0] if text else ""
    opening_points = 0.0
    if any(word in first_paragraph for word in (*HOOK_WORDS, *IDENTITY_WORDS, *QUESTION_WORDS)):
        opening_points += 0.45
    if evidence_signals(first_paragraph):
        # 具体到时间/人物/场景/原话，本身就是钩子
        opening_points += 0.35
    if re.search(r"(不是.{1,12}而是|反而|其实|全网|大家都在|大多数人)", first_paragraph):
        opening_points += 0.30
    if 0 < len(first_paragraph) <= 60:
        opening_points += 0.10
    dim_score = round(_clamp(opening_points * 15, 0, 15), 1)
    dimensions.append(
        _dimension(
            "opening",
            "开头钩子",
            dim_score,
            15,
            "开头给一个具体场景、反常识结论或明确承诺，不要从背景铺垫开始" if dim_score < 10 else "开头有抓手",
        )
    )

    # 结构
    paragraphs = [line for line in text.split("\n") if line.strip()]
    marker_hits = sum(1 for marker in STRUCTURE_MARKERS if marker in text)
    if len(paragraphs) >= 3 and marker_hits >= 2:
        dim_score = 20
    elif len(paragraphs) >= 2 and marker_hits >= 1:
        dim_score = 14
    elif len(paragraphs) >= 2:
        dim_score = 9
    else:
        dim_score = 4
    dimensions.append(
        _dimension("structure", "结构", dim_score, 20, "拆成 3–5 个要点，配小标题或序号" if dim_score < 14 else "结构清晰")
    )

    # 信息密度：按「每句是否新增可核验信息点」算，不按字数算。
    # 旧实现把 200–900 字直接判满分，导致一段正确但空洞的排比也能拿满；
    # 而真正信息密集的短稿（如 300 字写清一件事）反而因为字数不够被扣分。
    char_count = len(re.sub(r"\s", "", text))
    density = information_density(text)
    generic = generic_ratio(text)
    density_score = round(_clamp(density * 15, 0, 15), 1)
    if generic >= 0.4:
        density_score = max(0.0, density_score - 4)
    dimensions.append(
        _dimension(
            "density",
            "信息密度",
            density_score,
            15,
            (
                f"当前 {char_count} 字，可核验信息点占比 {density:.0%}"
                + ("；空泛句偏多，换成具体场景/数字/原话" if generic >= 0.4 else "")
            )
            if density_score < 10
            else f"信息密度好（可核验信息点 {density:.0%}）",
        )
    )

    # 互动引导：运营型 CTA 或有效收束都算。
    # 旧实现只认 收藏/评论/关注 等词，金句结尾（「我永远忠诚于我自己」）得 3 分，
    # 等于逼模型给每篇都加一句销售话术。
    ends_with_question = bool(text) and text.rstrip()[-1:] in {"？", "?"}
    moves = closing_moves(text)
    operation = set(moves) & set(OPERATION_CTAS)
    if operation and ends_with_question:
        dim_score = 15.0
    elif operation:
        dim_score = 12.0
    elif len(moves) >= 2:
        dim_score = 11.0
    elif moves:
        dim_score = 9.0
    elif ends_with_question:
        dim_score = 8.0
    else:
        dim_score = 3.0
    dimensions.append(
        _dimension(
            "cta",
            "互动引导",
            dim_score,
            15,
            "结尾给一个可执行动作、一句金句或一个具体问题" if dim_score < 10 else "结尾有收束设计",
        )
    )

    # 标签
    tag_list = list(tags or []) or HASHTAG_RE.findall(text)
    tag_count = len([tag for tag in tag_list if tag])
    if 3 <= tag_count <= 8:
        dim_score = 15
    elif tag_count:
        dim_score = 9
    else:
        dim_score = 3
    dimensions.append(
        _dimension("tags", "话题标签", dim_score, 15, f"当前 {tag_count} 个，建议 3–8 个（大词+精准词+场景词）")
    )

    total = round(sum(item["score"] for item in dimensions), 1)
    grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C"
    suggestions = [item["advice"] for item in dimensions if item["score"] < item["max"] * 0.7]
    return {
        "title": title,
        "score": total,
        "grade": grade,
        "char_count": char_count,
        "dimensions": dimensions,
        "title_detail": title_result,
        "suggestions": suggestions[:5] or ["整体结构完整，可以发布"],
        "skill_alignment": skill_alignment_check(title, text, tag_list),
    }


__all__ = ["score_note", "score_title", "skill_alignment_check"]
