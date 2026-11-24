from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Note, User
from backend.app.services.analytics_snapshot_service import build_content_features
from backend.app.services.skill_score_service import score_note_with_skill

DEFAULT_WEIGHTS = {
    "title_hook": ("标题钩子", 20.0),
    "cover": ("封面", 10.0),
    "opening": ("开头", 15.0),
    "structure": ("结构", 20.0),
    "evidence": ("具体证据", 15.0),
    "cta": ("CTA", 10.0),
    "tags": ("标签", 10.0),
}
NAME_TO_KEY = {name: key for key, (name, _) in DEFAULT_WEIGHTS.items()}


def _rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return numerator / (dx * dy) if dx and dy else 0.0


def _spearman(xs: list[float], ys: list[float]) -> float:
    return round(_pearson(_rankdata(xs), _rankdata(ys)), 3)


def _parse_weights(skill) -> dict[str, float]:
    weights = {key: value for key, (_, value) in DEFAULT_WEIGHTS.items()}
    for line in (skill.content_md or "").splitlines():
        match = re.match(r"\|\s*([^|]+?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|", line)
        if not match:
            continue
        key = NAME_TO_KEY.get(match.group(1).strip())
        if key:
            weights[key] = float(match.group(2))
    if sum(weights.values()) <= 0:
        return {key: value for key, (_, value) in DEFAULT_WEIGHTS.items()}
    return weights


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values()) or 1.0
    normalized = {key: max(5.0, min(35.0, round(value / total * 100, 1))) for key, value in weights.items()}
    diff = round(100.0 - sum(normalized.values()), 1)
    if diff:
        key = max(normalized, key=normalized.get)
        normalized[key] = round(normalized[key] + diff, 1)
    return normalized


def _current_multipliers(skill) -> dict[str, float]:
    """Effective weight multipliers of the current Skill.

    Prefers multipliers stored by a previous evolution. Falls back to parsing
    the long-form rubric table so manually tuned Skills are respected.
    """
    base = {key: value for key, (_, value) in DEFAULT_WEIGHTS.items()}
    stored = (skill.structured_json or {}).get("weight_multipliers")
    if isinstance(stored, dict):
        multipliers: dict[str, float] = {}
        for key in base:
            try:
                value = float(stored.get(key, 1.0))
            except (TypeError, ValueError):
                value = 1.0
            multipliers[key] = max(0.6, min(1.8, value))
        return multipliers
    parsed = _parse_weights(skill)
    return {
        key: round(max(0.6, min(1.8, parsed.get(key, base[key]) / base[key])), 3)
        if base[key]
        else 1.0
        for key in base
    }


def _weights_from_multipliers(multipliers: dict[str, float]) -> dict[str, float]:
    raw = {
        key: default * multipliers.get(key, 1.0)
        for key, (_, default) in DEFAULT_WEIGHTS.items()
    }
    return _normalize(raw)


def _next_version(version: str) -> str:
    match = re.search(r"v(\d+)\.(\d+)", version or "")
    if not match:
        return "v0.2-draft"
    return f"v{match.group(1)}.{int(match.group(2)) + 1}-draft"


def _next_version_for(db: Session, user: User, skill) -> str:
    """Next version label for a style profile being forked by evolution."""
    from backend.app.models import StyleProfile

    base = getattr(skill, "version", "") or "v0.1"
    rows = db.scalars(
        select(StyleProfile.name).where(StyleProfile.user_id == user.id)
    ).all()
    # 用「名字 + 序号」避免版本号撞车
    stem = str(getattr(skill, "name", "风格")).strip() or "风格"
    count = sum(1 for name in rows if name and name.startswith(stem))
    return f"{stem}·进化{count + 1}"

def propose_skill_evolution(
    db: Session,
    user: User,
    skill=None,
    *,
    account_id: int | None = None,
):
    """Analyze saved notes and fork the active style with calibrated weights.

    Returns ``(profile, report)``. The new profile is *not* auto-activated: the
    user reviews it in 风格库 and applies it deliberately.
    """
    if skill is None:
        from backend.app.services.account_context_service import active_creation_skill

        skill = active_creation_skill(db, user, account_id)
        if skill is None:
            raise ValueError("该账号还没有生效的写作风格，无法进化。")

    # Own notes only. Filtering on ``platform_account_id`` used to include the 104
    # crawled competitor notes, so ``len(scorable_account) >= 10`` was always true
    # and the report claimed 样本来自当前账号的笔记 while mixing in strangers' posts.
    from backend.app.services.note_ownership import is_own_note

    notes = db.scalars(
        select(Note).where(Note.user_id == user.id, Note.platform == "xhs")
    ).all()
    account_notes = [
        note
        for note in notes
        if is_own_note(note) and (account_id is None or note.platform_account_id == account_id)
    ]
    scorable_account = []
    for note in account_notes:
        result = score_note_with_skill(db, user, note, account_id=account_id)
        if result.get("craft", {}).get("applicable"):
            scorable_account.append(note)
    if len(scorable_account) >= 10:
        scope = "account"
        selected = scorable_account
    else:
        scope = "library"
        selected = []
        for note in notes:
            result = score_note_with_skill(db, user, note, account_id=account_id)
            if result.get("craft", {}).get("applicable"):
                selected.append(note)

    rows: list[dict[str, Any]] = []
    for note in selected:
        result = score_note_with_skill(db, user, note, account_id=account_id)
        craft = result.get("craft") or {}
        if not craft.get("applicable") or craft.get("total") is None:
            continue
        engagement = int(note.like_count or 0) + int(note.collect_count or 0) + int(note.comment_count or 0) + int(note.share_count or 0)
        if engagement <= 0:
            continue
        features = build_content_features(note)
        rows.append(
            {
                "note_id": note.id,
                "engagement": engagement,
                "format": result.get("format_label") or "",
                "craft": craft,
                "features": features,
            }
        )

    if len(rows) < 3:
        raise ValueError("可评分笔记太少（少于 3 条），先补全正文/标签后再进化。")

    next_version = _next_version_for(db, user, skill)
    baseline = statistics.median([row["engagement"] for row in rows])
    for row in rows:
        row["relative"] = row["engagement"] / baseline if baseline else 0.0

    dimension_pairs: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        for dimension in row["craft"].get("dimensions") or []:
            key = dimension.get("key")
            maximum = float(dimension.get("max") or 0)
            if not key or maximum <= 0:
                continue
            ratio = float(dimension.get("score") or 0) / maximum
            dimension_pairs.setdefault(key, []).append((ratio, row["relative"]))

    correlations: dict[str, float | None] = {}
    for key in DEFAULT_WEIGHTS:
        pairs = dimension_pairs.get(key) or []
        correlations[key] = _spearman([x for x, _ in pairs], [y for _, y in pairs]) if len(pairs) >= 8 else None

    weights_before = _weights_from_multipliers(_current_multipliers(skill))
    multipliers_before = _current_multipliers(skill)
    multipliers_after = dict(multipliers_before)
    changes: list[str] = []
    if len(rows) >= 10:
        for key, correlation in correlations.items():
            if correlation is None:
                continue
            name = DEFAULT_WEIGHTS[key][0]
            if correlation >= 0.15:
                multipliers_after[key] = min(1.8, round(multipliers_after[key] * 1.15, 3))
                changes.append(f"{name} 与相对表现正相关（{correlation:+.2f}），权重上调")
            elif correlation <= -0.15:
                multipliers_after[key] = max(0.6, round(multipliers_after[key] * 0.85, 3))
                changes.append(f"{name} 与相对表现负相关（{correlation:+.2f}），权重下调")
        weights_after = _weights_from_multipliers(multipliers_after)
    else:
        weights_after = dict(weights_before)

    format_counter = Counter(row["format"] for row in rows)
    title_counter: Counter = Counter()
    cta_counter: Counter = Counter()
    for row in rows:
        if row["relative"] < 1:
            continue
        title_counter.update(row["features"].get("title_patterns") or [])
        cta_counter.update(row["features"].get("cta_types") or [])

    confidence = "low" if len(rows) < 15 else "medium" if len(rows) < 30 else "high"
    report = {
        "scope": scope,
        "sample_size": len(rows),
        "baseline_engagement": round(baseline, 1),
        "confidence": confidence,
        "format_distribution": format_counter.most_common(),
        "dimension_correlation": correlations,
        "weights_before": weights_before,
        "weights_after": weights_after,
        "weight_multipliers_before": multipliers_before,
        "weight_multipliers_after": multipliers_after,
        "changes": changes,
        "top_title_patterns": title_counter.most_common(8),
        "top_cta_patterns": cta_counter.most_common(6),
        "note": (
            "样本来自当前账号的笔记。" if scope == "account"
            else "当前账号可评分笔记不足 10 条，已改用内容库样本；结论只作方向参考。"
        ),
    }

    updated_md = skill.content_md or ""
    for key, (name, _) in DEFAULT_WEIGHTS.items():
        new_weight = weights_after.get(key)
        if new_weight is None:
            continue
        updated_md = re.sub(
            rf"(\|\s*{re.escape(name)}\s*\|\s*)\d+(?:\.\d+)?(\s*\|)",
            rf"\g<1>{new_weight:g}\g<2>",
            updated_md,
        )
    section = [
        "",
        f"## 数据进化记录（{next_version}）",
        "",
        f"- 样本范围：{report['note']}",
        f"- 可评分样本：{len(rows)} 条；基线中位互动：{baseline:.0f}",
        f"- 置信度：{confidence}",
        "- 维度相关性：" + "、".join(
            f"{DEFAULT_WEIGHTS[key][0]} {value:+.2f}" for key, value in correlations.items() if value is not None
        ),
        "- 权重变化：" + ("；".join(changes) if changes else "样本不足或相关性不明显，本次不改权重。"),
        "- 权重系数（应用到各形式的 rubric）："
        + "、".join(f"{DEFAULT_WEIGHTS[key][0]} ×{value:g}" for key, value in multipliers_after.items()),
        "- 说明：上面的评分标准表是长文基准的展示值，实际评分按各形式的 rubric × 权重系数计算（含封面）。",
        "- 高表现标题模式：" + ("、".join(f"{name}({count})" for name, count in title_counter.most_common(5)) or "暂无"),
        "- 注意：这是数据建议，不是因果结论；确认后再设为当前。",
    ]
    updated_md = updated_md.rstrip() + "\n" + "\n".join(section) + "\n"

    from backend.app.models import StyleProfile

    new_profile = StyleProfile(
        user_id=user.id,
        account_id=getattr(skill, "account_id", account_id),
        name=next_version,
        status="ready",
        source="data_evolution",
        works_count=len(rows),
        char_count=len(updated_md),
        engine="evolved",
        profile_json={
            "evolution_report": report,
            "weight_multipliers": multipliers_after,
            "parent_style_id": getattr(skill, "id", None),
            "analysis": {},
            "stats": {},
        },
        skill_md=updated_md,
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
    return new_profile, report
