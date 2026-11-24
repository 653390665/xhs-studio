"""给历史 style_profiles 补证据蒸馏的输入指纹。

`save_profile` 现在会自己算指纹并原地更新，但库里已有的 23 份里
21 份是证据蒸馏（`engine="evidence"`），它们没有 `input_fingerprint`，
所以「对同一份语料再蒸一次」认不出旧的那份。

这里按 (corpus_set_id, hypothesis_set, corpus_label) 算指纹补上，
不改名字、不改内容、不改 status。
"""
import hashlib
import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB = r"G:\XHSStudio\data\data\spider_xhs.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def evidence_fingerprint(meta):
    parts = (
        str(meta.get("corpus_set_id") or ""),
        str(meta.get("hypothesis_set") or ""),
        str(meta.get("corpus_label") or ""),
    )
    if not parts[0] and not parts[2]:
        return ""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


rows = con.execute(
    "select id, name, source, engine, account_id, profile_json from style_profiles order by id"
).fetchall()

updated = 0
no_data = 0
groups = {}
for row in rows:
    meta = json.loads(row["profile_json"] or "{}")
    if meta.get("input_fingerprint"):
        continue
    fp = ""
    if row["engine"] == "evidence" or row["source"] == "evidence_distill":
        fp = evidence_fingerprint(meta)
    if not fp:
        no_data += 1
        continue
    meta["input_fingerprint"] = fp
    if "distill_revision" not in meta:
        meta["distill_revision"] = 1
    con.execute(
        "update style_profiles set profile_json=? where id=?",
        (json.dumps(meta, ensure_ascii=False), row["id"]),
    )
    updated += 1
    key = (fp, row["account_id"])
    groups.setdefault(key, []).append((row["id"], row["name"][:34]))
    print(f"  补 id={row['id']:<3} fp={fp} account={row['account_id']} {row['name'][:30]}")

con.commit()
print()
print(f"补充: {updated} 份 | 无法计算: {no_data} 份")
print()
print("重复组（同语料 + 同假设 + 同账号，多份）：")
dups = {k: v for k, v in groups.items() if len(v) > 1}
if not dups:
    print("  无")
for (fp, account), items in dups.items():
    print(f"  fp={fp} account={account}")
    for id_, name in items:
        print(f"     id={id_} {name}")

print()
print("总量:", con.execute("select count(*) from style_profiles").fetchone()[0])
con.close()
