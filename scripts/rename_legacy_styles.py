"""给历史重复的写法改名，让列表能一眼分出「当前该用哪份」。

背景
----
活库 23 份写法里，7/8/11 和 10/12/13 是两组「同一批素材反复蒸」的产物，
指纹完全相同。它们不是逐字重复：

- 7 缺「倾向」段，是早一代产物；8 是 19 条假设实验版；11 规则最接近当前口径。
- 10 与 12 相似度 0.999；13 多 3 条负向约束且是唯一 applied 的那份。

删行会丢对照物、并在 ai_drafts.skill_version 留下悬空标签（草稿 23 → style-7，
草稿 42 → style-13），所以只改名。改名可逆、不碰引用、不动 status。

用法
----
    python scripts/rename_legacy_styles.py            # 预览
    python scripts/rename_legacy_styles.py --apply    # 写库
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(r"G:\XHSStudio\data\data\spider_xhs.db")

# id -> (旧名, 新名)。id 11 / 13 是「当前该用的那份」，13 保持原名。
RENAMES: dict[int, str] = {
    7: "Ego 单作者 · 早期（缺倾向段，历史）",
    8: "Ego 单作者 · 假设实验版（历史）",
    11: "Ego 单作者 · 主版本（147 篇）",
    10: "AI产品阿豪 · 早期（历史）",
    12: "AI产品阿豪 · 检测器修正（与早期近同，历史）",
    4: "配方验证 · 抖音 3 篇（实验）",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"数据库不存在：{db}")
        return 1

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = {
        row["id"]: row
        for row in con.execute(
            f"select id, name, status from style_profiles "
            f"where id in ({','.join(str(i) for i in RENAMES)})"
        )
    }

    missing = sorted(set(RENAMES) - set(rows))
    if missing:
        print(f"缺少 id：{missing}（可能已被改名或删除）")
        return 1

    print(f"数据库：{db}\n")
    for pid, new_name in RENAMES.items():
        row = rows[pid]
        marker = "  " if row["name"] == new_name else "→ "
        print(
            f"  id={pid:<3} status={row['status']:<8} "
            f"{row['name'][:40]!r}"
        )
        if row["name"] != new_name:
            print(f"       {marker}{new_name!r}")

    changes = [
        (new, pid) for pid, new in RENAMES.items() if rows[pid]["name"] != new
    ]
    if not changes:
        print("\n已经都是新名字，无需改动。")
        con.close()
        return 0

    if not args.apply:
        print(f"\ndry-run：{len(changes)} 条待改。确认后加 --apply。")
        con.close()
        return 0

    with con:
        con.executemany(
            "update style_profiles set name = ?, updated_at = datetime('now') "
            "where id = ?",
            changes,
        )
    print(f"\n已改名 {len(changes)} 条。")
    for row in con.execute(
        f"select id, status, name from style_profiles "
        f"where id in ({','.join(str(i) for i in RENAMES)}) order by id"
    ):
        print(f"  id={row['id']:<3} {row['status']:<8} {row['name']}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
