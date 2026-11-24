"""Publishing options → ``note_info`` conversion.

There used to be two implementations of this, in ``api/publish.py`` (interactive
publish) and ``services/scheduler_service.py`` (scheduled publish). They drifted:
the API version converted ``draft_tags`` but only when the tags were dicts, the
scheduler version dropped them unconditionally. Both ignored the shape that
actually exists in the database — 20 of 21 drafts store plain strings like
``["AI工具", "一人公司"]`` — so every AI-generated tag was silently discarded at
publish time, while preflight still warned "no tags, add 3–8".

Keeping this in one place is the point: the two paths must not disagree about
what a tag is.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

__all__ = [
    "clean_topics",
    "topics_from_draft_tags",
    "parse_publish_options",
    "apply_publish_options",
]


def parse_publish_options(raw: str | None) -> dict[str, Any]:
    """Read the JSON blob stored on a publish job.

    A malformed or non-object value must behave like no options, not crash the
    publish path. Both the API serializer and the publisher use this so they
    cannot disagree about what was stored.
    """
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def clean_topics(topics: Iterable[Any] | None) -> list[str]:
    """Trimmed non-empty topic strings."""
    if not topics:
        return []
    return [str(topic).strip() for topic in topics if topic and str(topic).strip()]


def topics_from_draft_tags(draft_tags: Any) -> list[str]:
    """Tag names from either stored shape.

    Drafts hold two shapes depending on how they were created: a plain list of
    names, or an imported list of ``{"id": ..., "name": ...}`` objects. Both are
    valid; the publish path must accept both rather than quietly publishing
    nothing.
    """
    if not isinstance(draft_tags, list):
        return []

    names: list[str] = []
    for item in draft_tags:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    # De-duplicate but keep the author's order.
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def resolve_topics(options: dict[str, Any]) -> list[str]:
    """Explicit topics win; otherwise fall back to the draft's own tags."""
    topics = clean_topics(options.get("topics") if isinstance(options.get("topics"), list) else None)
    if topics:
        return topics
    return topics_from_draft_tags(options.get("draft_tags"))


def apply_publish_options(note_info: dict[str, Any], options: dict[str, Any]) -> None:
    """Copy stored job options onto the payload sent to the platform."""
    topics = resolve_topics(options)
    if topics:
        note_info["topics"] = topics

    location = options.get("location")
    if isinstance(location, str) and location.strip():
        note_info["location"] = location.strip()

    privacy_type = options.get("privacy_type")
    if privacy_type in (0, 1):
        note_info["type"] = privacy_type
