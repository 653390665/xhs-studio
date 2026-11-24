"""Task-driven skill routing.

The library can hold dozens of imported skills (for example the 69 skills in
``phuryn/pm-skills``), but a single prompt can only carry a few of them. This
module scores every enabled skill against the current task and returns the most
relevant ones, so callers can inject a small, task-specific block instead of the
whole module.

Pure functions only: no database access, easy to unit test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models import SkillLibraryItem

_EN_RE = re.compile(r"[a-z][a-z0-9']+")
_ZH_RE = re.compile(r"[\u4e00-\u9fff]+")

# Platform name and content-type words appear in almost every task. Tokenized as
# bigrams they turn "小红书" into 小红 + 红书, which spuriously matched the
# "小红书定位" trigger of the positioning skill and injected persona methodology
# into ordinary writing prompts. Strip them before tokenizing.
_DOMAIN_NOISE = (
    "小红书", "xiaohongshu", "xhs", "红书笔记", "图文笔记",
)

# Bigrams that survive segmentation but carry no task signal.
_ZH_STOPWORDS = {
    "怎么", "什么", "如何", "为何", "为什", "是否", "可以", "需要", "一个",
    "一下", "帮我", "给我", "我们", "你们", "他们", "这个", "那个", "就是",
    "不是", "没有", "已经", "还有", "因为", "所以", "但是", "如果", "时候",
    "今天", "现在", "然后", "而且", "或者", "以及", "进行", "通过", "对于",
    "关于", "这样", "那样", "一些", "这些", "那些", "自己", "东西", "事情",
    "问题", "方法", "方式", "能够", "应该", "可能", "觉得", "知道", "看到",
    # Fragments of the platform name and generic content nouns.
    "小红", "红书", "书笔", "笔记", "草稿", "主题", "内容", "文章", "一篇",
    "写作", "口语", "一点", "帮我",
}

_GENERIC_TRIGGERS = {
    "怎么", "什么", "如何", "今天", "现在", "可以", "需要", "是否", "为什么",
    "一个", "一下", "我们", "他们", "你们", "这个", "那个", "时候", "东西",
    "事情", "问题", "方法", "方式",
}

# Generic words that appear in almost every skill description. Matching them
# would make every skill look relevant.
_STOPWORDS = {
    "the", "and", "for", "with", "your", "you", "that", "this", "from", "are",
    "how", "what", "when", "who", "why", "into", "about", "their", "they",
    "will", "can", "cannot", "could", "would", "should", "must", "may",
    "have", "has", "had", "use", "used", "using", "not", "but", "all", "any",
    "out", "our", "one", "two", "its", "was", "were", "been", "being", "more",
    "most", "some", "such", "than", "then", "there", "these", "those", "over",
    "under", "again", "once", "here", "both", "each", "few", "other", "own",
    "same", "too", "very", "just", "also", "only", "via", "per", "etc",
    "skill", "skills", "guide", "guides", "example", "examples", "step",
    "steps", "approach", "approaches", "practice", "practices", "help",
    "helps", "helping", "work", "works", "working", "team", "teams",
    "product", "products", "company", "companies", "make", "makes", "making",
    "need", "needs", "want", "wants", "best", "new", "good", "great",
    "review", "reviews", "plan", "plans", "planning", "tool", "tools",
}

# Chinese intent -> English keywords. Imported packs are mostly English, while
# the product UI and prompts are Chinese. This bridge lets a Chinese task match
# English skill names/descriptions without an extra model call.
ZH_EN_HINTS: dict[str, tuple[str, ...]] = {
    "定位": ("positioning", "position", "niche", "persona"),    "画像": ("persona", "profile", "audience", "positioning"),
    "人群": ("audience", "segment", "customer", "persona"),
    "用户": ("user", "customer", "research", "interview"),
    "客户": ("customer", "client", "buyer"),
    "需求": ("requirements", "prd", "spec", "problem"),
    "竞品": ("competitor", "competitive", "benchmark"),
    "对标": ("benchmark", "competitor", "competitive"),
    "市场": ("market", "market research", "market sizing"),
    "调研": ("research", "interview", "survey", "discovery"),
    "访谈": ("interview", "research", "discovery"),
    "假设": ("hypothesis", "assumption"),
    "验证": ("validation", "experiment", "hypothesis"),
    "实验": ("experiment", "testing", "hypothesis"),
    "选题": ("topic", "idea", "content", "angle"),
    "标题": ("title", "headline", "hook"),
    "开头": ("opening", "hook", "intro"),
    "封面": ("cover", "visual", "thumbnail"),
    "视觉": ("visual", "design", "cover"),
    "配图": ("illustration", "visual", "image"),
    "插图": ("illustration", "visual", "image"),
    "插画": ("illustration", "visual", "image"),
    "图片": ("image", "visual", "illustration"),
    "海报": ("poster", "cover", "visual"),
    "设计": ("design", "visual", "layout"),
    "写稿": ("writing", "draft", "copy", "narrative"),
    "改写": ("rewrite", "editing", "copy"),
    "润色": ("polish", "rewrite", "editing"),
    "文案": ("copy", "copywriting", "messaging"),
    "结构": ("structure", "outline", "framework"),
    "复盘": ("retrospective", "review", "metrics", "analytics"),
    "数据": ("data", "metrics", "analytics", "measurement"),
    "指标": ("metric", "kpi", "north star"),
    "增长": ("growth", "acquisition", "funnel", "conversion"),
    "转化": ("conversion", "funnel", "retention"),
    "留存": ("retention", "cohort", "churn"),
    "获客": ("acquisition", "channel", "growth"),
    "变现": ("monetization", "revenue", "pricing", "business"),
    "定价": ("pricing", "price", "revenue"),
    "商业化": ("monetization", "business model", "revenue"),
    "发布": ("launch", "release", "go-to-market", "gtm"),
    "上线": ("launch", "release", "go-to-market"),
    "排期": ("roadmap", "planning", "prioritization", "schedule"),
    "路线图": ("roadmap", "planning", "prioritization"),
    "优先级": ("prioritization", "priority", "rice"),
    "策略": ("strategy", "strategic", "vision"),
    "战略": ("strategy", "strategic", "vision"),
    "品牌": ("brand", "positioning", "messaging"),
    "案例": ("case study", "case", "example"),
    "模板": ("template", "framework"),
    "面试": ("interview", "hiring"),
    "招聘": ("hiring", "interview", "recruiting"),
    "商业": ("business", "revenue", "model"),
    "目标": ("goal", "objective", "okr"),
    "北极星": ("north star", "metric"),
    "反馈": ("feedback", "review", "survey"),
}

# 中文口语说法 → Skill 字段里的英文关键词。
#
# 为什么和 ZH_EN_HINTS 分开：那一张是「中文话题词 → 英文专业词」的翻译桥，
# 这一张是「用户怎么描述自己的问题」。真实用户不会说「执行去 AI 味方法论」，
# 他会说「这篇太像 AI 了」「改得像人写的」「读起来太生硬」。
# 这些说法和 Skill 的 triggers（「去 AI 味」「不像人」）字面不重合，
# 只靠两字切片只能拿到 1.6 分，过不了 4.0 的门槛，于是路由返回空。
#
# 只收真实出现过的说法，不做无限同义词扩张：多收一个词就多一种误命中，
# 而这里的代价是把一整套方法论塞进不相干的提示词。
ZH_PARAPHRASE_HINTS: dict[str, tuple[str, ...]] = {
    "像人": ("humanize",),
    "人味": ("humanize",),
    "不像人": ("humanize",),
    "机器写": ("humanize",),
    "太像ai": ("humanize",),
    "生硬": ("humanize",),
    "口语化": ("humanize",),
    "讲人话": ("humanize",),
    "改稿": ("rewrite", "editing"),
    "改得像人": ("humanize",),
    # 「润色」原来只桥到 polish/rewrite，而库里的改稿 Skill 叫
    # humanize-compliance，中文正文里才出现「润色」。
    "润色": ("humanize", "polish", "rewrite"),
}

# Field weights. A name/slug hit is the strongest signal, description and
# trigger hits are medium, body text is only supporting evidence.
NAME_WEIGHT = 5.0
TRIGGER_WEIGHT = 4.0
# A shared two-character fragment of a trigger is weak evidence, not a hit.
TRIGGER_FRAGMENT_WEIGHT = 0.5
DESCRIPTION_WEIGHT = 2.5
CONTENT_WEIGHT = 0.3
CONTENT_MATCH_CAP = 4
SLUG_PART_WEIGHT = 2.0
MODULE_BONUS = 2.0
MIN_SCORE = 4.0
# 调用方已经指明模块时，该模块自己的 Skill 用更低的门槛。
# 模块本身就是一条强信号（「这次是写稿改稿」），不需要再靠触发词证明；
# 但跨模块的 Skill 仍然要过 MIN_SCORE，并且必须有触发短语。
MODULE_MIN_SCORE = 2.5


@dataclass
class RoutedSkill:
    item: SkillLibraryItem
    score: float
    reasons: list[str]


_TOKEN_CACHE: dict[tuple, dict[str, set[str]]] = {}
_TOKEN_CACHE_LIMIT = 300


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("'s"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> set[str]:
    """Split English words and Chinese character bigrams."""
    lowered = (text or "").lower()
    for noise in _DOMAIN_NOISE:
        lowered = lowered.replace(noise, " ")
    result: set[str] = set()
    for word in _EN_RE.findall(lowered):
        if len(word) < 3 or word in _STOPWORDS:
            continue
        result.add(_stem(word))
    for segment in _ZH_RE.findall(lowered):
        if len(segment) == 1:
            if segment not in _ZH_STOPWORDS:
                result.add(segment)
            continue
        for index in range(len(segment) - 1):
            token = segment[index : index + 2]
            if token not in _ZH_STOPWORDS:
                result.add(token)
    return result


def query_tokens(text: str) -> set[str]:
    """Task tokens plus bilingual bridge tokens for Chinese intent."""
    lowered = (text or "").lower()
    result = tokens(lowered)
    for chinese, english in ZH_EN_HINTS.items():
        if chinese in lowered:
            for word in english:
                for part in _EN_RE.findall(word.lower()):
                    if len(part) >= 3 and part not in _STOPWORDS:
                        result.add(_stem(part))
    # 口语说法按「去掉空白后」匹配，否则「太像 AI」和「太像ai」被当成两句。
    compact = _normalize_for_match(lowered)
    for chinese, english in ZH_PARAPHRASE_HINTS.items():
        if chinese in compact:
            for word in english:
                for part in _EN_RE.findall(word.lower()):
                    if len(part) >= 3 and part not in _STOPWORDS:
                        result.add(_stem(part))
    return result


def _skill_tokens(item: SkillLibraryItem) -> dict[str, set[str]]:
    content = item.content_md or ""
    cache_key = (item.id, item.updated_at, item.slug, len(content))
    cached = _TOKEN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    triggers = [str(value) for value in (item.triggers or []) if str(value).strip()]
    result = {
        "name": tokens(f"{item.name} {item.slug}"),
        "description": tokens(item.description or ""),
        "trigger": tokens(" ".join(triggers)),
        "content": tokens(content[:12000]),
    }
    if len(_TOKEN_CACHE) >= _TOKEN_CACHE_LIMIT:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[cache_key] = result
    return result


def _trigger_is_generic(value: str) -> bool:
    if value in _GENERIC_TRIGGERS:
        return True
    meaningful = tokens(value) - _GENERIC_TRIGGERS
    return not meaningful


def _normalize_for_match(value: str) -> str:
    """Collapse whitespace so 「去 AI 味」 matches 「去AI味」."""
    return re.sub(r"\s+", "", (value or "").lower())


def _matched_trigger(item: SkillLibraryItem, query_lower: str) -> list[str]:
    """Triggers that actually appear in the task text, as whole phrases.

    Triggers must be matched as phrases, not as character bigrams. The bigram
    path treated 「个人IP」 as the token 「个人」, so an ordinary topic like
    「15 个人聊 AI 选型」 routed a positioning skill into a writing task.
    """
    hits: list[str] = []
    if not query_lower:
        return hits
    normalized_query = _normalize_for_match(query_lower)
    for raw in item.triggers or []:
        trigger = str(raw or "").strip().lower()
        if len(trigger) < 2 or _trigger_is_generic(trigger):
            continue
        normalized_trigger = _normalize_for_match(trigger)
        if not normalized_trigger:
            continue
        if _is_ascii_word(normalized_trigger):
            # Latin triggers must match on a word boundary, otherwise "ai"
            # matches inside "said" and similar.
            if re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_trigger)}(?![a-z0-9])",
                normalized_query,
            ):
                hits.append(trigger)
            continue
        if normalized_trigger in normalized_query:
            hits.append(trigger)
    return hits


def _is_ascii_word(value: str) -> bool:
    return bool(value) and all(ord(char) < 128 for char in value)


def score_skill(
    item: SkillLibraryItem,
    query: str,
    task_tokens: set[str] | None = None,
    *,
    preferred_module: str | None = None,
) -> tuple[float, list[str]]:
    """Return ``(score, reasons)`` for one skill against one task."""
    resolved_tokens = task_tokens if task_tokens is not None else query_tokens(query)
    if not resolved_tokens and not query:
        return 0.0, []

    query_lower = (query or "").lower()
    skill_tokens = _skill_tokens(item)
    score = 0.0
    reasons: list[str] = []

    name_hits = resolved_tokens & skill_tokens["name"]
    if name_hits:
        score += NAME_WEIGHT * len(name_hits)
        reasons.append("名称命中：" + "、".join(sorted(name_hits)[:3]))

    # Trigger scoring uses phrase matching only (see _matched_trigger). The
    # bigram intersection is kept at a much lower weight because a shared
    # two-character fragment is weak evidence.
    trigger_hits = resolved_tokens & skill_tokens["trigger"]
    if trigger_hits:
        score += TRIGGER_FRAGMENT_WEIGHT * min(len(trigger_hits), 2)

    description_hits = resolved_tokens & skill_tokens["description"]
    if description_hits:
        score += DESCRIPTION_WEIGHT * min(len(description_hits), 3)
        reasons.append("描述命中：" + "、".join(sorted(description_hits)[:3]))

    content_hits = resolved_tokens & skill_tokens["content"]
    if content_hits:
        score += CONTENT_WEIGHT * min(len(content_hits), CONTENT_MATCH_CAP)

    for part in (item.slug or "").lower().split("-"):
        if len(part) >= 4 and part not in _STOPWORDS and part in query_lower:
            score += SLUG_PART_WEIGHT
            reasons.append(f"关键词：{part}")
            break

    phrases = _matched_trigger(item, query_lower)
    for trigger in phrases[:2]:
        score += TRIGGER_WEIGHT
        reasons.append(f"触发短语：{trigger}")

    if preferred_module and item.module == preferred_module:
        score += MODULE_BONUS
        reasons.append("模块匹配")

    return round(score, 2), reasons


def effective_score(entry: RoutedSkill, module: str | None) -> float:
    """Score comparable to the routing threshold.

    ``score_skill`` adds ``MODULE_BONUS`` when the skill belongs to the module
    the caller named. That bonus says "this is the right discipline", not
    "this is relevant to the task", so it must be subtracted before comparing
    against ``MODULE_MIN_SCORE`` — otherwise a 0.6-relevance skill shows up as
    2.6 and looks like it cleared a 2.5 bar. The same number is shown in the UI,
    so the displayed score and the displayed threshold have to be on one scale.
    """
    if module and entry.item.module == module:
        return round(entry.score - MODULE_BONUS, 2)
    return entry.score


def rank_rows(
    rows: list[SkillLibraryItem],
    query: str,
    *,
    module: str | None = None,
    priority_by_id: dict[int, int] | None = None,
) -> list[RoutedSkill]:
    """Score every allowed skill, without applying a threshold.

    ``route_rows`` throws away everything below the bar. That is right for
    injection but wrong for diagnostics: 「没有命中」 gives the user no way to
    tell whether the library is empty, disabled, or just phrased differently.
    The UI and the agent use this ranked list to show near misses.
    """
    text = (query or "").strip()
    if not text or not rows:
        return []
    task_tokens = query_tokens(text)
    if not task_tokens:
        return []

    scored: list[RoutedSkill] = []
    for item in rows:
        if module == "visual":
            if item.module != "visual":
                continue
        elif module is not None and item.module == "visual":
            continue
        score, reasons = score_skill(item, text, task_tokens, preferred_module=module)
        scored.append(RoutedSkill(item=item, score=score, reasons=reasons))

    # 同分时的次序。**分数永远是第一排序键**，priority 只在同分时起作用。
    #
    # 两个刻度不能直接比，所以先分组再各自升序：
    #   · 显式设过优先级的：按 priority 升序（1 最优先，和 ``sort_order`` 同向）。
    #     界面文案已同步改成「数字越小越优先」，因为 ``AccountSkillSetting.priority``
    #     默认 100，而 ``sort_order`` 是 10/20/30/40——「越大越优先」会让默认值
    #     压过所有内置次序，也和 ``test_account_priority_breaks_ties`` 的既有约定相反。
    #   · 没设过的：按 sort_order 升序。
    def _rank(entry: "RoutedSkill") -> tuple[float, int, int, int]:
        explicit = priority_by_id.get(entry.item.id) if priority_by_id else None
        if explicit is not None:
            return (-entry.score, 0, int(explicit), entry.item.id)
        return (-entry.score, 1, int(entry.item.sort_order or 0), entry.item.id)

    scored.sort(key=_rank)
    return scored


def route_rows(
    rows: list[SkillLibraryItem],
    query: str,
    *,
    module: str | None = None,
    limit: int = 3,
    min_score: float = MIN_SCORE,
    priority_by_id: dict[int, int] | None = None,
) -> list[RoutedSkill]:
    """Pick the most relevant enabled skills for one task.

    Visual skills only compete inside the visual module: their content is about
    image prompts and would pollute text-generation prompts. When no module is
    given the caller is routing explicitly by task (the agent's
    ``route_skill_library``), so visual skills are allowed to compete — otherwise
    「封面锚点」 could never be reached by name.
    """
    if not (query or "").strip() or not rows:
        return []
    if not query_tokens(query):
        return []

    scored = rank_rows(
        rows, query, module=module, priority_by_id=priority_by_id
    )

    # 门槛分两种：调用方点名的模块，自己的 Skill 用 MODULE_MIN_SCORE；
    # 其余（含没有点名模块的情况）一律用 min_score。
    #
    # 比较时要先减掉「模块匹配 +2」：那 2 分只说明它属于这个模块，
    # 不说明它和这次任务有关。不减的话，任何模块自己的 Skill 凭
    # 0.6 分的内容命中就能过线，等于门槛失效。
    routed: list[RoutedSkill] = []
    for entry in scored:
        is_own_module = module is not None and entry.item.module == module
        if is_own_module:
            relevance = effective_score(entry, module)
            bar = MODULE_MIN_SCORE
        else:
            relevance = entry.score
            bar = min_score
        if relevance < bar:
            continue
        routed.append(entry)

    # A skill from another module may only join when it matched on something
    # stronger than a shared word. Otherwise 「写一篇沙龙复盘」 pulls in
    # 「排期与复盘」 just because the topic contains 复盘, and the writing prompt
    # becomes a scheduling methodology.
    if module:
        module_has_skills = any(item.module == module for item in rows)
        own = [entry for entry in routed if entry.item.module == module]
        if own:
            routed = own + [
                entry
                for entry in routed
                if entry.item.module != module
                and any("触发短语" in reason for reason in entry.reasons)
            ]
        elif module_has_skills:
            # The module owns skills but none cleared the bar. Returning a
            # foreign skill here would replace the module's methodology with a
            # different discipline; return nothing and let the caller fall back
            # to this module's own skills.
            routed = []

    return routed[: max(1, limit)]
