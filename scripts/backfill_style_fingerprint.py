"""给现有 style_profiles 补 input_fingerprint。

新建的 profile 会自动带指纹，但库里已有的 23 份没有，因此「对同一批素材
再蒸一次」认不出旧的那份，还是会新建。

这一步只补指纹，不改名字、不改内容、不改 status——纯粹让去重逻辑对历史
数据也生效。
"""
import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB = r"G:\XHSStudio\data\data\spider_xhs.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    "select id, source, account_id, profile_json, works_count from style_profiles order by id"
).fetchall()

import hashlib


def fingerprint(note_ids):
    normalized = ",".join(str(int(v)) for v in sorted(set(note_ids)))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


updated = 0
skipped = 0
groups = {}
for row in rows:
    meta = json.loads(row["profile_json"] or "{}")
    note_ids = meta.get("note_ids") or []
    if not note_ids:
        skipped += 1
        print(f"  跳过 id={row['id']:<3} {row['source']:<16} （没有 note_ids："
              f"{'证据蒸馏' if row['source']=='evidence_distill' else row['source']}）")
        continue
    fp = fingerprint(note_ids)
    meta["input_fingerprint"] = fp
    if "distill_revision" not in meta:
        meta["distill_revision"] = 1
    con.execute(
        "update style_profiles set profile_json=? where id=?",
        (json.dumps(meta, ensure_ascii=False), row["id"]),
    )
    updated += 1
    groups.setdefault((fp, row["account_id"]), []).append(row["id"])
    print(f"  补 id={row['id']:<3} fp={fp} notes={len(note_ids)} account={row['account_id']}")

con.commit()
print()
print(f"补充指纹: {updated} 份，跳过: {skipped} 份")
print()
print("重复组（同一批素材 + 同一账号，有多份）：")
dups = {k: v for k, v in groups.items() if len(v) > 1}
if not dups:
    print("  无")
for (fp, account), ids in dups.items():
    print(f"  fp={fp} account={account} -> ids {ids}")

print()
print("补完之后库里的总量:", con.execute("select count(*) from style_profiles").fetchone()[0])
con.close()
