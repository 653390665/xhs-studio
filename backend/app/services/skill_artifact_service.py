"""把结构化的 Skill 产物拆成可编辑字段。

The account-profile Skill already names the fields it wants in its own
completion criteria (``main_topics``, ``persona_extensions``,
``secondary_account_candidates``). Field design therefore comes from the Skill
manual, not from a hand-written schema here — otherwise the product would drift
away from the methodology it claims to run.

A field is one of three states, matching how the manual marks unknowns:

* ``confirmed`` — the source text asserted it
* ``assumed``   — the source text marked it as a guess (⚠️ / 假设 / 待确认)
* ``missing``   — the source text marked it as unavailable (❌ / 缺失 / 数据不足)

Only ``missing`` and ``assumed`` fields are worth asking the user about, which is
what makes the artifact editable instead of write-only.
"""

from __future__ import annotations

import re
from typing import Any

_MISSING_MARKERS = ("❌", "缺失", "数据不足", "无法填写", "未提供", "未确认", "待填")
_ASSUMED_MARKERS = ("⚠️", "⚠", "假设", "待确认", "暂定", "待补", "待验证", "草案")


def _classify(row_text: str) -> str:
    """Return the weakest claim the text supports.

    ``缺失`` inside an ordinary sentence ("缺什么就补") is not a missing field, so
    markers only count when they look like a status annotation: a ❌/⚠️ glyph, or
    the marker appearing at the start/end of the text.
    """
    value = (row_text or "").strip()
    if not value:
        return "missing"
    head = value[:40]
    tail = value[-40:]
    for marker in _MISSING_MARKERS:
        if marker == "❌":
            if marker in value:
                return "missing"
            continue
        if marker in head or marker in tail:
            return "missing"
    for marker in _ASSUMED_MARKERS:
        if marker in ("⚠️", "⚠"):
            if marker in value:
                return "assumed"
            continue
        if marker in head or marker in tail:
            return "assumed"
    return "confirmed"


def _clean(cell: str) -> str:
    return re.sub(r"\s+", " ", (cell or "").replace("**", "")).strip()


def _table_rows(lines: list[str]) -> list[tuple[str, str]]:
    """Return ``(key, detail)`` pairs from markdown table rows.

    Only narrow tables (≤3 columns) are treated as field lists. A wide data table
    such as a 样本对比表 has many columns; exploding every cell into a field would
    produce dozens of meaningless entries.
    """
    rows: list[tuple[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or len(cells) > 3:
            continue
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        key = _clean(cells[0])
        if not key or key in ("字段", "项目", "#", "编号"):
            continue
        detail = " ".join(_clean(cell) for cell in cells[1:] if _clean(cell))
        rows.append((key, detail))
    return rows


def _known_field_keys(item) -> list[str]:
    """Field names the Skill manual itself asks for (backticked identifiers).

    ``账号档案`` step 5 requires ``main_topics`` / ``persona_extensions`` /
    ``secondary_account_candidates``; step 6 requires ``input_slots`` and friends.
    Reading them from the manual keeps the schema honest.
    """
    content = item.content_md or ""
    found: list[str] = []
    for name in re.findall(r"`([a-z][a-z0-9_]{2,40})`", content):
        if name not in found:
            found.append(name)
    return found


def extract_fields(artifact_md: str, item=None) -> list[dict[str, Any]]:
    """Split an artifact into editable fields with a three-state status."""
    text = artifact_md or ""
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Every ``## heading`` becomes a field; its body carries the status marks.
    for part in re.split(r"\n(?=## )", text):
        lines = part.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        if not heading.startswith("## "):
            continue
        label = _clean(re.sub(r"^##\s*", "", heading))
        label = re.sub(r"[（(][^）)]*[）)]\s*$", "", label).strip()
        label = re.sub(r"^第[一二三四五六七八九十]+部分[:：]\s*", "", label).strip()
        # Drop the ordinal and status glyph so the label reads as a field name.
        label = re.sub(r"^\d+[.、]\s*", "", label).strip()
        label = label.replace("✅", "").replace("❌", "").replace("⚠️", "").replace("⚠", "").strip()
        label = re.sub(r"\s*(数据不足|大部分待确认|待确认)$", "", label).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        body = "\n".join(lines[1:]).strip()
        heading_status = _classify(heading)
        body_status = _classify(body)
        # A long section that merely contains a ❌/⚠️ cell in a table is not a
        # blank field; it needs review, not filling in from scratch.
        if body_status == "missing" and len(body) > 200:
            body_status = "assumed"
        # An explicit heading mark outranks a clean body: the Skill author marked
        # this section as unfilled, so treat it as needing the user's input.
        if heading_status != "confirmed":
            status = heading_status
        else:
            status = body_status
        # A pure divider ("第一部分：…") carries no content of its own.
        if len(body) < 10:
            continue
        fields.append(
            {
                "key": _slugify(label),
                "label": label,
                "value": body,
                "status": status,
                "editable": status != "confirmed",
            }
        )

    # 2. Tables supply fine-grained fields, but only a 2-3 column table reads as
    # one field per row. A wide comparison table (样本对比表) is data, not a
    # field list, and exploding it into dozens of fields makes the panel unusable.
    for key, detail in _table_rows(text.splitlines()):
        slug = _slugify(key)
        if slug in seen:
            continue
        seen.add(slug)
        status = _classify(detail)
        fields.append(
            {
                "key": slug,
                "label": key,
                "value": detail,
                "status": status,
                "editable": status != "confirmed",
            }
        )

    # 3. Field names the manual demands but the artifact never filled.
    if item is not None:
        for name in _known_field_keys(item):
            slug = _slugify(name)
            if slug in seen:
                continue
            seen.add(slug)
            fields.append(
                {
                    "key": slug,
                    "label": name,
                    "value": "",
                    "status": "missing",
                    "editable": True,
                    "required": True,
                    "source": "skill_manual",
                }
            )

    return fields


def _slugify(value: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    if ascii_part:
        return ascii_part
    # Chinese labels have no ascii form; keep the label readable and stable.
    return re.sub(r"\s+", "_", (value or "").strip())


def summarize_fields(fields: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"confirmed": 0, "assumed": 0, "missing": 0}
    for field in fields:
        status = str(field.get("status") or "missing")
        summary[status] = summary.get(status, 0) + 1
    return summary


__all__ = ["extract_fields", "summarize_fields", "_classify"]
