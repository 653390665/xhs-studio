"""Tests for the content-to-topic recommendation logic."""

from __future__ import annotations

import pytest

from backend.app.services import topic_recommendation_service as svc


def test_bigram_similarity_prefers_overlapping_text():
    assert svc.bigram_similarity("秋天的第一杯咖啡", "秋天的第一杯奶茶") > 0.4
    assert svc.bigram_similarity("秋天的第一杯咖啡", "显卡驱动更新教程") < 0.1


def test_longest_common_phrase():
    assert svc.longest_common_phrase("秋天的第一杯咖啡", "秋天的第一杯奶茶") == "秋天的第一杯"
    assert svc.longest_common_phrase("完全无关", "显卡驱动") == ""


def test_extract_hashtags():
    assert svc.extract_hashtags("今天喝咖啡 #咖啡日常 #通勤 好喝") == ["咖啡日常", "通勤"]


def test_recommend_ranks_overlapping_topic_first(monkeypatch):
    monkeypatch.setattr(
        svc,
        "fetch_free_hot_list",
        lambda: (
            True,
            "ok",
            {
                "items": [
                    {
                        "title": "显卡驱动更新教程",
                        "hot_text": "900w",
                        "hot_score": 9_000_000,
                        "url": "",
                        "word_type": "",
                    },
                    {
                        "title": "秋天的第一杯奶茶",
                        "hot_text": "800w",
                        "hot_score": 8_000_000,
                        "url": "",
                        "word_type": "热",
                    },
                ]
            },
        ),
    )

    success, message, data = svc.recommend_topics("秋天的第一杯咖啡真好喝 #咖啡日常")

    assert success is True, message
    assert data["items"][0]["title"] == "秋天的第一杯奶茶"
    assert data["items"][0]["score"] > 0
    assert data["hashtags"] == ["咖啡日常"]
    assert data["total_candidates"] == 2


def test_recommend_ignores_common_word_overlap(monkeypatch):
    monkeypatch.setattr(
        svc,
        "fetch_free_hot_list",
        lambda: (
            True,
            "ok",
            {
                "items": [
                    {"title": "原来古诗词里的河南真的存在", "hot_text": "727w", "hot_score": 7_270_000, "url": "", "word_type": ""},
                ]
            },
        ),
    )

    success, message, data = svc.recommend_topics("这个真的可以，我觉得不错")

    assert success is True, message
    assert data["items"][0]["source"] == "hot_search_fallback"


def test_recommend_falls_back_to_hottest_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(
        svc,
        "fetch_free_hot_list",
        lambda: (
            True,
            "ok",
            {
                "items": [
                    {"title": "量子计算新突破", "hot_text": "1w", "hot_score": 10_000, "url": "", "word_type": ""},
                    {"title": "考古发现", "hot_text": "0.9w", "hot_score": 9_000, "url": "", "word_type": ""},
                ]
            },
        ),
    )

    success, message, data = svc.recommend_topics("今天天气不错")

    assert success is True, message
    assert len(data["items"]) == 2
    assert data["items"][0]["source"] == "hot_search_fallback"


def test_recommend_requires_content():
    success, message, data = svc.recommend_topics("   ")
    assert success is False
    assert data is None
    assert "内容" in message


def test_recommend_falls_back_to_local_keywords_when_hot_source_fails(monkeypatch):
    """A hot-search outage must not break the feature.

    Behaviour changed deliberately: the old contract returned failure and left
    the user with nothing. Now a source outage degrades to locally extracted
    keywords and says so in the message.
    """
    monkeypatch.setattr(svc, "fetch_free_hot_list", lambda: (False, "热搜源不可用", None))

    success, message, data = svc.recommend_topics("咖啡")

    assert success is True
    assert data is not None
    assert "热搜源不可用" in message
    assert "本地" in message
    assert data["fallback"] is True
    assert data["items"], "short content must still yield at least one local topic"


def test_recommend_uses_local_topics_when_hot_source_is_rate_limited(monkeypatch):
    monkeypatch.setattr(
        svc,
        "fetch_free_hot_list",
        lambda: (False, "免费热搜源限流（429）", None),
    )

    success, message, data = svc.recommend_topics("通勤咖啡怎么选 #咖啡 #通勤日常")

    assert success is True
    assert data["fallback"] is True
    assert data["items"][0]["source"] == "local_fallback"
    assert "咖啡" in data["items"][0]["title"]
    assert "限流" in message
