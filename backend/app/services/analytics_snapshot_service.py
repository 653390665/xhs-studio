from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import AnalysisRun, FeatureSnapshot, MetricSnapshot, Note
from backend.app.services.note_metrics_service import parse_count

CONTENT_FEATURE_SET = "content_rules_v1"
NOTE_METRICS = ("likes", "collects", "comments", "shares", "views", "fans")

TITLE_PATTERNS = {
    "数字型": r"\d+",
    "疑问型": r"[？?]|怎么|如何|为什么|什么",
    "感叹型": r"[！!]|绝了|太|真的|居然|竟然",
    "教程型": r"教程|手把手|保姆级|步骤|方法|攻略",
    "列表型": r"合集|盘点|推荐|必备|top|榜",
    "对比型": r"vs|对比|区别|差异|还是",
    "故事型": r"我|亲身|经历|踩坑|分享|心得",
    "悬念型": r"\.\.\.|…|竟然|没想到|万万|千万",
}

HOOK_WORDS = (
    "别再", "千万别", "后悔", "踩坑", "避雷", "真相", "居然", "竟然", "原来", "终于",
    "第一次", "最后一次", "秘密", "隐藏", "亲测", "实测", "翻车", "救命",
)

CTA_PATTERNS = {
    "关注引导": r"关注|点个关注|记得关注",
    "收藏引导": r"收藏|先收藏|码住|mark",
    "点赞引导": r"点赞|双击|给个赞",
    "评论引导": r"评论|留言|告诉我|你们觉得|欢迎讨论",
    "转发引导": r"转发|分享给",
    "私信引导": r"私信|私我|后台回复|滴滴",
}

HASHTAG_RE = re.compile(r"#([^#\s\[\]]{1,30})")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
VIEW_KEYS = ("view_count", "views", "viewCount", "read_count", "play_count", "impression_count")
FOLLOW_KEYS = ("follows_gained", "new_followers", "fans_gained", "涨粉量")


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return parse_count(value)


def _raw_dict(note: Note) -> dict[str, Any]:
    raw = note.raw_json
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _raw_value(raw: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in raw and raw[key] is not None:
            return _as_int(raw[key])
    for container_key in ("note", "note_card", "data", "interact_info", "interactInfo"):
        container = raw.get(container_key)
        if isinstance(container, dict):
            for key in keys:
                if key in container and container[key] is not None:
                    return _as_int(container[key])
    return 0


def extract_note_metric_values(note: Note) -> dict[str, int]:
    """Return raw counters, preferring DB columns and falling back to raw_json."""
    raw = _raw_dict(note)
    values = {
        "likes": int(note.like_count or 0) or _raw_value(raw, ("likes", "liked_count", "like_count", "likedCount")),
        "collects": int(note.collect_count or 0) or _raw_value(raw, ("collects", "collected_count", "collect_count", "collectedCount")),
        "comments": int(note.comment_count or 0) or _raw_value(raw, ("comments", "comment_count", "commentCount")),
        "shares": int(note.share_count or 0) or _raw_value(raw, ("shares", "share_count", "shareCount")),
        "views": _raw_value(raw, VIEW_KEYS),
        "fans": int(note.author_fans or 0) or _raw_value(raw, ("author_fans", "fans", "fans_count")),
    }
    for name, value in list(values.items()):
        values[name] = max(0, int(value or 0))
    return values


def _latest_snapshot_at(db: Session, note: Note) -> datetime | None:
    return db.scalar(
        select(MetricSnapshot.captured_at)
        .where(
            MetricSnapshot.user_id == note.user_id,
            MetricSnapshot.scope == "note",
            MetricSnapshot.ref_id == note.id,
        )
        .order_by(MetricSnapshot.captured_at.desc())
        .limit(1)
    )


def _latest_snapshot_values(db: Session, note: Note) -> dict[str, float]:
    rows = db.scalars(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.user_id == note.user_id,
            MetricSnapshot.scope == "note",
            MetricSnapshot.ref_id == note.id,
        )
        .order_by(MetricSnapshot.captured_at.desc(), MetricSnapshot.id.desc())
    ).all()
    latest: dict[str, float] = {}
    for row in rows:
        if row.metric_name not in latest:
            latest[row.metric_name] = float(row.metric_value)
    return latest


def record_note_snapshot(
    db: Session,
    note: Note,
    *,
    source: str = "save",
    captured_at: datetime | None = None,
    force: bool = False,
) -> int:
    """Append a snapshot when counters changed (or at most once per 12h)."""
    values = extract_note_metric_values(note)
    if not any(values.get(name, 0) for name in NOTE_METRICS):
        return 0

    latest_values = _latest_snapshot_values(db, note)
    latest_at = _latest_snapshot_at(db, note)
    now = shanghai_now()
    target_time = captured_at or note.metrics_fetched_at or now

    changed = any(latest_values.get(name) != float(value) for name, value in values.items())
    stale = latest_at is None or target_time - latest_at >= timedelta(hours=12)
    if not force and not changed and not stale:
        return 0

    rows = []
    for name in NOTE_METRICS:
        value = values.get(name, 0)
        if name in ("views", "fans") and value <= 0:
            continue
        rows.append(
            MetricSnapshot(
                user_id=note.user_id,
                platform=note.platform or "xhs",
                scope="note",
                ref_id=note.id,
                metric_name=name,
                metric_value=float(value),
                source=source,
                captured_at=target_time,
            )
        )
    db.add_all(rows)
    return len(rows)


def _extract_tags(note: Note, raw: dict[str, Any], body: str) -> list[str]:
    tags: list[str] = []
    for key in ("tags", "tag_list", "tagList", "topics"):
        value = raw.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    tags.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("tag_name")
                    if name:
                        tags.append(str(name).strip())
    tags.extend(HASHTAG_RE.findall(body or ""))
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        cleaned = tag.lstrip("#").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result[:20]


def _note_format(note: Note, raw: dict[str, Any]) -> str:
    value = str(raw.get("note_type") or raw.get("type") or raw.get("content_type") or "").lower()
    if "video" in value or "视频" in value:
        return "video"
    if value in {"normal", "image", "图文"}:
        return "image"
    width = _raw_value(raw, ("width", "image_width"))
    height = _raw_value(raw, ("height", "image_height"))
    return "video" if width and height and height > width * 1.2 else "image"


def build_content_features(note: Note) -> dict[str, Any]:
    raw = _raw_dict(note)
    title = note.title or ""
    body = note.content or ""
    tags = _extract_tags(note, raw, body)
    patterns = [name for name, pattern in TITLE_PATTERNS.items() if re.search(pattern, title, re.I)]
    hooks = [word for word in HOOK_WORDS if word in title or word in body[:200]]
    ctas = [name for name, pattern in CTA_PATTERNS.items() if re.search(pattern, body, re.I)]
    paragraphs = [line for line in body.splitlines() if line.strip()]
    char_count = len(re.sub(r"\s", "", body))
    if char_count < 200:
        length_bucket = "short"
    elif char_count < 500:
        length_bucket = "medium"
    else:
        length_bucket = "long"
    structure = {
        "paragraphs": len(paragraphs),
        "char_count": char_count,
        "length_bucket": length_bucket,
        "has_list": bool(re.search(r"^[\s]*[-•●]\s", body, re.M)),
        "has_number_heading": bool(re.search(r"[①②③④⑤⑥⑦⑧⑨⑩]|[1-9][.、]", body)),
        "emoji_count": len(EMOJI_RE.findall(body)),
    }
    publish_time = (
        raw.get("time")
        or raw.get("timestamp")
        or raw.get("publish_time")
        or note.created_at.isoformat()
    )
    return {
        "title": title,
        "title_length": len(title),
        "title_patterns": patterns,
        "hook_words": hooks,
        "cta_types": ctas,
        "tags": tags,
        "tag_count": len(tags),
        "format": _note_format(note, raw),
        "structure": structure,
        "publish_time": str(publish_time),
        "has_views": extract_note_metric_values(note)["views"] > 0,
    }


def record_note_features(
    db: Session,
    note: Note,
    *,
    source: str = "rules",
    force: bool = False,
) -> bool:
    payload = build_content_features(note)
    existing = db.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.scope == "note",
            FeatureSnapshot.ref_id == note.id,
            FeatureSnapshot.feature_set == CONTENT_FEATURE_SET,
        )
    )
    if existing is None:
        db.add(
            FeatureSnapshot(
                user_id=note.user_id,
                platform=note.platform or "xhs",
                scope="note",
                ref_id=note.id,
                feature_set=CONTENT_FEATURE_SET,
                feature_json=payload,
                source=source,
                analyzed_at=shanghai_now(),
            )
        )
        return True
    if not force and existing.feature_json == payload:
        return False
    existing.feature_json = payload
    existing.source = source
    existing.analyzed_at = shanghai_now()
    return True


def record_note_analytics(
    db: Session,
    note: Note,
    *,
    source: str = "save",
    force: bool = False,
    commit: bool = False,
) -> dict[str, int]:
    if note.id is None:
        db.flush()
    snapshots = record_note_snapshot(db, note, source=source, force=force)
    features = 1 if record_note_features(db, note, source=source, force=force) else 0
    if commit:
        db.commit()
    return {"snapshots": snapshots, "features": features}


def backfill_user_analytics(db: Session, user_id: int) -> dict[str, Any]:
    notes = db.scalars(select(Note).where(Note.user_id == user_id)).all()
    snapshot_rows = 0
    feature_rows = 0
    for note in notes:
        result = record_note_analytics(db, note, source="backfill")
        snapshot_rows += result["snapshots"]
        feature_rows += result["features"]
    run = AnalysisRun(
        user_id=user_id,
        scope="backfill",
        status="ok",
        params_json={"notes": len(notes)},
        summary_json={"snapshots": snapshot_rows, "features": feature_rows},
        finished_at=shanghai_now(),
    )
    db.add(run)
    db.commit()
    return {
        "notes": len(notes),
        "snapshots": snapshot_rows,
        "features": feature_rows,
    }


def latest_feature_payload(db: Session, note: Note) -> dict[str, Any]:
    row = db.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.scope == "note",
            FeatureSnapshot.ref_id == note.id,
            FeatureSnapshot.feature_set == CONTENT_FEATURE_SET,
        )
    )
    if row and isinstance(row.feature_json, dict):
        return row.feature_json
    return build_content_features(note)


def note_peer_engagement(notes: list[Note], exclude_note_id: int | None = None) -> list[float]:
    values: list[float] = []
    for note in notes:
        if exclude_note_id is not None and note.id == exclude_note_id:
            continue
        metrics = extract_note_metric_values(note)
        engagement = metrics["likes"] + metrics["collects"] + metrics["comments"] + metrics["shares"]
        if engagement > 0:
            values.append(float(engagement))
    return values


def median_or_zero(values: list[float]) -> float:
    return float(median(values)) if values else 0.0
