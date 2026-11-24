"""回填 notes.published_at：raw_json 里有发布时间，列上却还是 NULL。

背景
----
`published_at` 是「最近发布」「低粉爆款」这类筛选的锚点。抖音转写稿的
payload 把时间放在顶层 `published_at`（日期字符串），但历史代码只认
`published` / `time` / `workPublishTime`，所以这批稿子在列上全是 NULL。
读取路径已经补上（`note_metrics_service.extract_note_metrics`、
`api/notes.py`、`scripts/migrate_backfill.py`）；这个脚本只负责把**已经
在库里的历史行**补回来。

口径
----
只填 NULL，绝不覆盖已有时间；raw 里没有可解析时间的行保持 NULL。
默认 dry-run，加 `--apply` 才写库。

用法
----
    python scripts/backfill_published_at.py
    python scripts/backfill_published_at.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.note_metrics_service import extract_note_metrics  # noqa: E402

DEFAULT_DB = Path(r"G:\XHSStudio\data\data\spider_xhs.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只预览")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    if not db.is_file():
        print(f"数据库不存在：{db}")
        return 1

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    before = con.execute(
        "select count(*) from notes where published_at is not null"
    ).fetchone()[0]
    total = con.execute("select count(*) from notes").fetchone()[0]

    rows = con.execute(
        "select id, platform, source_type, raw_json from notes "
        "where published_at is null order by id"
    ).fetchall()

    updates: list[tuple[str, int]] = []
    by_source: Counter[tuple[str, str]] = Counter()
    examples: list[tuple[int, str, str, str]] = []

    for row in rows:
        raw = row["raw_json"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = {}
        metrics = extract_note_metrics(raw)
        parsed = metrics.get("published_at")
        if parsed is None:
            continue
        value = parsed.isoformat(sep=" ")
        updates.append((value, int(row["id"])))
        by_source[(row["platform"] or "", row["source_type"] or "")] += 1
        if len(examples) < 5:
            examples.append(
                (
                    int(row["id"]),
                    row["platform"] or "",
                    row["source_type"] or "",
                    value,
                )
            )

    print(f"数据库：{db}")
    print(f"总笔记：{total}；回填前 published_at 非空：{before}")
    print(f"NULL 行：{len(rows)}；可回填：{len(updates)}；仍无法解析：{len(rows) - len(updates)}")
    for (platform, source), count in by_source.most_common():
        print(f"  {platform or '-'} / {source or '-'}: {count}")
    if examples:
        print("样例：")
        for note_id, platform, source, value in examples:
            print(f"  id={note_id} {platform}/{source} -> {value}")

    if not args.apply:
        print("\ndry-run：没有写库。确认后加 --apply。")
        con.close()
        return 0

    if not updates:
        print("\n没有可回填的行。")
        con.close()
        return 0

    with con:
        con.executemany(
            "update notes set published_at = ? where id = ? and published_at is null",
            updates,
        )

    after = con.execute(
        "select count(*) from notes where published_at is not null"
    ).fetchone()[0]
    print(f"\n已写库：{len(updates)} 条；published_at 非空：{before} -> {after}")
    print(f"剩余 NULL：{total - after}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
