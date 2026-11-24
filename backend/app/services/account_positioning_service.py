"""Account positioning: who the account serves, and what it never says.

Why this exists separately from :class:`StyleProfile`
----------------------------------------------------
A style is *distilled from a corpus*; a positioning is *decided* by the owner.
An account with four notes has a positioning and no style, and forcing it into
``style_profiles`` produced two failures that are visible in production data:

1. ``apply_to_account`` demotes every other applied profile for the account, so
   positioning and style could never be active at the same time.
2. The generator read the whole ``skill_md`` as one blob, so a positioning had
   to be written as a long document before any of it reached the prompt.

Here positioning is six short fields, injected as one small block. Style stays
on its own path and is simply absent until there is a corpus to distill.

What gets injected, and what deliberately does not
--------------------------------------------------
* Injected: positioning / audience / main_topics / taboos (+ language_samples).
* Not injected: ``promise`` and any offer/pricing information. Those decide
  *what to write about*, not *how to write this piece*; injecting them turns
  every draft into a sales page. The 变现倒推 Skill says as much: content
  serves "why people trust me", not "buy now".
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AccountPositioning, PlatformAccount, User

# Fields that may be written by a client. Kept explicit so an API caller cannot
# set ``source`` or ownership columns by accident.
EDITABLE_FIELDS: tuple[str, ...] = (
    "positioning",
    "audience",
    "promise",
    "main_topics",
    "taboos",
    "language_samples",
)

# Fields injected into a writing prompt. ``promise`` is intentionally excluded.
PROMPT_FIELDS: tuple[str, ...] = (
    "positioning",
    "audience",
    "main_topics",
    "taboos",
    "language_samples",
)

_FIELD_LABELS: dict[str, str] = {
    "positioning": "一句话定位",
    "audience": "目标用户",
    "promise": "内容承诺",
    "main_topics": "内容支柱",
    "taboos": "禁区",
    "language_samples": "语言样本",
}

MAX_BLOCK_CHARS = 1800


def _clean_list(value: Any, *, split_commas: bool = True) -> list[str]:
    """Normalise a list-ish field.

    ``split_commas=False`` is used for verbatim quotes (language samples): they
    routinely contain commas, and splitting there would rewrite the user's own
    words. Labels (topics, taboos) read fine either way.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.replace(",", "\n").replace("，", "\n") if split_commas else value
        items: Iterable[Any] = text.splitlines()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    out: list[str] = []
    for item in items:
        text = str(item).strip().lstrip("-*•").strip()
        if text and text not in out:
            out.append(text)
    return out


def _samples_list(value: Any) -> list[str]:
    return _clean_list(value, split_commas=False)


def get_positioning(
    db: Session, user: User, account_id: int | None
) -> AccountPositioning | None:
    """The positioning for one account, or ``None`` when it was never filled."""
    if not account_id:
        return None
    return db.scalars(
        select(AccountPositioning).where(
            AccountPositioning.user_id == user.id,
            AccountPositioning.platform_account_id == account_id,
        )
    ).first()


def is_empty(record: AccountPositioning | None) -> bool:
    """是否「没有任何会进提示词的内容」。

    判定必须和 :data:`PROMPT_FIELDS` 用同一份字段表。以前这里额外检查了
    ``promise``（内容承诺），而那一项按设计不进提示词：于是「只填了内容承诺」
    被当成「定位已就绪」，`positioning_block` 却产出一段只有「内容支柱：[]、
    禁区：[]」的空壳，写稿时还会在它后面追加「以上是账号的真实情况」。
    """
    if record is None:
        return True
    for field in PROMPT_FIELDS:
        if field in ("main_topics", "taboos", "language_samples"):
            getter = _samples_list if field == "language_samples" else _clean_list
            if getter(getattr(record, field)):
                return False
        elif str(getattr(record, field) or "").strip():
            return False
    return True


def upsert_positioning(
    db: Session,
    user: User,
    account: PlatformAccount,
    updates: dict[str, Any],
    *,
    source: str = "manual",
) -> AccountPositioning:
    """Create or update the account's positioning.

    Only :data:`EDITABLE_FIELDS` are accepted; unknown keys are ignored rather
    than raising, because the same dict is fed from both the UI form and a
    Skill artifact whose field names drift.
    """
    record = get_positioning(db, user, account.id)
    if record is None:
        record = AccountPositioning(
            user_id=user.id,
            platform_account_id=account.id,
            source=source,
        )
        db.add(record)

    for field in EDITABLE_FIELDS:
        if field not in updates:
            continue
        value = updates[field]
        if field == "language_samples":
            setattr(record, field, _samples_list(value))
        elif field in ("main_topics", "taboos"):
            setattr(record, field, _clean_list(value))
        else:
            setattr(record, field, str(value or "").strip())

    if source:
        record.source = source

    db.commit()
    db.refresh(record)
    return record


def serialize_positioning(record: AccountPositioning | None, account_id: int | None = None) -> dict[str, Any]:
    """Shape used by the API and the UI form.

    ``missing`` lists the fields a writer still needs. The UI shows them as
    gaps, and the prompt block says they are unknown instead of inventing them.
    """
    if record is None:
        return {
            "account_id": account_id,
            "positioning": "",
            "audience": "",
            "promise": "",
            "main_topics": [],
            "taboos": [],
            "language_samples": [],
            "source": "",
            "missing": list(EDITABLE_FIELDS),
            "is_empty": True,
            "updated_at": None,
        }
    payload = {
        "account_id": record.platform_account_id,
        "positioning": record.positioning or "",
        "audience": record.audience or "",
        "promise": record.promise or "",
        "main_topics": _clean_list(record.main_topics),
        "taboos": _clean_list(record.taboos),
        "language_samples": _samples_list(record.language_samples),
        "source": record.source or "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    payload["missing"] = [field for field in EDITABLE_FIELDS if not payload[field]]
    payload["is_empty"] = is_empty(record)
    return payload


def positioning_block(
    db: Session,
    user: User,
    account_id: int | None,
    *,
    max_chars: int = MAX_BLOCK_CHARS,
) -> str:
    """Compact prompt block for positioning.

    Returns an empty string when nothing was filled: a caller that adds this to
    a prompt should be able to tell "no positioning" from "positioning is empty
    after trimming", so absence stays absence rather than becoming boilerplate.
    """
    record = get_positioning(db, user, account_id)
    if is_empty(record):
        return ""

    lines: list[str] = ["【账号定位】"]
    for field in PROMPT_FIELDS:
        if field not in ("positioning", "audience"):
            continue
        text = str(getattr(record, field) or "").strip()
        if text:
            lines.append(f"- {_FIELD_LABELS[field]}：{text}")

    main_topics = _clean_list(record.main_topics)
    if main_topics:
        lines.append(f"- 内容支柱：{'、'.join(main_topics[:8])}")

    taboos = _clean_list(record.taboos)
    if taboos:
        lines.append(f"- 禁区（绝不写）：{'；'.join(taboos[:8])}")

    samples = _samples_list(record.language_samples)
    if samples:
        lines.append("- 语言样本（我的真实原话，语气参照，不要照抄内容）：")
        for sample in samples[:6]:
            lines.append(f"  · {sample}")

    lines.append("- 定位高于通用模板；与模板冲突时以定位和禁区为准。")

    block = "\n".join(lines)
    # 只有「内容支柱 / 禁区 / 语言样本」三项都空、定位与目标用户也没写时，
    # 上面那些标题行会全部被跳过，只剩首尾两行样板——那不是「有定位」，
    # 而是「有这个字段」。宁可返回空串，让调用方按「没定位」处理。
    if len(lines) <= 2:
        return ""
    if len(block) <= max_chars:
        return block
    # Positioning is six short fields; if it blew the budget the owner pasted a
    # document in. Truncate but keep the cut visible instead of silently losing
    # the tail (the failure mode that once dropped a whole 禁区 section).
    return block[: max_chars - 20].rstrip() + "\n…（定位过长，已截断）"


__all__ = [
    "EDITABLE_FIELDS",
    "PROMPT_FIELDS",
    "MAX_BLOCK_CHARS",
    "get_positioning",
    "is_empty",
    "upsert_positioning",
    "serialize_positioning",
    "positioning_block",
]
