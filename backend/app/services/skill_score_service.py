from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AiDraft, DraftAsset, User
from backend.app.services.content_scoring_service import skill_alignment_check
from backend.app.services.writing_signals import (
    OPERATION_CTAS,
    closing_moves,
    evidence_points,
    evidence_signals,
    split_sentences,
)

FORMAT_LONG = "long_text"
FORMAT_SHORT = "short_copy"
FORMAT_LIST = "list"
FORMAT_VIDEO = "video"
FORMAT_CASE = "case_story"
FORMAT_UNKNOWN = "unknown"

FORMAT_LABELS = {
    FORMAT_LONG: "图文长文",
    FORMAT_SHORT: "图文短文案",
    FORMAT_LIST: "清单/合集",
    FORMAT_VIDEO: "视频",
    FORMAT_CASE: "案例/复盘",
    FORMAT_UNKNOWN: "未识别",
}

CRAFT_RUBRICS: dict[str, list[tuple[str, str, float]]] = {
    FORMAT_LONG: [
        ("title_hook", "标题钩子", 20),
        ("cover", "封面", 10),
        ("opening", "开头", 15),
        ("structure", "结构", 20),
        ("evidence", "具体证据", 15),
        ("cta", "CTA", 10),
        ("tags", "标签", 10),
    ],
    FORMAT_SHORT: [
        ("title_hook", "标题钩子", 30),
        ("cover", "封面", 25),
        ("opening", "开头", 15),
        ("evidence", "具体证据", 15),
        ("cta", "CTA", 10),
        ("tags", "标签", 5),
    ],
    FORMAT_LIST: [
        ("title_hook", "标题钩子", 20),
        ("cover", "封面", 15),
        ("structure", "清单清晰度", 25),
        ("evidence", "具体证据", 20),
        ("cta", "CTA", 10),
        ("tags", "标签", 10),
    ],
    FORMAT_VIDEO: [
        ("title_hook", "标题钩子", 20),
        ("cover", "封面", 20),
        ("opening", "前 3 秒/开头", 20),
        ("structure", "节奏/信息推进", 15),
        ("cta", "CTA", 15),
        ("tags", "标签", 10),
    ],
    FORMAT_CASE: [
        ("title_hook", "标题钩子", 20),
        ("opening", "开头/结果前置", 15),
        ("evidence", "可信度/证据", 25),
        ("structure", "过程/可复用点", 20),
        ("cta", "CTA", 10),
        ("tags", "标签", 10),
    ],
    FORMAT_UNKNOWN: [
        ("title_hook", "标题钩子", 25),
        ("cover", "封面", 15),
        ("opening", "开头", 15),
        ("evidence", "具体证据", 15),
        ("cta", "CTA", 15),
        ("tags", "标签", 15),
    ],
}

EXTREME_WORDS = ("最好", "第一", "绝对", "100%", "永久", "包赚", "稳赚", "国家级", "顶级", "唯一")
PILLAR_WORDS = ("AI", "人工智能", "一人公司", "OPC", "独立开发", "副业", "宁波", "Skills", "vibecoding")
PAIN_WORDS = ("不会", "难", "贵", "没时间", "焦虑", "卡住", "踩坑", "避雷", "翻车", "看不懂", "学不会")
RESULT_WORDS = ("省", "赚", "交付", "跑通", "做到", "提升", "从", "到", "结果", "收入", "成本")
CASE_WORDS = ("我用", "实测", "亲测", "案例", "客户", "交付", "复盘", "踩坑", "真实", "经历")
IDENTITY_WORDS = ("普通人", "打工人", "新手", "小白", "宝妈", "学生党", "独立开发", "一人公司", "创业者", "自由职业")
HOOK_WORDS = ("别再", "千万别", "后悔", "踩坑", "避雷", "真相", "居然", "竟然", "原来", "终于", "亲测", "实测", "翻车")
CTA_WORDS = {
    "save": ("收藏", "码住", "先收藏"),
    "comment": ("评论", "留言", "告诉我", "你们觉得", "欢迎讨论"),
    "follow": ("关注", "点个关注", "记得关注"),
    "private": ("私信", "私我", "后台回复", "报名", "滴滴"),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _grade(total: float) -> str:
    return "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C"


def _dimension(key: str, name: str, ratio: float, maximum: float, advice: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "score": round(_clamp01(ratio) * maximum, 1),
        "max": maximum,
        "advice": advice,
    }


def _skill_weight_multipliers(skill) -> dict[str, float]:
    """Read data-evolved weight multipliers from the active style.

    Accepts either the StyleProfile-backed view or a plain dict, so this keeps
    working after the CreationSkill layer was removed.
    """
    if skill is None:
        return {}
    raw = {}
    if isinstance(skill, dict):
        raw = skill.get("weight_multipliers") or {}
    else:
        raw = (getattr(skill, "structured_json", None) or {}).get("weight_multipliers") or {}
    if not isinstance(raw, dict):
        return {}
    multipliers: dict[str, float] = {}
    for key, value in raw.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if 0.5 <= number <= 2.0:
            multipliers[str(key)] = number
    return multipliers


def _active_skill(db: Session, user: User, account_id: int | None):
    """The account's active writing style (StyleProfile-backed view)."""
    from backend.app.services.account_context_service import active_creation_skill

    return active_creation_skill(db, user, account_id)


def detect_format(
    title: str,
    body: str,
    *,
    note_type: str = "",
    image_count: int = 0,
    has_video: bool = False,
) -> str:
    kind = (note_type or "").lower()
    if has_video or "video" in kind or "视频" in kind:
        return FORMAT_VIDEO
    text = f"{title or ''}\n{body or ''}"
    compact = re.sub(r"\s", "", body or "")
    list_hits = len(re.findall(r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●])\s*", body or "", re.M))
    case_hits = sum(1 for word in CASE_WORDS if word in text)
    if list_hits >= 2:
        return FORMAT_LIST
    if case_hits >= 2:
        return FORMAT_CASE
    if len(compact) < 200:
        return FORMAT_SHORT
    return FORMAT_LONG


def _note_type_and_images(note: Any) -> tuple[str, int, bool]:
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    card: dict[str, Any] = {}
    if isinstance(raw.get("note_card"), dict):
        card = raw["note_card"]
    elif isinstance(raw.get("note"), dict):
        card = raw["note"]
    else:
        data = raw.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            # 详情接口的 items 在顶层
            items = raw.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            item = items[0]
            if isinstance(item.get("note_card"), dict):
                card = item["note_card"]
            elif isinstance(item.get("note"), dict):
                card = item["note"]
    note_type = str(card.get("type") or raw.get("type") or raw.get("note_type") or "")
    image_list = card.get("image_list") or card.get("images") or raw.get("image_list") or []
    image_count = len(image_list) if isinstance(image_list, list) else 0
    has_video = bool(
        card.get("video")
        or raw.get("video_url")
        or raw.get("video_addr")
        or str(note_type).lower() == "video"
    )
    return note_type, image_count, has_video


def _draft_media(db: Session, draft: AiDraft) -> tuple[int, bool]:
    if not draft.id:
        return 0, False
    assets = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id)).all()
    images = sum(1 for asset in assets if asset.asset_type == "image")
    has_video = any(asset.asset_type == "video" for asset in assets)
    return images, has_video


def _cover_ratio(image_count: int, has_video: bool, *, known: bool) -> float | None:
    if not known:
        return None
    if has_video:
        return 0.8
    if image_count >= 3:
        return 1.0
    if image_count >= 1:
        return 0.65
    return 0.35


def _title_ratio(title: str) -> tuple[float, str]:
    points = 0.0
    if re.search(r"\d", title) or re.search(r"[一二三四五六七八九十百千万半]", title):
        points += 0.30
    if re.search(r"[？?]|怎么|如何|为什么|哪些", title):
        points += 0.22
    if any(word in title for word in IDENTITY_WORDS):
        points += 0.18
    # 反差句式。「不是……而是……」只是其中一种，口语里更常见的是
    # 「不是X，是Y」（反复爱上同一种人，不是宿命，是创伤）。旧正则只认
    # 前一种，把她最招牌的一类标题全部判成无钩子。
    if (
        any(word in title for word in HOOK_WORDS)
        or re.search(r"不是.{1,8}(而是|才)", title)
        or re.search(r"不是.{1,14}[，,、]\s*(是|就|而)", title)
        or re.search(r"(其实|恰恰|反而|才发现|本质上)", title)
        or re.search(r"竟然|居然|原来", title)
    ):
        points += 0.22
    if re.search(r"[，,、].{2,}", title):
        # 有转折/递进结构的复合标题，比单句陈述多一点信息量
        points += 0.08
    if 0 < len(title) <= 22:
        points += 0.10
    ratio = _clamp01(points)
    advice = "标题加数字/疑问/身份/反差钩子，控制在 22 字以内。" if ratio < 0.7 else "标题钩子完整。"
    return ratio, advice


def _opening_ratio(body: str) -> tuple[float, str]:
    opening = (body or "")[:120]
    points = 0.0
    if any(word in opening for word in PAIN_WORDS):
        points += 0.30
    if any(word in opening for word in RESULT_WORDS) or re.search(r"\d", opening):
        points += 0.30
    if any(word in opening for word in IDENTITY_WORDS):
        points += 0.20
    if re.search(r"[？?]|竟然|居然|原来|不是.{1,8}而是", opening):
        points += 0.20
    ratio = _clamp01(points)
    advice = "前 2 行先给痛点、结果或反常识，不要从背景铺垫开始。" if ratio < 0.7 else "开头有明确抓手。"
    return ratio, advice


def _structure_ratio(body: str, fmt: str) -> tuple[float | None, str]:
    if fmt == FORMAT_SHORT:
        return None, "短文案不强制长文结构。"
    paragraphs = [line for line in (body or "").splitlines() if line.strip()]
    list_hits = len(re.findall(r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●])\s*", body or "", re.M))
    if fmt == FORMAT_LIST:
        ratio = min(1.0, list_hits / 5 + (0.25 if len(paragraphs) >= 3 else 0.0))
        advice = "清单要 5 条以上、每条有具体信息，不要只列名词。" if ratio < 0.7 else "清单结构清楚。"
        return ratio, advice
    if fmt == FORMAT_VIDEO:
        # No retention data here; use segmented script / short sentences as a proxy.
        ratio = 0.35 + (0.25 if list_hits >= 2 else 0.0) + (0.2 if len(paragraphs) >= 3 else 0.0)
        advice = "视频需要前 3 秒钩子、分段推进和明确结尾；补完播数据后再精确评估。"
        return _clamp01(ratio), advice
    if fmt == FORMAT_CASE:
        points = 0.25
        if re.search(r"\d", body or ""):
            points += 0.25
        if any(word in body for word in CASE_WORDS):
            points += 0.25
        if len(paragraphs) >= 3:
            points += 0.25
        advice = "案例要有结果、过程、可复用点和真实证据。" if points < 0.7 else "案例结构完整。"
        return _clamp01(points), advice
    points = 0.0
    if len(paragraphs) >= 3:
        points += 0.35
    elif len(paragraphs) >= 2:
        points += 0.20
    if list_hits >= 2:
        points += 0.30
    elif list_hits >= 1:
        points += 0.15
    compact = re.sub(r"\s", "", body or "")
    if 200 <= len(compact) <= 1500:
        points += 0.20
    if paragraphs and len(compact) / max(1, len(paragraphs)) <= 90:
        points += 0.15
    advice = "拆成 3–5 个要点，用序号/小标题，单段不超过 90 字。" if points < 0.7 else "结构清楚，可扫读。"
    return _clamp01(points), advice


def _evidence_ratio(body: str) -> tuple[float, str]:
    """Evidence = something the reader can check, not just money and screenshots.

    Rewritten because the old rule looked only for 元/小时/截图/案例, which scored
    a relational story ("他没有骂回去，反而看见了他的脆弱") at 0.30 while scoring
    filler that name-drops "成本" at 0.65. Measured on the ego corpus, that made
    good writing lose to generic advice.
    """
    points = evidence_points(body or "")
    sentences = len(split_sentences(body or "")) or 1
    # Density of evidence-bearing sentences, plus a small bonus for having a
    # mechanism/contrast at all (the part that makes a story transferable).
    density = points / sentences
    signals = set()
    for sentence in split_sentences(body or ""):
        signals.update(evidence_signals(sentence))
    if {"contrast", "mechanism"} & signals:
        density += 0.15
    if {"speech", "sensation"} & signals:
        density += 0.10
    ratio = _clamp01(density)
    if ratio < 0.7:
        advice = "补具体场景：时间、当事人、原话、身体感受，或前后对比。抽象结论不算证据。"
    else:
        advice = "证据具体。"
    return ratio, advice


def _cta_ratio(body: str) -> tuple[float, str]:
    """Closing moves, not only sales CTAs.

    The old rule credited only 收藏/评论/关注/私信 and scored a piece ending on
    「我永远忠诚于我自己」 at 0.0. That is a valid and common closing; scoring it
    zero taught the model to bolt a sales line onto every ending. Operational
    CTAs still earn full credit, they are just no longer the only way.
    """
    moves = closing_moves(body or "")
    if not moves:
        return 0.0, "结尾缺收束动作：给一个可执行动作、一句金句，或一个问题。"
    operation = set(moves) & set(OPERATION_CTAS)
    if operation:
        ratio = 1.0 if len(operation) == 1 else 0.8
        advice = "CTA 明确。"
    elif len(moves) >= 2:
        ratio = 0.85
        advice = "结尾有收束。"
    else:
        ratio = 0.7
        advice = "结尾有收束；如需转化，可再加一个明确动作。"
    return ratio, advice


def _tags_ratio(tags: list[str]) -> tuple[float, str]:
    count = len(tags)
    if 3 <= count <= 8:
        ratio = 0.85
    elif 1 <= count <= 2 or 9 <= count <= 10:
        ratio = 0.55
    elif count > 10:
        ratio = 0.35
    else:
        ratio = 0.0
    text = " ".join(tags)
    categories = sum(
        1
        for group in (
            ("AI", "人工智能", "AIGC"),
            ("一人公司", "独立开发", "副业", "OPC", "vibecoding"),
            ("普通人", "新手", "打工人", "学生党", "宝妈"),
            ("宁波", "线下", "沙龙"),
        )
        if any(word in text for word in group)
    )
    if categories >= 2:
        ratio = min(1.0, ratio + 0.15)
    advice = "3–8 个标签，至少覆盖大词 + 场景词 + 人群/本地词。" if ratio < 0.7 else "标签覆盖较完整。"
    return ratio, advice


def _fit(
    title: str,
    body: str,
    tags: list[str],
    fmt: str,
    *,
    positioning: Any = None,
) -> dict[str, Any]:
    """How well this draft fits the account, or an explicit "cannot tell".

    Every dimension here is defined against the account's positioning: content
    pillars, target audience, the account's own voice, its taboos. With no
    positioning there is nothing to compare against — and the previous version
    filled that void with hardcoded keyword lists, so any AI-topic draft scored
    10+10+25+15+10 = 70 minimum and 100 with an identity word. A draft written in
    a completely different voice still earned an S.

    A metre that cannot say "no" is not a metre. Absence is reported as absence,
    the same way ``author_fans_status`` distinguishes unknown from zero.
    """
    from backend.app.services.account_positioning_service import _clean_list, is_empty

    if positioning is None or is_empty(positioning):
        return {
            "applicable": False,
            "total": None,
            "grade": "—",
            "dimensions": [],
            "summary": "未填写账号定位，无法评估适配度",
            "reason": (
                "适配度是「这篇是否符合这个账号」，需要账号定位作为基准。"
                "现在定位是空的，任何打分都只是猜测。"
                "请先在「账号 → 定位」填写 6 个字段。"
            ),
        }

    text = f"{title}\n{body}\n{' '.join(tags)}"
    pillars = _clean_list(getattr(positioning, "main_topics", None))
    taboos = _clean_list(getattr(positioning, "taboos", None))
    audience = str(getattr(positioning, "audience", "") or "").strip()

    # Pillar: does the draft actually touch one of the account's pillars?
    hit_pillars = [p for p in pillars if p and p in text]
    pillar_score = 30 if hit_pillars else (10 if not pillars else 0)

    # Audience: does it speak to the declared reader?
    audience_terms = [w for w in re.split(r"[，,、/\s]+", audience) if len(w) >= 2]
    audience_score = 20 if any(w in text for w in audience_terms) else 0
    if not audience_terms:
        audience_score = 0

    # Style: keep the cheap signals, but they no longer stand in for the skill.
    style_score = 25
    if any(word in text for word in EXTREME_WORDS):
        style_score -= 15
    if any(word in text for word in ("我", "我们", "亲测", "实测", "复盘")):
        style_score += 5
    if any(word in text for word in ("真实", "过程", "踩坑", "成本")):
        style_score += 5
    style_score = max(0, min(25, style_score))

    format_score = 15 if fmt in {FORMAT_LONG, FORMAT_SHORT, FORMAT_LIST, FORMAT_VIDEO, FORMAT_CASE} else 8

    # Taboo: the account's own forbidden list decides, not a global word list.
    hits = [t for t in taboos if t and t in text]
    taboo_score = 0 if hits else 10

    dimensions = [
        _dimension(
            "pillar",
            "内容支柱匹配",
            pillar_score / 30,
            30,
            f"命中支柱：{'、'.join(hit_pillars[:3])}" if hit_pillars
            else (f"没有落在任何支柱上：{'、'.join(pillars[:4])}" if pillars else "定位里没写内容支柱"),
        ),
        _dimension(
            "audience",
            "目标人群匹配",
            audience_score / 20,
            20,
            "语气与目标人群一致。" if audience_score else f"没有针对目标人群表述：{audience[:30] or '未填写'}",
        ),
        _dimension(
            "style",
            "风格匹配",
            style_score / 25,
            25,
            "保持真实、具体、反鸡汤；不要极限词。" if style_score < 18 else "风格一致。",
        ),
        _dimension(
            "format",
            "形式匹配",
            format_score / 15,
            15,
            "形式已识别；低置信时按长文兜底。" if format_score < 12 else "形式明确。",
        ),
        _dimension(
            "taboo",
            "禁区检查",
            taboo_score / 10,
            10,
            f"命中禁区：{'、'.join(hits[:3])}" if hits else "未触碰定位里的禁区。",
        ),
    ]
    total = round(sum(item["score"] for item in dimensions), 1)
    return {
        "applicable": True,
        "total": total,
        "grade": _grade(total),
        "dimensions": dimensions,
        "summary": f"适配分 {total}（{_grade(total)}）",
    }


def _craft(
    title: str,
    body: str,
    tags: list[str],
    fmt: str,
    *,
    image_count: int,
    media_known: bool,
    has_video: bool,
    weight_multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    compact = re.sub(r"\s", "", body or "")
    if not compact and not tags and not has_video:
        return {
            "applicable": False,
            "format": fmt,
            "format_label": FORMAT_LABELS.get(fmt, "未识别"),
            "total": None,
            "grade": "N/A",
            "dimensions": [],
            "suggestions": ["正文和标签缺失，只有标题/封面，无法做 Craft 评分。"],
            "coverage": 0.0,
            "reason": "正文和标签缺失，数据不足。",
        }
    ratios: dict[str, tuple[float | None, str]] = {}
    ratios["title_hook"] = _title_ratio(title)
    ratios["cover"] = (None, "封面数据不足。") if fmt == FORMAT_SHORT and not media_known else (
        _cover_ratio(image_count, has_video, known=media_known),
        "封面/首图决定点击；至少 1 张清晰封面，清单类 3 张以上。" if not has_video else "视频封面要有一个明确主题。",
    )
    if fmt != FORMAT_LIST:
        opening_text = f"{title}\n{body[:120]}" if has_video else body
        ratios["opening"] = _opening_ratio(opening_text)
    if fmt != FORMAT_SHORT:
        ratios["structure"] = _structure_ratio(body, fmt)
    ratios["evidence"] = _evidence_ratio(body)
    ratios["cta"] = _cta_ratio(body)
    ratios["tags"] = _tags_ratio(tags)

    rubric = CRAFT_RUBRICS.get(fmt, CRAFT_RUBRICS[FORMAT_UNKNOWN])
    multipliers = weight_multipliers or {}
    available_weight = 0.0
    weighted = 0.0
    dimensions: list[dict[str, Any]] = []
    suggestions: list[str] = []
    for key, name, weight in rubric:
        ratio, advice = ratios.get(key, (None, "该维度不适用于当前形式。"))
        if ratio is None:
            continue
        effective_weight = weight * multipliers.get(key, 1.0)
        available_weight += effective_weight
        weighted += ratio * effective_weight
        dimensions.append(_dimension(key, name, ratio, effective_weight, advice))
        if ratio < 0.7:
            suggestions.append(advice)

    if available_weight < 40:
        return {
            "applicable": False,
            "format": fmt,
            "format_label": FORMAT_LABELS.get(fmt, "未识别"),
            "total": None,
            "grade": "N/A",
            "dimensions": dimensions,
            "suggestions": ["正文/封面数据不足，暂不做 Craft 评分；先补全正文或图片/视频。"],
            "coverage": round(available_weight, 1),
            "reason": "可用于评分的维度权重不足 40，数据不完整。",
        }

    total = round(weighted / available_weight * 100, 1)
    return {
        "applicable": True,
        # Named for what it is: a generic writing rubric, not a fit judgement.
        # It has no knowledge of the account or the author, so a draft that
        # imitates the author's actual habits (no numeric title, no emoji) can
        # score *lower* here than a generic one. Calling it "Craft" next to
        # "适配度" implied both measured the same thing.
        "scope": "generic",
        "scope_label": "通用写作规范",
        "scope_note": (
            "只看通用写作规范（钩子、结构、证据、CTA、标签），"
            "不考虑账号定位与作者风格；风格一致性请看「适配度」。"
        ),
        "format": fmt,
        "format_label": FORMAT_LABELS.get(fmt, "未识别"),
        "total": total,
        "grade": _grade(total),
        "dimensions": dimensions,
        "suggestions": suggestions[:5] or ["整体符合当前形式的执行标准。"],
        "coverage": round(available_weight, 1),
        "reason": "",
    }


def score_draft_with_skill(
    db: Session,
    user: User,
    draft: AiDraft,
    *,
    format_hint: str | None = None,
    image_count_hint: int | None = None,
    has_video_hint: bool | None = None,
) -> dict[str, Any]:
    skill = _active_skill(db, user, draft.platform_account_id)
    title = (draft.title or "").strip()
    body = (draft.body or "").strip()
    tags = [str(tag).strip() for tag in (draft.tags or []) if str(tag).strip()]
    draft_images, draft_video = _draft_media(db, draft)
    image_count = image_count_hint if image_count_hint is not None else draft_images
    has_video = has_video_hint if has_video_hint is not None else draft_video
    media_known = image_count_hint is not None or draft_images > 0 or has_video
    fmt = format_hint or detect_format(title, body, image_count=image_count, has_video=has_video)
    from backend.app.services.account_positioning_service import get_positioning

    positioning = get_positioning(db, user, draft.platform_account_id)
    fit = _fit(title, body, tags, fmt, positioning=positioning)
    craft = _craft(
        title,
        body,
        tags,
        fmt,
        image_count=image_count,
        media_known=media_known,
        has_video=has_video,
        weight_multipliers=_skill_weight_multipliers(skill),
    )
    summary = (
        (fit["summary"] if fit.get("applicable") else "适配度：未填写账号定位，无法评估")
        + " · "
        + (
            f"通用规范 {craft['total']}（{craft['grade']}）"
            if craft["applicable"]
            else "通用规范暂不适用"
        )
        + (f" · {skill.name} {skill.version}" if skill else " · 未配置 Skill，使用默认规则")
    )
    return {
        "draft_id": draft.id,
        "skill": (
            {
                "id": skill.id,
                "name": skill.name,
                "version": skill.version,
                "account_id": skill.account_id,
            }
            if skill
            else None
        ),
        "format": fmt,
        "format_label": FORMAT_LABELS.get(fmt, "未识别"),
        "fit": fit,
        "craft": craft,
        # Backward-compatible fields used by older clients.
        "total": craft["total"],
        "grade": craft["grade"],
        "dimensions": craft["dimensions"],
        "suggestions": craft["suggestions"],
        "summary": summary,
        "skill_alignment": skill_alignment_check(title, body, tags),
    }


def score_note_with_skill(
    db: Session,
    user: User,
    note: Any,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Score a saved note with the account's active Skill.

    Uses the note's real format (image/video, short/long) so a short visual
    note is not punished by a long-form body rubric.
    """
    from backend.app.models import Tag, note_tags

    tags = list(
        db.scalars(
            select(Tag.name)
            .join(note_tags, Tag.id == note_tags.c.tag_id)
            .where(note_tags.c.note_id == note.id)
        ).all()
    )
    if not tags and isinstance(note.raw_json, dict):
        raw = note.raw_json
        for key in ("tags", "tag_list", "tagList"):
            value = raw.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        tags.append(item)
                    elif isinstance(item, dict) and item.get("name"):
                        tags.append(str(item["name"]))
    if not tags:
        try:
            from backend.app.models import FeatureSnapshot

            snapshot = db.scalars(
                select(FeatureSnapshot).where(
                    FeatureSnapshot.scope == "note",
                    FeatureSnapshot.ref_id == note.id,
                    FeatureSnapshot.feature_set == "content_rules_v1",
                )
            ).first()
            if snapshot and isinstance(snapshot.feature_json, dict):
                tags = [str(tag) for tag in (snapshot.feature_json.get("tags") or []) if str(tag).strip()]
        except Exception:
            tags = []

    note_type, image_count, has_video = _note_type_and_images(note)
    fmt = detect_format(
        note.title or "",
        note.content or "",
        note_type=note_type,
        image_count=image_count,
        has_video=has_video,
    )
    draft = AiDraft(
        user_id=user.id,
        platform=note.platform or "xhs",
        platform_account_id=account_id or note.platform_account_id,
        title=note.title or "",
        body=note.content or "",
        tags=tags,
    )
    draft.id = note.id
    result = score_draft_with_skill(
        db,
        user,
        draft,
        format_hint=fmt,
        image_count_hint=image_count,
        has_video_hint=has_video,
    )
    result["note_id"] = note.id
    return result
