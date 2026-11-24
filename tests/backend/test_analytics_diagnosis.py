from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.models import Note
from backend.app.services.account_report_service import build_account_report
from backend.app.services.analytics_snapshot_service import (
    build_content_features,
    extract_note_metric_values,
)
from backend.app.services.diagnosis_service import (
    account_diagnosis_raw,
    apply_account_diagnosis_percentiles,
    build_note_diagnosis,
    percentile_rank,
)


def make_note(note_id: int, **overrides) -> Note:
    note = Note(
        user_id=1,
        platform_account_id=1,
        platform="xhs",
        note_id=f"n{note_id}",
        title="3个方法让你避雷",
        content="第一段：先说痛点。\n1. 方法一\n2. 方法二\n3. 方法三\n评论区告诉我你踩过哪个坑？",
        like_count=100,
        collect_count=50,
        comment_count=10,
        share_count=5,
        author_fans=1000,
        raw_json={"view_count": 5000, "tags": ["护肤", "避雷"]},
        created_at=datetime(2026, 10, 1) + timedelta(days=note_id),
    )
    note.id = note_id
    for key, value in overrides.items():
        setattr(note, key, value)
    return note


def test_percentile_rank_handles_small_and_directional_samples():
    assert percentile_rank(10, [10]) is None
    assert percentile_rank(10, [10, 20]) == 0.0
    assert percentile_rank(20, [10, 20]) == 100.0
    assert percentile_rank(1, [1, 2, 3], higher_is_better=False) == 100.0
    assert percentile_rank(3, [1, 2, 3], higher_is_better=False) == 0.0


def test_extract_note_metric_values_prefers_columns_and_reads_views():
    note = make_note(1, like_count=0, raw_json={"view_count": "1.2万", "liked_count": "300"})
    metrics = extract_note_metric_values(note)
    assert metrics["likes"] == 300
    assert metrics["views"] == 12000
    assert metrics["fans"] == 1000


def test_content_features_extract_title_cta_and_structure():
    note = make_note(1)
    features = build_content_features(note)
    assert "数字型" in features["title_patterns"]
    assert "教程型" in features["title_patterns"]
    assert "避雷" in features["hook_words"]
    assert "评论引导" in features["cta_types"]
    assert features["structure"]["paragraphs"] >= 3
    assert features["tag_count"] == 2


def test_note_diagnosis_uses_views_and_relative_baseline():
    note = make_note(1)
    peer = make_note(2, like_count=200, collect_count=100, comment_count=20, share_count=10, raw_json={"view_count": 6000})
    peer2 = make_note(3, like_count=250, collect_count=120, comment_count=25, share_count=5, raw_json={"view_count": 7000})
    diagnosis = build_note_diagnosis(note, [note, peer, peer2])
    assert diagnosis["basis"] == "views"
    assert diagnosis["proxy"] is False
    assert diagnosis["relative"]["baseline_engagement"] == 365
    assert diagnosis["relative"]["percentile"] == 0.0
    assert diagnosis["funnel"]["stages"][0]["status"] == "ok"
    assert diagnosis["funnel"]["stages"][1]["status"] == "missing"


def test_account_diagnosis_percentiles_assign_five_groups_and_scores():
    notes_a = [
        {"title": "3个方法", "likes": 100, "collects": 50, "comments": 10, "shares": 5, "timestamp": 1700000000},
        {"title": "避雷清单", "likes": 200, "collects": 100, "comments": 20, "shares": 10, "timestamp": 1700600000},
    ]
    notes_b = [
        {"title": "日常分享", "likes": 10, "collects": 2, "comments": 1, "shares": 0, "timestamp": 1700000000},
    ]
    items = [
        {"diagnosis_raw": account_diagnosis_raw({"fans": 1000}, notes_a)},
        {"diagnosis_raw": account_diagnosis_raw({"fans": 1000}, notes_b)},
    ]
    apply_account_diagnosis_percentiles(items)
    diagnosis = items[0]["diagnosis"]
    assert len(diagnosis["groups"]) == 5
    assert diagnosis["cohort_size"] == 2
    assert diagnosis["basis"] == "fans"
    assert all(0 <= group["score"] <= 100 for group in diagnosis["groups"])
    assert "diagnosis_raw" not in items[0]


def test_account_diagnosis_single_account_marks_sample_insufficient():
    items = [{"diagnosis_raw": account_diagnosis_raw({"fans": 1000}, [{"title": "x", "likes": 1}])}]
    apply_account_diagnosis_percentiles(items)
    diagnosis = items[0]["diagnosis"]
    assert diagnosis["cohort_size"] == 1
    assert all(group["score"] == 50.0 for group in diagnosis["groups"])
    assert diagnosis["note"]


def test_account_report_attaches_percentile_diagnosis():
    profiles = [
        {"user_id": "u1", "nickname": "A", "fans": 1000},
        {"user_id": "u2", "nickname": "B", "fans": 2000},
    ]
    notes = [
        {
            "note_id": "n1",
            "title": "3个方法让你避雷",
            "likes": 100,
            "collects": 50,
            "comments": 10,
            "shares": 5,
            "timestamp": 1700000000,
        },
        {
            "note_id": "n2",
            "title": "避雷清单",
            "likes": 200,
            "collects": 100,
            "comments": 20,
            "shares": 10,
            "timestamp": 1700600000,
        },
    ]
    items = [
        build_account_report(profiles[0], notes),
        build_account_report(profiles[1], notes),
    ]
    apply_account_diagnosis_percentiles(items)
    assert all("diagnosis" in item for item in items)
    assert items[0]["diagnosis"]["cohort_size"] == 2
    assert len(items[0]["diagnosis"]["groups"]) == 5
    assert "diagnosis_raw" not in items[0]
