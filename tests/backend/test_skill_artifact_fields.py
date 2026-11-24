"""Skill 产物要能拆成可编辑字段，而不是只能读的整篇文章。

The account-profile Skill asks for specific fields in its own completion
criteria, so the schema is read from the manual instead of being invented here.
"""

from __future__ import annotations

from backend.app.models import SkillLibraryItem
from backend.app.services.skill_artifact_service import (
    _classify,
    extract_fields,
    summarize_fields,
)


ARTIFACT = """# 账号档案

## 1. 定位卡 ✅

| 字段 | 内容 | 状态 |
| --- | --- | --- |
| 一句话定位 | 宁波一人公司记录者 | ✅ |
| 目标用户 | 宁波独立开发者 | ✅ |
| 报价 | 待确认 | ⚠️ 假设 |

## 2. 个人语言样本 ❌ 数据不足

只找到 1 句原话，不足以判断口吻。

## 3. 禁区（红线）✅

- 不承诺收益
- 不编造案例
"""

MANUAL = """# 账号档案

## E — 可执行步骤

5. **定义人设垂直规则**
   - 完成标准: 输出 `main_topics`、`persona_extensions`。

6. **登记长期资产**
   - 完成标准: 输出 `direction_assets`、`trust_assets`。
"""


def _item(content: str = MANUAL) -> SkillLibraryItem:
    return SkillLibraryItem(
        id=1,
        user_id=1,
        slug="wb-xhs-account-profile",
        name="账号档案",
        description="账号档案。",
        module="persona",
        triggers=[],
        content_md=content,
        enabled=True,
        sort_order=1,
    )


def test_classify_reads_status_marks():
    assert _classify("✅ 已确认") == "confirmed"
    assert _classify("⚠️ 假设") == "assumed"
    assert _classify("❌ 缺失") == "missing"
    assert _classify("") == "missing"


def test_classify_does_not_flag_incidental_words():
    """「为什么信你」 is prose, not a missing-field marker."""
    assert _classify("2. 个人 IP 信任逻辑（为什么信你，而不只是收藏这条内容）") == "confirmed"


def test_sections_become_fields():
    fields = extract_fields(ARTIFACT)
    by_label = {field["label"]: field for field in fields}

    assert any("定位卡" in label for label in by_label)
    assert any("个人语言样本" in label for label in by_label)
    assert any("禁区" in label for label in by_label)


def test_short_section_with_marker_is_missing():
    fields = extract_fields(ARTIFACT)
    language = next(f for f in fields if "个人语言样本" in f["label"])

    assert language["status"] == "missing"
    assert language["editable"] is True


def test_confirmed_section_is_not_editable():
    fields = extract_fields(ARTIFACT)
    redline = next(f for f in fields if "禁区" in f["label"])

    assert redline["status"] == "confirmed"
    assert redline["editable"] is False


def test_table_rows_in_header_become_fields():
    fields = extract_fields(ARTIFACT)
    labels = [field["label"] for field in fields]

    assert "一句话定位" in labels
    assert "目标用户" in labels


def test_manual_field_names_are_added_as_missing():
    """Fields the Skill demands but the artifact never filled show up as missing."""
    fields = extract_fields(ARTIFACT, _item())
    keys = {field["key"] for field in fields}

    assert "main_topics" in keys
    assert "persona_extensions" in keys
    assert "trust_assets" in keys
    required = [f for f in fields if f.get("source") == "skill_manual"]
    assert all(field["status"] == "missing" for field in required)
    assert all(field["editable"] for field in required)


def test_summary_counts_all_three_states():
    fields = extract_fields(ARTIFACT, _item())

    summary = summarize_fields(fields)

    assert summary["confirmed"] >= 1
    assert summary["assumed"] + summary["missing"] >= 1
    assert sum(summary.values()) == len(fields)


def test_empty_artifact_yields_only_manual_fields():
    fields = extract_fields("", _item())
    keys = {field["key"] for field in fields}

    assert "main_topics" in keys
    assert all(field["status"] == "missing" for field in fields)
