from __future__ import annotations

import re
from datetime import datetime
from statistics import median
from typing import Any, Iterable

from backend.app.models import Note
from backend.app.services.analytics_snapshot_service import (
    TITLE_PATTERNS,
    build_content_features,
    extract_note_metric_values,
)
from backend.app.services.note_metrics_service import parse_count

GROUP_ORDER = ("scale", "cadence", "structure", "performance", "growth")
GROUP_NAMES = {
    "scale": "规模",
    "cadence": "节奏",
    "structure": "内容结构",
    "performance": "效果",
    "growth": "增长",
}
GROUP_ADVICE = {
    "scale": "体量不是内容问题，重点看效果和增长两组。",
    "cadence": "发布间隔偏长或不稳定，先恢复固定节奏。",
    "structure": "选题/标签过散或过窄，收窄到 2–3 个核心方向。",
    "performance": "互动或收藏偏低，优先改封面、开头和可收藏价值。",
    "growth": "近期表现下滑，复盘最近 10 篇的选题和发布时间。",
}


def safe_div(numerator: float, denominator: float) -> float:
    return float(numerator or 0) / float(denominator) if denominator else 0.0


def percentile_rank(value: float | None, values: Iterable[float | None], higher_is_better: bool = True) -> float | None:
    clean = [float(item) for item in values if item is not None]
    if value is None or len(clean) < 2:
        return None
    if higher_is_better:
        better = sum(1 for item in clean if item < float(value))
    else:
        better = sum(1 for item in clean if item > float(value))
    return round(better / (len(clean) - 1) * 100, 1)


def _timestamp(value: Any, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if fallback is not None:
        return fallback
    if isinstance(value, (int, float)) and value:
        number = float(value)
        if number > 10**12:
            number /= 1000
        try:
            return datetime.fromtimestamp(number)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
        try:
            return _timestamp(float(text))
        except ValueError:
            return None
    return None


def _note_dict_metrics(note: dict[str, Any]) -> dict[str, int]:
    raw = note.get("raw") if isinstance(note.get("raw"), dict) else {}
    merged = {**raw, **note}
    values = {
        "likes": parse_count(merged.get("likes") or merged.get("like_count") or merged.get("liked_count")),
        "collects": parse_count(merged.get("collects") or merged.get("collect_count") or merged.get("collected_count")),
        "comments": parse_count(merged.get("comments") or merged.get("comment_count")),
        "shares": parse_count(merged.get("shares") or merged.get("share_count")),
        "views": parse_count(
            merged.get("views")
            or merged.get("view_count")
            or merged.get("viewCount")
            or merged.get("read_count")
            or merged.get("play_count")
        ),
        "fans": parse_count(merged.get("author_fans") or merged.get("fans") or merged.get("fans_count")),
    }
    for key, value in list(values.items()):
        values[key] = max(0, int(value or 0))
    return values


def _tags_for_note(note: dict[str, Any]) -> list[str]:
    tags = note.get("tags") or note.get("tag_list") or []
    if isinstance(tags, str):
        tags = [tags]
    result: list[str] = []
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, str):
                result.append(item.lstrip("#").strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("tag_name")
                if name:
                    result.append(str(name).lstrip("#").strip())
    result.extend(re.findall(r"#([^#\s]{1,30})", str(note.get("content") or "")))
    return [tag for tag in result if tag]


def _patterns_for_title(title: str) -> list[str]:
    return [name for name, pattern in TITLE_PATTERNS.items() if re.search(pattern, title or "", re.I)]


def _time_stats(notes: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[tuple[datetime, float]] = []
    for note in notes:
        metrics = _note_dict_metrics(note)
        engagement = metrics["likes"] + metrics["collects"] + metrics["comments"] + metrics["shares"]
        stamp = _timestamp(note.get("timestamp") or note.get("time") or note.get("publish_time"))
        if stamp and engagement > 0:
            points.append((stamp, float(engagement)))
    if len(points) < 2:
        return {"avg_days_between": None, "recent_days": None, "delta_pct": None, "early_median": None, "recent_median": None}
    points.sort(key=lambda item: item[0])
    days = [(points[index][0] - points[index - 1][0]).total_seconds() / 86400 for index in range(1, len(points))]
    days = [day for day in days if 0 < day < 365]
    mid = len(points) // 2
    early = [value for _, value in points[:mid]] or [value for _, value in points[:1]]
    recent = [value for _, value in points[mid:]] or [value for _, value in points[-1:]]
    early_median = median(early)
    recent_median = median(recent)
    return {
        "avg_days_between": round(sum(days) / len(days), 1) if days else None,
        "recent_days": round(max(0.0, (datetime.now() - points[-1][0]).total_seconds() / 86400), 1),
        "delta_pct": round(safe_div(recent_median - early_median, early_median) * 100, 1) if early_median else None,
        "early_median": round(early_median, 1),
        "recent_median": round(recent_median, 1),
    }


def account_diagnosis_raw(profile: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    fans = parse_count(profile.get("fans") or profile.get("followers") or profile.get("fans_count"))
    metrics_list = [_note_dict_metrics(note) for note in notes]
    engagements = [m["likes"] + m["collects"] + m["comments"] + m["shares"] for m in metrics_list]
    total_engagement = sum(engagements)
    avg_engagement = safe_div(total_engagement, len(engagements))
    median_engagement = median(engagements) if engagements else 0.0
    views_total = sum(m["views"] for m in metrics_list)
    has_views = views_total > 0
    basis = "views" if has_views else ("fans" if fans else "none")

    def rate_for_note(item: dict[str, int], numerator: float) -> float:
        if basis == "views":
            return safe_div(numerator, item["views"])
        if basis == "fans":
            return safe_div(numerator, fans)
        engagement = item["likes"] + item["collects"] + item["comments"] + item["shares"]
        return safe_div(numerator, engagement)

    engagement_rates = [
        rate_for_note(item, item["likes"] + item["collects"] + item["comments"] + item["shares"])
        for item in metrics_list
    ]
    save_rates = [rate_for_note(item, item["collects"]) for item in metrics_list]
    comment_rates = [rate_for_note(item, item["comments"]) for item in metrics_list]
    share_rates = [rate_for_note(item, item["shares"]) for item in metrics_list]
    collect_per_like = [safe_div(m["collects"], m["likes"]) for m in metrics_list if m["likes"] > 0]
    hit_threshold = median_engagement * 3
    hits = [value for value in engagements if hit_threshold > 0 and value > hit_threshold]

    all_tags: list[str] = []
    patterns: list[str] = []
    for note in notes:
        all_tags.extend(_tags_for_note(note))
        patterns.extend(_patterns_for_title(str(note.get("title") or "")))
    tag_counts: dict[str, int] = {}
    for tag in all_tags:
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tag_share = safe_div(max(tag_counts.values(), default=0), len(all_tags))
    pattern_counts: dict[str, int] = {}
    for pattern in patterns:
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    top_pattern_share = safe_div(max(pattern_counts.values(), default=0), len(patterns))
    time_stats = _time_stats(notes)

    return {
        "basis": basis,
        "scale": {
            "fans": fans,
            "total_notes": len(notes),
            "total_engagement": total_engagement,
            "avg_engagement": round(avg_engagement, 1),
            "median_engagement": round(median_engagement, 1),
        },
        "cadence": {
            "avg_days_between": time_stats["avg_days_between"],
            "recent_days": time_stats["recent_days"],
            "video_ratio": safe_div(sum(1 for note in notes if str(note.get("type") or "").lower() == "video"), len(notes)),
        },
        "structure": {
            "tag_diversity": len(tag_counts),
            "title_pattern_diversity": len(pattern_counts),
            "top_tag_share": round(top_tag_share, 3),
            "top_pattern_share": round(top_pattern_share, 3),
        },
        "performance": {
            "median_engagement_rate": round(median(engagement_rates), 4) if engagement_rates else 0.0,
            "median_save_rate": round(median(save_rates), 4) if save_rates else 0.0,
            "median_comment_rate": round(median(comment_rates), 4) if comment_rates else 0.0,
            "median_share_rate": round(median(share_rates), 4) if share_rates else 0.0,
            "hit_rate": round(safe_div(len(hits), len(engagements)), 4),
            "collect_per_like": round(median(collect_per_like), 4) if collect_per_like else 0.0,
        },
        "growth": {
            "delta_pct": time_stats["delta_pct"],
            "early_median": time_stats["early_median"],
            "recent_median": time_stats["recent_median"],
        },
        "has_views": has_views,
    }


def _group_metric_defs() -> dict[str, list[tuple[str, str, str, bool]]]:
    """(key, label, unit, higher_is_better) per group."""
    return {
        "scale": [
            ("fans", "粉丝", "", True),
            ("total_notes", "笔记数", "", True),
            ("total_engagement", "总互动", "", True),
            ("avg_engagement", "篇均互动", "", True),
        ],
        "cadence": [
            ("avg_days_between", "平均间隔", "天", False),
            ("recent_days", "最近更新", "天前", False),
        ],
        "structure": [
            ("tag_diversity", "标签多样性", "", True),
            ("title_pattern_diversity", "标题模式数", "", True),
        ],
        "performance": [
            ("median_engagement_rate", "中位互动率", "%", True),
            ("median_save_rate", "中位收藏率", "%", True),
            ("median_comment_rate", "中位评论率", "%", True),
            ("median_share_rate", "中位分享率", "%", True),
            ("hit_rate", "爆文率", "%", True),
            ("collect_per_like", "赞藏比", "", True),
        ],
        "growth": [
            ("delta_pct", "近期变化", "%", True),
        ],
    }


def _display_metric_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in {
        "median_engagement_rate",
        "median_save_rate",
        "median_comment_rate",
        "median_share_rate",
        "hit_rate",
    }:
        return round(float(value) * 100, 2)
    return value


def apply_account_diagnosis_percentiles(items: list[dict[str, Any]]) -> None:
    """Attach a 5-group percentile diagnosis to account-report items in place."""
    if not items:
        return
    raw_items = [item.get("diagnosis_raw") for item in items if isinstance(item.get("diagnosis_raw"), dict)]
    cohort_size = len(raw_items)
    for item in items:
        raw = item.get("diagnosis_raw") if isinstance(item.get("diagnosis_raw"), dict) else {}
        if not raw:
            item.pop("diagnosis_raw", None)
            continue
        groups = []
        all_group_scores: list[float] = []
        for group_key in GROUP_ORDER:
            metrics = []
            scores = []
            for metric_key, label, unit, higher in _group_metric_defs()[group_key]:
                value = (raw.get(group_key) or {}).get(metric_key)
                values = [(entry.get(group_key) or {}).get(metric_key) for entry in raw_items]
                percentile = percentile_rank(value, values, higher_is_better=higher) if cohort_size >= 2 else None
                if percentile is not None:
                    scores.append(percentile)
                metrics.append(
                    {
                        "key": metric_key,
                        "label": label,
                        "value": _display_metric_value(metric_key, value),
                        "unit": unit,
                        "direction": "higher" if higher else "lower",
                        "percentile": percentile,
                    }
                )
            score = round(sum(scores) / len(scores), 1) if scores else 50.0
            all_group_scores.append(score)
            groups.append(
                {
                    "key": group_key,
                    "name": GROUP_NAMES[group_key],
                    "score": score,
                    "metrics": metrics,
                    "advice": GROUP_ADVICE[group_key],
                }
            )
        weakest = min(groups, key=lambda group: group["score"]) if groups else None
        if cohort_size < 2:
            summary = "同批账号不足 2 个，暂不计算百分位；建议一次对比多个账号。"
        else:
            summary = (
                f"当前最弱项：{weakest['name']}（{weakest['score']} 分）。{weakest['advice']}"
                if weakest
                else "数据不足，先积累 10 篇以上笔记再做诊断。"
            )
        item["diagnosis"] = {
            "groups": groups,
            "cohort_size": cohort_size,
            "basis": raw.get("basis", "none"),
            "has_views": bool(raw.get("has_views")),
            "summary": summary,
            "note": "分数是同一批账号内的百分位；少于 2 个账号时统一显示 50 分。" if cohort_size < 2 else "",
        }
        item.pop("diagnosis_raw", None)


def _raw_percent(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        try:
            number = float(str(value).replace("%", "").strip())
        except (TypeError, ValueError):
            continue
        return number * 100 if 0 < number <= 1 else number
    return None


def _relative_level(multiple: float | None) -> str:
    if multiple is None:
        return "样本不足"
    if multiple > 3:
        return "爆款"
    if multiple >= 1.5:
        return "潜力"
    if multiple >= 0.7:
        return "正常"
    return "低于预期"


def build_note_diagnosis(note: Note, peers: list[Note], fans_fallback: int = 0) -> dict[str, Any]:
    metrics = extract_note_metric_values(note)
    if not metrics["fans"] and fans_fallback:
        metrics["fans"] = max(0, int(fans_fallback))
    engagement = metrics["likes"] + metrics["collects"] + metrics["comments"] + metrics["shares"]
    peer_metrics = [extract_note_metric_values(peer) for peer in peers if peer.id != note.id]
    peer_engagements = [
        item["likes"] + item["collects"] + item["comments"] + item["shares"]
        for item in peer_metrics
        if item["likes"] + item["collects"] + item["comments"] + item["shares"] > 0
    ]
    baseline = median(peer_engagements) if peer_engagements else 0.0
    multiple = safe_div(engagement, baseline) if baseline else None
    features = build_content_features(note)
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}

    views = metrics["views"]
    fans = metrics["fans"]
    if views > 0:
        basis = "views"
        rates = {
            "engagement_rate": safe_div(engagement, views),
            "save_rate": safe_div(metrics["collects"], views),
            "comment_rate": safe_div(metrics["comments"], views),
            "share_rate": safe_div(metrics["shares"], views),
        }
        proxy = False
    elif fans > 0:
        basis = "fans"
        rates = {
            "engagement_rate": safe_div(engagement, fans),
            "save_rate": safe_div(metrics["collects"], engagement),
            "comment_rate": safe_div(metrics["comments"], engagement),
            "share_rate": safe_div(metrics["shares"], engagement),
        }
        proxy = True
    else:
        basis = "none"
        rates = {"engagement_rate": 0.0, "save_rate": 0.0, "comment_rate": 0.0, "share_rate": 0.0}
        proxy = True

    cover_ctr = _raw_percent(raw, ("cover_click_rate", "cover_ctr", "ctr", "封面点击率"))
    completion = _raw_percent(raw, ("completion_rate", "完播率", "play_progress"))
    follows_gained = parse_count(raw.get("follows_gained") or raw.get("new_followers") or raw.get("涨粉量"))

    stages = [
        {
            "key": "exposure",
            "name": "曝光/观看",
            "value": views or None,
            "unit": "",
            "percent": None,
            "status": "ok" if views > 0 else "missing",
            "hint": "" if views > 0 else "需要创作者后台的观看/曝光数据",
        },
        {
            "key": "click",
            "name": "封面点击",
            "value": cover_ctr,
            "unit": "%",
            "percent": cover_ctr,
            "status": "ok" if cover_ctr is not None else "missing",
            "hint": "" if cover_ctr is not None else "需要封面点击率",
        },
        {
            "key": "read",
            "name": "完播/完读",
            "value": completion,
            "unit": "%",
            "percent": completion,
            "status": "ok" if completion is not None else "missing",
            "hint": "" if completion is not None else "需要完播率或平均观看时长",
        },
        {
            "key": "engage",
            "name": "互动",
            "value": round(rates["engagement_rate"] * 100, 2) if basis == "views" else engagement,
            "unit": "%" if basis == "views" else "",
            "percent": round(rates["engagement_rate"] * 100, 2) if basis == "views" else None,
            "status": "ok" if basis == "views" else ("proxy" if basis == "fans" else "missing"),
            "hint": (
                ""
                if basis == "views"
                else ("暂用粉丝数做分母，补观看数据后更准" if basis == "fans" else "缺少观看和粉丝数据")
            ),
        },
        {
            "key": "follow",
            "name": "涨粉",
            "value": follows_gained or None,
            "unit": "",
            "percent": round(safe_div(follows_gained, views) * 100, 2) if views and follows_gained else None,
            "status": "ok" if follows_gained else "missing",
            "hint": "" if follows_gained else "需要新增关注/涨粉数据",
        },
    ]

    if views <= 0:
        bottleneck = "exposure_data"
    elif rates["engagement_rate"] < 0.05:
        bottleneck = "engagement"
    elif rates["save_rate"] < 0.02:
        bottleneck = "save"
    elif rates["comment_rate"] < 0.01:
        bottleneck = "comment"
    else:
        bottleneck = "none"

    suggestions: list[str] = []
    title_patterns = features.get("title_patterns") or []
    if "数字型" not in title_patterns:
        suggestions.append("标题加一个具体数字或时间（3 个方法 / 5 分钟）。")
    if not features.get("cta_types"):
        suggestions.append("结尾加一个具体问题或收藏引导。")
    if (features.get("structure") or {}).get("paragraphs", 0) < 3:
        suggestions.append("正文拆成 3–5 个要点，方便收藏和复看。")
    if rates["save_rate"] < 0.03 and basis == "views":
        suggestions.append("提高可收藏价值：清单、步骤、对比表。")
    if rates["comment_rate"] < 0.02 and basis == "views":
        suggestions.append("中段设置一个评论触发点（提问/投票/反差）。")

    return {
        "note_id": note.id,
        "platform_note_id": note.note_id,
        "title": note.title,
        "metrics": metrics,
        "engagement": engagement,
        "basis": basis,
        "proxy": proxy,
        "rates": {key: round(value, 4) for key, value in rates.items()},
        "relative": {
            "baseline_engagement": round(baseline, 1),
            "multiple": round(multiple, 2) if multiple is not None else None,
            "percentile": percentile_rank(engagement, peer_engagements),
            "collect_per_like": round(safe_div(metrics["collects"], metrics["likes"]), 3),
            "level": _relative_level(multiple),
            "peer_count": len(peer_engagements),
        },
        "funnel": {
            "stages": stages,
            "bottleneck": bottleneck,
            "missing": [stage["key"] for stage in stages if stage["status"] == "missing"],
        },
        "features": features,
        "suggestions": suggestions[:5] or ["数据完整，保持当前结构。"],
        "data_quality": {
            "has_views": views > 0,
            "has_snapshots": False,
            "peer_count": len(peer_engagements),
        },
    }
