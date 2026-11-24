"""Skill pack import parsing (no database or model calls)."""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.app.services.skill_library_service import (
    SkillPackError,
    _clean_content,
    parse_skill_pack,
)


def _make_pack() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "pack/wb-xhs-topic-bank/SKILL.md",
            """---
name: wb-xhs-topic-bank
description: |
  选题库。Trigger phrases: "选题库", "标题公式".
---

# 七类选题库

## Runtime bootstrap and update gate

Before using any external program, install everything.

## 可执行步骤

1. 按七类公式生成选题。
""",
        )
        archive.writestr(
            "pack/custom-demo/SKILL.md",
            """# 自定义 Skill

没有 frontmatter 时用目录名。
""",
        )
        archive.writestr("pack/README.md", "visual assets are MIT and CC BY-NC 4.0")
    return buffer.getvalue()


def test_parse_skill_pack_maps_modules_and_strips_runtime():
    items = parse_skill_pack(_make_pack(), source="demo-pack")

    assert len(items) == 2
    by_slug = {item["slug"]: item for item in items}
    topic = by_slug["wb-xhs-topic-bank"]
    assert topic["module"] == "topic"
    assert "Runtime bootstrap" not in topic["content_md"]
    assert "七类公式" in topic["content_md"]
    assert "选题库" in topic["triggers"]
    assert topic["source"] == "demo-pack"
    assert "CC BY-NC" in topic["license"]

    assert by_slug["custom-demo"]["module"] == "general"


def test_clean_content_removes_frontmatter_and_relative_policy():
    text = """---
name: demo
---
# Demo

See ../RUNTIME_UPDATE_POLICY.md.
"""
    cleaned = _clean_content(text)

    assert not cleaned.startswith("---")
    assert "../RUNTIME_UPDATE_POLICY.md" not in cleaned


def test_parse_skill_pack_rejects_non_zip():
    with pytest.raises(SkillPackError):
        parse_skill_pack(b"not a zip")


def test_parse_skill_pack_requires_skill_md():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack/readme.md", "no skills")
    with pytest.raises(SkillPackError):
        parse_skill_pack(buffer.getvalue())
