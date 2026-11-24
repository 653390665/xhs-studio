"""Account writing identity: a StyleProfile-backed view.

历史包袱：`CreationSkill`（层2）和 `StyleProfile`（层1）重复存放同一份内容。
每次「应用内置/蒸馏风格」都会把 StyleProfile 的内容复制一份到 CreationSkill，
于是 ego 这类内容在两张表各存一次，修改时要改两处，还可能不同步。

现在只保留 StyleProfile 作为唯一来源：一个账号只能有一个「生效中的风格」，
应用即激活，不再复制。为免改动 100+ 处调用点，这里返回一个视图对象，
字段名保持 `name` / `version` / `content_md` / `structured_json` 不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import PlatformAccount, StyleProfile, User


@dataclass
class ActiveStyleView:
    """A StyleProfile shaped like the old CreationSkill.

    ``version`` is derived from the profile id so callers that print
    "name version" keep working without showing a meaningless value.
    """

    profile: StyleProfile
    name: str = field(init=False)
    version: str = field(init=False)
    content_md: str = field(init=False)
    structured_json: dict[str, Any] = field(init=False)
    id: int = field(init=False)
    account_id: int | None = field(init=False)

    def __post_init__(self) -> None:
        p = self.profile
        self.id = p.id
        self.name = p.name
        self.account_id = p.account_id
        self.version = f"style-{p.id}"
        self.content_md = p.skill_md or ""
        meta = p.profile_json or {}
        self.structured_json = {
            "style_profile_id": p.id,
            "source": p.source,
            "engine": p.engine,
            "works_count": p.works_count,
            # 数据进化产物跟着风格走，评分权重不会因为删掉层2而丢
            "weight_multipliers": meta.get("weight_multipliers") or {},
            "analysis": meta.get("analysis") or {},
            "stats": meta.get("stats") or {},
        }


def active_style_profile(
    db: Session, user: User, account_id: int | None
) -> StyleProfile | None:
    """The account's currently applied style, or a global fallback.

    Highest priority is the most recently applied profile for this account; if the
    account has none, fall back to a user-level profile with no account binding.
    """
    if account_id:
        profile = db.scalars(
            select(StyleProfile)
            .where(
                StyleProfile.user_id == user.id,
                StyleProfile.account_id == account_id,
                StyleProfile.status == "applied",
            )
            .order_by(StyleProfile.updated_at.desc())
        ).first()
        if profile is not None:
            return profile
    return db.scalars(
        select(StyleProfile)
        .where(
            StyleProfile.user_id == user.id,
            StyleProfile.account_id.is_(None),
            StyleProfile.status == "applied",
        )
        .order_by(StyleProfile.updated_at.desc())
    ).first()


def active_creation_skill(
    db: Session, user: User, account_id: int | None
) -> ActiveStyleView | None:
    """Backwards-compatible accessor: the account's active style as a Skill view."""
    profile = active_style_profile(db, user, account_id)
    return ActiveStyleView(profile) if profile is not None else None


def _split_sections(md: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, body)`` chunks on level-2 headings.

    Content before the first ``##`` is returned as a chunk with an empty heading
    so nothing is silently dropped.
    """
    chunks: list[tuple[str, str]] = []
    current_head = ""
    current: list[str] = []
    for line in md.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            if current or current_head:
                chunks.append((current_head, "\n".join(current).strip()))
            current_head = line.strip()
            current = []
            continue
        current.append(line)
    if current or current_head:
        chunks.append((current_head, "\n".join(current).strip()))
    return [(head, body) for head, body in chunks if head or body]


# Sections that must survive a budget cut. Red lines and the account's own voice
# are worthless if they are the part that gets trimmed: a truncated prompt that
# keeps "变现路径" but loses "禁区" actively makes generation less safe.
_HIGH_PRIORITY = (
    "定位", "一句话", "目标用户", "人群", "禁区", "红线", "边界",
    "语言样本", "语气", "口吻", "栏目", "写法", "支柱",
)
_MID_PRIORITY = (
    "信任", "可信主张", "Offer", "offer", "变现", "人设", "差异化",
)
# Bookkeeping the model does not need while writing. Dropped first.
_LOW_PRIORITY = (
    "数据日志", "未确认", "更新机制", "验证计划", "内容管线", "Timing",
    "timing", "视觉身份", "可售卖资产",
)


def _section_rank(heading: str) -> int:
    """0 = keep first, 2 = drop first."""
    if any(key in heading for key in _LOW_PRIORITY):
        return 2
    if any(key in heading for key in _HIGH_PRIORITY):
        return 0
    if any(key in heading for key in _MID_PRIORITY):
        return 1
    return 1


def _evidence_rule_block(view: ActiveStyleView) -> str:
    """The rule block of an evidence-distilled profile, or "".

    Evidence profiles store ``injectable_rules`` (each with its coverage) next to
    the rendered Markdown. The rules are what the model should follow; the
    Markdown is a report for humans. Injecting the report wastes budget on
    headings and coverage bars that the model cannot act on.
    """
    meta = view.profile.profile_json or {}
    if meta.get("method") != "hypothesis-then-evidence":
        return ""
    rules = meta.get("injectable_rules") or []
    if not isinstance(rules, list) or not rules:
        return ""
    lines = [f"【写作风格：{view.name}】"]
    for rule in rules:
        text = str(rule).strip()
        if not text:
            continue
        # ``rules_for_prompt`` already prefixes with "- "; adding another produces
        # the visible "- - 每篇…" that shipped in the first version of this block.
        lines.append(text if text.startswith(("-", "·", "•")) else f"- {text}")
    return "\n".join(lines)


def style_prompt_block(view: ActiveStyleView, *, max_chars: int = 6000) -> str:
    """The style text a prompt should receive — one implementation for every caller.

    Why this exists: generation (``api/ai.py``), the agent, image copy, the skill
    library and the scheduler each used to compose this themselves, so the same
    applied profile reached the model five different ways: the rule block in some
    places, a bare ``content[:4000]`` slice in others, a section-prioritised
    truncation elsewhere. Users edited one profile and only half the model calls
    saw the edit.

    Evidence-distilled profiles carry their rules structurally. Their Markdown is
    a report *about* the writing (coverage bars, "自述与实测不一致" sections that
    explicitly say "不写进生成要求"), so injecting it wastes budget on guidance
    the model cannot act on. Those get the rule block; everything else gets the
    Markdown, truncated by section priority rather than mid-sentence.
    """
    rule_block = _evidence_rule_block(view)
    if rule_block:
        return rule_block

    content = view.content_md or ""
    if len(content) <= max_chars:
        return content

    # Over budget: keep the decision-critical sections whole, in document order,
    # then fill the remaining space. A plain ``content[:max_chars]`` used to cut
    # the 禁区 section off the end of a long profile.
    sections = _split_sections(content)
    budget = max_chars
    kept: dict[int, str] = {}
    order = sorted(
        range(len(sections)),
        key=lambda index: (_section_rank(sections[index][0]), index),
    )
    for index in order:
        head, body = sections[index]
        block = f"{head}\n{body}".strip() if head else body
        if not block:
            continue
        if len(block) > budget:
            if _section_rank(head) == 0 and budget > 200:
                # A critical section that cannot fit whole is still better
                # partially included than dropped.
                block = block[: budget - 1].rstrip() + "…"
            else:
                continue
        kept[index] = block
        budget -= len(block) + 2
        if budget <= 0:
            break

    body_text = "\n\n".join(kept[index] for index in sorted(kept))
    if len(body_text) > max_chars:
        body_text = body_text[: max_chars - 1].rstrip() + "…"
    omitted = len(sections) - len(kept)
    if omitted > 0:
        body_text += f"\n\n（另有 {omitted} 节因长度省略）"
    return body_text


def account_skill_block(
    db: Session,
    user: User,
    account: PlatformAccount | None,
    *,
    max_chars: int = 6000,
) -> str:
    """Prompt block describing who this account is, plus its writing rules."""
    if account is None:
        return ""
    view = active_creation_skill(db, user, account.id)
    lines = [f"账号：{account.nickname or account.id}"]
    if view is None:
        lines.append(
            "该账号还没有生效的写作风格。生成前建议先在「提炼 → 风格库」应用一个。"
        )
        return "\n".join(lines)
    lines.append(f"当前生效风格：{view.name}")
    lines.append("")
    body = style_prompt_block(view, max_chars=max_chars)
    if body:
        lines.append(body)
    return "\n".join(lines)
