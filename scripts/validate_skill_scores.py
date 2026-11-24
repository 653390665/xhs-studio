"""Batch-score saved notes with the format-aware Skill and run a preliminary validation.

Fit = how well the note matches the account's positioning/style/format.
Craft = format-specific execution; marked unavailable when data is too thin.
Performance is intentionally not computed here; engagement is only used for a
directional correlation check.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.app.core.database import SessionLocal
from backend.app.models import Note, User
from backend.app.services.skill_score_service import score_note_with_skill

OUTPUT_MD = Path("data/skill_validation_report.md")
OUTPUT_JSON = Path("data/skill_validation_report.json")


def rankdata(values: list[float]) -> list[float]:
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


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    return numerator / (denom_x * denom_y) if denom_x and denom_y else 0.0


def spearman(xs: list[float], ys: list[float]) -> float:
    return round(pearson(rankdata(xs), rankdata(ys)), 3)


def main() -> None:
    db = SessionLocal()
    try:
        user = db.get(User, 1)
        notes = db.scalars(
            select(Note).where(Note.user_id == 1, Note.platform == "xhs").order_by(Note.id.desc())
        ).all()
        rows: list[dict[str, Any]] = []
        for note in notes:
            content_chars = len((note.content or "").replace(" ", "").replace("\n", ""))
            engagement = int(note.like_count or 0) + int(note.collect_count or 0) + int(note.comment_count or 0) + int(note.share_count or 0)
            result = score_note_with_skill(db, user, note, account_id=1)
            craft = result.get("craft") or {}
            fit = result.get("fit") or {}
            rows.append(
                {
                    "note_id": note.id,
                    "title": note.title,
                    "author": note.author_name,
                    "content_chars": content_chars,
                    "engagement": engagement,
                    "format": result.get("format"),
                    "format_label": result.get("format_label"),
                    "fit_total": fit.get("total"),
                    "fit_grade": fit.get("grade"),
                    "craft_total": craft.get("total"),
                    "craft_grade": craft.get("grade"),
                    "craft_applicable": bool(craft.get("applicable")),
                    "craft_reason": craft.get("reason", ""),
                    "craft_dimensions": {item["key"]: item["score"] for item in (craft.get("dimensions") or [])},
                }
            )

        with_engagement = [row for row in rows if row["engagement"] > 0]
        craft_rows = [row for row in with_engagement if row["craft_applicable"] and row["craft_total"] is not None]
        fit_values = [row["fit_total"] for row in with_engagement if row["fit_total"] is not None]
        craft_values = [row["craft_total"] for row in craft_rows]
        log_engagements = [math.log1p(row["engagement"]) for row in with_engagement]
        fit_scores = [row["fit_total"] for row in with_engagement if row["fit_total"] is not None]
        fit_corr = spearman(fit_scores, log_engagements[: len(fit_scores)]) if fit_scores else 0.0
        craft_corr = (
            spearman(craft_values, [math.log1p(row["engagement"]) for row in craft_rows])
            if craft_values
            else 0.0
        )

        ordered = sorted(craft_rows, key=lambda row: row["engagement"], reverse=True)
        group_size = max(1, len(ordered) // 4)
        top_group = ordered[:group_size]
        bottom_group = ordered[-group_size:]
        top_fit = round(statistics.mean([row["fit_total"] for row in top_group]), 1) if top_group else 0
        bottom_fit = round(statistics.mean([row["fit_total"] for row in bottom_group]), 1) if bottom_group else 0
        top_craft = round(statistics.mean([row["craft_total"] for row in top_group]), 1) if top_group else 0
        bottom_craft = round(statistics.mean([row["craft_total"] for row in bottom_group]), 1) if bottom_group else 0

        dimension_keys = ["title_hook", "cover", "opening", "structure", "evidence", "cta", "tags"]
        dimension_corr = {}
        for key in dimension_keys:
            values = [row["craft_dimensions"].get(key, 0.0) for row in craft_rows]
            dimension_corr[key] = spearman(values, [math.log1p(row["engagement"]) for row in craft_rows]) if values else 0.0

        report = {
            "total_notes": len(rows),
            "with_engagement": len(with_engagement),
            "craft_scorable": len(craft_rows),
            "excluded_from_craft": len(rows) - len(craft_rows),
            "fit": {
                "mean": round(statistics.mean(fit_values), 1) if fit_values else 0,
                "median": round(statistics.median(fit_values), 1) if fit_values else 0,
                "spearman_vs_log_engagement": fit_corr,
            },
            "craft": {
                "mean": round(statistics.mean(craft_values), 1) if craft_values else 0,
                "median": round(statistics.median(craft_values), 1) if craft_values else 0,
                "spearman_vs_log_engagement": craft_corr,
                "top_group_mean": top_craft,
                "bottom_group_mean": bottom_craft,
            },
            "format_distribution": Counter(row["format_label"] for row in rows).most_common(),
            "dimension_spearman": dimension_corr,
            "top_group_fit": top_fit,
            "bottom_group_fit": bottom_fit,
            "top_10_by_engagement": ordered[:10],
            "bottom_5_by_engagement": ordered[-5:],
            "excluded_examples": [row for row in rows if not row["craft_applicable"]][:10],
        }

        lines = [
            "# Skill 评分批量验证（格式感知版）",
            "",
            f"- 总笔记：{report['total_notes']}",
            f"- 可做 Craft 评分：{report['craft_scorable']}",
            f"- Craft 数据不足：{report['excluded_from_craft']}",
            f"- Fit：均值 {report['fit']['mean']} / 中位 {report['fit']['median']} / 与 log 互动 Spearman **{fit_corr}**",
            f"- Craft：均值 {report['craft']['mean']} / 中位 {report['craft']['median']} / 与 log 互动 Spearman **{craft_corr}**",
            f"- 高互动组：Fit {top_fit} / Craft {top_craft}；低互动组：Fit {bottom_fit} / Craft {bottom_craft}",
            "",
            "## 形式分布",
            "",
            "| 形式 | 数量 |",
            "|---|---:|",
            *[f"| {label} | {count} |" for label, count in report["format_distribution"]],
            "",
            "## Craft 分维度相关性",
            "",
            "| 维度 | Spearman |",
            "|---|---:|",
            *[f"| {key} | {value} |" for key, value in dimension_corr.items()],
            "",
            "## 高互动 Top 10（可 Craft 评分）",
            "",
            "| 标题 | 形式 | 互动 | Fit | Craft | 正文字数 |",
            "|---|---|---:|---:|---:|---:|",
            *[
                f"| {row['title'][:34]} | {row['format_label']} | {row['engagement']} | {row['fit_total']} | {row['craft_total']} | {row['content_chars']} |"
                for row in ordered[:10]
            ],
            "",
            "## 结论",
            "",
            "- Fit 衡量“像不像这个账号”，Craft 衡量“这个形式内做得好不好”，两个分数不合成一个总分。",
            "- 短文案/视频不再用长文结构扣分；正文/标签缺失的笔记标为 Craft 不可用，不强行给低分。",
            "- 跨作者绝对互动仍只用于方向性检查，不是因果验证。",
            "- 要验证 Skill 是否有效，需要自己账号 30+ 篇完整正文 + 发布后 7 天数据，或 A/B 生成实验。",
            "",
            "## 限制",
            "",
            "- 样本按“最多点赞”采集，存在爆款偏差；",
            "- 大量搜索笔记没有正文/标签，Craft 不可用；",
            "- 没有曝光、点击、完播、涨粉数据；",
            "- 跨作者评的是“是否符合我的 Skill”，不是作者内容质量。",
        ]
        OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
        OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "total_notes": report["total_notes"],
                    "craft_scorable": report["craft_scorable"],
                    "fit": report["fit"],
                    "craft": report["craft"],
                    "format_distribution": report["format_distribution"],
                    "dimension_spearman": dimension_corr,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("report:", OUTPUT_MD)
    finally:
        db.close()


if __name__ == "__main__":
    main()
