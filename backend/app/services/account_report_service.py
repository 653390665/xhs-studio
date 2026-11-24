from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.services.diagnosis_service import account_diagnosis_raw


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _as_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.lower().endswith("w"):
        multiplier = 10000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def normalize_timestamp(value: Any) -> int:
    """Return a Unix timestamp in seconds, accepting ms strings/numbers."""
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return 0
    if timestamp > 10**12:
        timestamp //= 1000
    if timestamp < 10**9:
        return 0
    return timestamp


def note_publish_time(note: dict[str, Any]) -> datetime | None:
    timestamp = normalize_timestamp(note.get("timestamp"))
    return datetime.fromtimestamp(timestamp, tz=SHANGHAI) if timestamp else None


def _note_engagement(note: dict[str, Any]) -> int:
    return sum(
        _as_int(note.get(key))
        for key in ("likes", "collects", "comments", "shares")
    )


def _serialize_report_note(note: dict[str, Any]) -> dict[str, Any]:
    published = note_publish_time(note)
    return {
        "note_id": str(note.get("note_id") or ""),
        "title": str(note.get("title") or ""),
        "note_url": str(note.get("note_url") or ""),
        "likes": _as_int(note.get("likes")),
        "collects": _as_int(note.get("collects")),
        "comments": _as_int(note.get("comments")),
        "shares": _as_int(note.get("shares")),
        "engagement": _note_engagement(note),
        "publish_time": published.isoformat() if published else "",
    }


def _clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _dimension(key: str, name: str, score: float, advice: str) -> dict[str, Any]:
    return {"key": key, "name": name, "score": _clamp_score(score), "advice": advice}


def _build_scorecard(
    profile: dict[str, Any],
    notes: list[dict[str, Any]],
    *,
    fans: int,
    post_count: int,
    avg_engagement: float,
    total_engagement: int,
) -> dict[str, Any]:
    """Seven-dimension account diagnosis (100 points)."""
    desc = str(profile.get("desc") or "").strip()
    nickname = str(profile.get("nickname") or "").strip()
    dimensions: list[dict[str, Any]] = []

    positioning = 40
    if desc:
        positioning += 20
    if len(desc) >= 30:
        positioning += 20
    if 2 <= len(nickname) <= 12:
        positioning += 10
    dimensions.append(
        _dimension("positioning", "定位", positioning, "补全简介（我是谁 + 提供什么 + 适合谁）" if positioning < 70 else "定位描述清晰")
    )

    if fans >= 10000:
        fan_score, fan_advice = 90, "粉丝体量健康"
    elif fans >= 1000:
        fan_score, fan_advice = 70, "已过冷启动，继续保持更新"
    elif fans >= 100:
        fan_score, fan_advice = 50, "粉丝基数偏小，先做垂直内容"
    else:
        fan_score, fan_advice = 30, "粉丝很少，优先做好账号定位与首图"
    if fans and total_engagement / max(fans, 1) >= 0.5:
        fan_score += 10
        fan_advice += "；互动/粉丝比优秀"
    dimensions.append(_dimension("fans", "粉丝", fan_score, fan_advice))

    if post_count >= 20:
        topic_score, topic_advice = 85, "更新稳定"
    elif post_count >= 10:
        topic_score, topic_advice = 70, "更新频率不错"
    elif post_count >= 5:
        topic_score, topic_advice = 55, "建议每周至少 3 篇"
    else:
        topic_score, topic_advice = 35, "样本太少，先积累 10 篇以上再评估选题"
    titles = [str(note.get("title") or "") for note in notes if note.get("title")]
    if titles:
        prefixes = {title[:6] for title in titles}
        if len(prefixes) == len(titles):
            topic_score += 10
            topic_advice += "；选题不重复"
    dimensions.append(_dimension("topics", "选题", topic_score, topic_advice))

    with_cover = sum(
        1 for note in notes if note.get("cover") or note.get("cover_url") or note.get("image_urls")
    )
    cover_ratio = with_cover / max(post_count, 1)
    if cover_ratio >= 0.9:
        cover_score, cover_advice = 85, "封面齐全"
    elif cover_ratio >= 0.6:
        cover_score, cover_advice = 65, "部分笔记缺封面信息"
    else:
        cover_score, cover_advice = 40, "补齐封面，封面决定点击率"
    dimensions.append(_dimension("covers", "封面", cover_score, cover_advice))

    max_engagement = max((_note_engagement(note) for note in notes), default=0)
    if max_engagement >= 1000:
        hit_score, hit_advice = 85, f"有爆文（最高互动 {max_engagement}）"
    elif max_engagement >= 300:
        hit_score, hit_advice = 65, f"有潜力笔记（最高互动 {max_engagement}）"
    elif max_engagement >= 100:
        hit_score, hit_advice = 50, "还没有明显爆文，继续测试选题"
    else:
        hit_score, hit_advice = 30, "互动偏低，优先改标题和封面"
    if avg_engagement and max_engagement >= avg_engagement * 2:
        hit_score += 10
        hit_advice += "；存在明显跑赢均值的笔记"
    dimensions.append(_dimension("hits", "爆文", hit_score, hit_advice))

    if avg_engagement >= 500:
        engagement_score, engagement_advice = 85, "篇均互动优秀"
    elif avg_engagement >= 100:
        engagement_score, engagement_advice = 65, "篇均互动中等"
    elif avg_engagement >= 30:
        engagement_score, engagement_advice = 50, "篇均互动偏低"
    else:
        engagement_score, engagement_advice = 30, "篇均互动很低，先优化开头与封面"
    likes = sum(_as_int(note.get("likes")) for note in notes)
    collects = sum(_as_int(note.get("collects")) for note in notes)
    if likes and collects / likes >= 0.5:
        engagement_score += 10
        engagement_advice += "；收藏率高，内容有保存价值"
    dimensions.append(_dimension("engagement", "互动", engagement_score, engagement_advice))

    latest = max(
        (note_publish_time(note) for note in notes if note_publish_time(note)),
        default=None,
    )
    if latest is None:
        output_score, output_advice = 40, "无法判断发布时间"
    else:
        days = (datetime.now(SHANGHAI) - latest).days
        if days <= 7:
            output_score, output_advice = 85, f"最近 {days} 天内有更新"
        elif days <= 30:
            output_score, output_advice = 65, f"最近一次更新在 {days} 天前"
        else:
            output_score, output_advice = 40, f"已 {days} 天未更新，建议恢复节奏"
    dimensions.append(_dimension("output", "产出", output_score, output_advice))

    total = _clamp_score(sum(item["score"] for item in dimensions) / len(dimensions))
    grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 55 else "C"
    weakest = sorted(dimensions, key=lambda item: item["score"])[:2]
    return {
        "total": total,
        "grade": grade,
        "dimensions": dimensions,
        "suggestions": [f"{item['name']}：{item['advice']}" for item in weakest],
    }


def build_account_report(
    profile: dict[str, Any],
    notes: list[dict[str, Any]],
    month: str | None = None,
) -> dict[str, Any]:
    """Summarize posting activity and engagement for one account."""
    selected: list[dict[str, Any]] = []
    for note in notes:
        published = note_publish_time(note)
        if month:
            if published is None or published.strftime("%Y-%m") != month:
                continue
        selected.append(note)

    selected.sort(key=_note_engagement, reverse=True)
    fans = _as_int(profile.get("fans"))
    likes = sum(_as_int(note.get("likes")) for note in selected)
    collects = sum(_as_int(note.get("collects")) for note in selected)
    comments = sum(_as_int(note.get("comments")) for note in selected)
    shares = sum(_as_int(note.get("shares")) for note in selected)
    total_engagement = likes + collects + comments + shares
    post_count = len(selected)
    avg_engagement = round(total_engagement / post_count, 1) if post_count else 0
    avg_likes = round(likes / post_count, 1) if post_count else 0

    month_counter: Counter[str] = Counter()
    for note in selected:
        published = note_publish_time(note)
        if published:
            month_counter[published.strftime("%Y-%m")] += 1

    top_notes = [_serialize_report_note(note) for note in selected[:5]]
    latest_note = max(
        (note for note in selected if note_publish_time(note)),
        key=lambda note: normalize_timestamp(note.get("timestamp")),
        default=None,
    )
    latest_time = note_publish_time(latest_note) if latest_note else None

    summary = (
        f"共 {post_count} 篇，互动 {total_engagement}，篇均 {avg_engagement}；"
        f"粉丝 {fans}，整体互动/粉丝 {round(total_engagement / max(fans, 1), 2)}。"
    )
    if top_notes:
        summary += f" 最高互动笔记《{top_notes[0]['title'] or top_notes[0]['note_id']}》{top_notes[0]['engagement']}。"

    return {
        "user_id": str(profile.get("user_id") or ""),
        "nickname": str(profile.get("nickname") or ""),
        "fans": fans,
        "follows": _as_int(profile.get("follows")),
        "total_notes": post_count,
        "total_engagement": total_engagement,
        "avg_engagement": avg_engagement,
        "avg_likes": avg_likes,
        "total_likes": likes,
        "total_collects": collects,
        "total_comments": comments,
        "total_shares": shares,
        "engagement_rate": round(total_engagement / max(fans, 1), 4) if fans else 0,
        "posting_months": [
            {"month": month_key, "count": count}
            for month_key, count in sorted(month_counter.items(), reverse=True)
        ],
        "latest_publish_time": latest_time.isoformat() if latest_time else "",
        "top_notes": top_notes,
        "summary": summary,
        "diagnosis_raw": account_diagnosis_raw(profile, selected),
        "scorecard": _build_scorecard(
            profile,
            selected,
            fans=fans,
            post_count=post_count,
            avg_engagement=avg_engagement,
            total_engagement=total_engagement,
        ),
    }
