"""Local banned-word check + seven-dimension account scorecard."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.services.account_report_service import _build_scorecard
from backend.app.services.sensitive_word_service import check_local

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_local_sensitive_words_find_hits():
    result = check_local("全网最好的产品，永久有效，100%治愈，加微信详聊")

    assert result["clean"] is False
    assert result["hit_count"] >= 4
    assert result["source"] == "local"
    words = {hit["word"] for hit in result["hits"]}
    assert "最好" in words or "全网最" in words
    assert "加微信" in words
    assert '<span class="banned-word">' in result["highlighted"]


def test_local_sensitive_words_clean_text():
    result = check_local("今天天气不错，出门散步")

    assert result["clean"] is True
    assert result["hit_count"] == 0
    assert result["highlighted"] == "今天天气不错，出门散步"


def test_local_sensitive_words_escape_markup():
    result = check_local("<script>alert(1)</script>最好")

    assert "<script>" not in result["highlighted"]
    assert "&lt;script&gt;" in result["highlighted"]


def _note(index: int, *, likes=50, collects=30, cover=True, days_ago=3, title=None):
    return {
        "note_id": f"n{index}",
        "title": title or f"标题{index}",
        "likes": likes,
        "collects": collects,
        "comments": 5,
        "shares": 2,
        "cover": "https://img" if cover else "",
        "timestamp": int((datetime.now(SHANGHAI) - timedelta(days=days_ago)).timestamp()),
    }


def test_scorecard_has_seven_dimensions():
    notes = [_note(i) for i in range(6)]
    card = _build_scorecard(
        {"nickname": "测试账号", "desc": "分享打工人早餐，5 分钟搞定，适合早八人"},
        notes,
        fans=3000,
        post_count=len(notes),
        avg_engagement=87,
        total_engagement=522,
    )

    assert len(card["dimensions"]) == 7
    keys = [item["key"] for item in card["dimensions"]]
    assert keys == ["positioning", "fans", "topics", "covers", "hits", "engagement", "output"]
    assert 0 <= card["total"] <= 100
    assert card["grade"] in {"S", "A", "B", "C"}
    assert len(card["suggestions"]) == 2


def test_scorecard_penalises_empty_account():
    card = _build_scorecard(
        {"nickname": "x", "desc": ""},
        [],
        fans=0,
        post_count=0,
        avg_engagement=0,
        total_engagement=0,
    )

    scores = {item["key"]: item["score"] for item in card["dimensions"]}
    assert scores["positioning"] < 60
    assert scores["fans"] < 50
    assert scores["topics"] < 50
    assert card["total"] < 60


def test_scorecard_rewards_active_account():
    notes = [_note(i, likes=1200, collects=900, days_ago=2) for i in range(12)]
    card = _build_scorecard(
        {"nickname": "早餐研究所", "desc": "每天分享一个 5 分钟早餐方案，适合早八打工人，已更新 200 期"},
        notes,
        fans=60000,
        post_count=len(notes),
        avg_engagement=2400,
        total_engagement=28800,
    )

    scores = {item["key"]: item["score"] for item in card["dimensions"]}
    assert scores["fans"] >= 90
    assert scores["hits"] >= 85
    assert scores["output"] >= 65
    assert card["total"] >= 70


def test_local_sensitive_words_cover_industry_categories():
    result = check_local("美白祛斑，稳赚不赔，保过，加微信领资料")

    kinds = {hit["kind"] for hit in result["hits"]}
    assert {"美妆护肤", "金融理财", "教育培训", "引流导流"} <= kinds
    assert result["word_count"] >= 120
    assert all(hit["hint"] for hit in result["hits"])


def test_extract_keywords_returns_real_words():
    from backend.app.services.viral_analysis_service import extract_keywords

    words = extract_keywords(
        [
            "宁波9.27｜零基础用AI做产品线下沙龙",
            "聊聊AI做产品线下沙龙的复盘，普通人也能上手",
        ],
        top_n=8,
    )

    assert "线下沙龙" in words
    assert any(word in words for word in ("产品", "ai"))
    garbage = {"有这么流口", "么流口水", "品线下沙", "零基础用", "你们的"}
    assert not (set(words) & garbage)
    assert all(len(word) >= 2 for word in words)


def test_extract_keywords_keeps_hashtags():
    from backend.app.services.viral_analysis_service import extract_keywords

    words = extract_keywords(["#咖啡店探店 咖啡店打工人的职场日常"], top_n=5)

    assert "咖啡店探店" in words
    assert any(word in words for word in ("职场", "打工人"))
    # 子串重复项会被去重，避免「咖啡店探店」和「咖啡店」同时占位
    assert "咖啡店" not in words


def test_extract_keywords_works_for_single_note():
    from backend.app.services.viral_analysis_service import extract_keywords

    words = extract_keywords(["咖啡店打工人的职场日常｜第三空间观察笔记"], top_n=8)

    assert "咖啡店" in words or "职场" in words
    assert len(words) >= 2
