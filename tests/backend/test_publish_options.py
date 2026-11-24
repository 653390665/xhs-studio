"""Publish options: the two paths must agree on what a tag is.

Regression guard for a real bug: drafts store tags as plain strings
(``["AI工具", "一人公司"]``) in 20 of 21 rows, but both ``_apply_publish_options``
implementations only understood ``[{"name": ...}]``. Every AI-generated tag was
dropped at publish time, and preflight simultaneously warned "no tags, add 3–8".
"""
from __future__ import annotations

from backend.app.services.publish_options_service import (
    apply_publish_options,
    clean_topics,
    resolve_topics,
    topics_from_draft_tags,
)


def test_clean_topics_trims_and_drops_empties():
    assert clean_topics(["  AI工具 ", "", "  ", None, "一人公司"]) == ["AI工具", "一人公司"]
    assert clean_topics(None) == []


def test_topics_from_string_tags_is_the_common_case():
    # This is the shape 20 of 21 real drafts store.
    assert topics_from_draft_tags(["AI工具", "一人公司"]) == ["AI工具", "一人公司"]


def test_topics_from_dict_tags_still_works():
    # Imported drafts (e.g. 抖音导入) store {"id", "name"} objects.
    tags = [{"id": "abc", "name": "AI工具"}, {"id": "def", "name": "一人公司"}]
    assert topics_from_draft_tags(tags) == ["AI工具", "一人公司"]


def test_topics_from_mixed_tags_and_dedupes():
    tags = ["AI工具", {"name": "一人公司"}, "AI工具", {"id": "x"}, ""]
    assert topics_from_draft_tags(tags) == ["AI工具", "一人公司"]


def test_topics_from_draft_tags_rejects_non_list():
    assert topics_from_draft_tags(None) == []
    assert topics_from_draft_tags({"name": "AI工具"}) == []


def test_explicit_topics_win_over_draft_tags():
    options = {"topics": ["显式话题"], "draft_tags": ["草稿标签"]}
    assert resolve_topics(options) == ["显式话题"]


def test_draft_tags_used_when_no_explicit_topics():
    options = {"draft_tags": ["AI工具", "一人公司"]}
    assert resolve_topics(options) == ["AI工具", "一人公司"]


def test_apply_publish_options_carries_string_tags_into_note_info():
    note_info: dict = {"title": "t", "desc": "b"}
    apply_publish_options(note_info, {"draft_tags": ["AI工具", "一人公司"]})
    assert note_info["topics"] == ["AI工具", "一人公司"]


def test_apply_publish_options_carries_dict_tags_into_note_info():
    note_info: dict = {"title": "t", "desc": "b"}
    apply_publish_options(note_info, {"draft_tags": [{"id": "a", "name": "AI工具"}]})
    assert note_info["topics"] == ["AI工具"]


def test_apply_publish_options_sets_location_and_privacy():
    note_info: dict = {}
    apply_publish_options(note_info, {"location": " 宁波 ", "privacy_type": 1})
    assert note_info["location"] == "宁波"
    assert note_info["type"] == 1


def test_apply_publish_options_ignores_blank_location_and_bad_privacy():
    note_info: dict = {}
    apply_publish_options(note_info, {"location": "   ", "privacy_type": 7})
    assert "location" not in note_info
    assert "type" not in note_info
