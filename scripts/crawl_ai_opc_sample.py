"""Conservative AI/OPC sample crawl for the local XHS workspace.

Usage:
    python scripts/crawl_ai_opc_sample.py --username 测试1 --password jmds6130
    python scripts/crawl_ai_opc_sample.py --keywords AI工具,AI副业 --pages 1 --dry-run

Safety defaults:
  - one page per keyword
  - no author-profile enrichment (fewer XHS requests)
  - no comments
  - random 6-10s delay between searches
  - stop immediately on 401/429/5xx
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_KEYWORDS = ["AI工具", "AI副业", "一人公司", "OPC", "独立开发"]
TITLE_PATTERNS = {
    "数字型": r"\d",
    "疑问型": r"[？?]|怎么|如何|为什么|什么",
    "教程型": r"教程|手把手|保姆级|步骤|方法|攻略",
    "列表型": r"合集|盘点|推荐|必备|top|榜",
    "对比型": r"vs|对比|区别|差异|还是",
    "故事型": r"我|亲身|经历|踩坑|分享|心得",
    "反转型": r"竟然|居然|没想到|原来|以为",
    "身份型": r"打工人|普通人|新手|小白|宝妈|学生党|独立开发|一人公司",
}
CTA_PATTERNS = {
    "关注引导": r"关注|点个关注|记得关注",
    "收藏引导": r"收藏|先收藏|码住|mark",
    "点赞引导": r"点赞|双击|给个赞",
    "评论引导": r"评论|留言|告诉我|你们觉得|欢迎讨论",
    "转发引导": r"转发|分享给",
    "私信引导": r"私信|私我|后台回复|滴滴",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl a small AI/OPC sample")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="测试1")
    parser.add_argument("--password", default="jmds6130")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--sort", type=int, default=2, help="0=综合, 2=最多点赞")
    parser.add_argument("--sleep-min", type=float, default=6.0)
    parser.add_argument("--sleep-max", type=float, default=10.0)
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-prefix", default="data/ai_opc_sample")
    return parser.parse_args()


def engagement(item: dict[str, Any]) -> int:
    return sum(int(item.get(key) or 0) for key in ("likes", "collects", "comments", "shares"))


def quantile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(p * (len(ordered) - 1))))
    return float(ordered[index])


def tags_of(item: dict[str, Any]) -> list[str]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    tags: list[str] = []
    for key in ("tags", "tag_list", "tagList"):
        value = raw.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    tags.append(entry.lstrip("#").strip())
                elif isinstance(entry, dict) and entry.get("name"):
                    tags.append(str(entry["name"]).lstrip("#").strip())
    content = str(item.get("content") or "")
    import re

    tags.extend(re.findall(r"#([^#\s]{1,30})", content))
    return [tag for tag in tags if tag]


def build_report(items: list[dict[str, Any]], keywords: list[str]) -> tuple[str, dict[str, Any]]:
    import re

    unique = {str(item.get("note_id")): item for item in items if item.get("note_id")}
    rows = list(unique.values())
    rows.sort(key=engagement, reverse=True)
    values = [engagement(item) for item in rows]
    nonzero = [value for value in values if value > 0]
    p50 = quantile(nonzero, 0.50)
    p75 = quantile(nonzero, 0.75)
    p80 = quantile(nonzero, 0.80)
    p90 = quantile(nonzero, 0.90)
    p99 = quantile(nonzero, 0.99)
    top = [item for item in rows if engagement(item) >= p80] if p80 else rows[: max(1, len(rows) // 5)]

    def pattern_counts(source: list[dict[str, Any]]) -> Counter:
        counter: Counter = Counter()
        for item in source:
            title = str(item.get("title") or "")
            content = str(item.get("content") or "")
            for name, pattern in TITLE_PATTERNS.items():
                if re.search(pattern, title, re.I):
                    counter[name] += 1
            for name, pattern in CTA_PATTERNS.items():
                if re.search(pattern, content, re.I):
                    counter[name] += 1
        return counter

    all_patterns = pattern_counts(rows)
    top_patterns = pattern_counts(top)
    tag_counter: Counter = Counter()
    for item in rows:
        tag_counter.update(tags_of(item))
    author_counter: Counter = Counter(str(item.get("author_name") or "未知") for item in rows)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "keywords": keywords,
        "total": len(rows),
        "unique_authors": len(author_counter),
        "engagement": {
            "median": p50,
            "p75": p75,
            "p80": p80,
            "p90": p90,
            "p99": p99,
            "max": max(values) if values else 0,
        },
        "top_authors": author_counter.most_common(10),
        "top_tags": tag_counter.most_common(15),
        "title_patterns_all": all_patterns.most_common(),
        "title_patterns_top": top_patterns.most_common(),
        "top_notes": [
            {
                "note_id": item.get("note_id"),
                "title": item.get("title"),
                "author": item.get("author_name"),
                "likes": item.get("likes", 0),
                "collects": item.get("collects", 0),
                "comments": item.get("comments", 0),
                "shares": item.get("shares", 0),
                "engagement": engagement(item),
                "note_url": item.get("note_url", ""),
            }
            for item in rows[:20]
        ],
    }

    lines = [
        "# AI / OPC 小红书样本报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 关键词：{', '.join(keywords)}",
        f"- 样本量：{report['total']} 条",
        f"- 作者数：{report['unique_authors']}",
        "",
        "## 互动分布",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 中位数 | {p50:,.0f} |",
        f"| P75 | {p75:,.0f} |",
        f"| P80（爆款候选线） | {p80:,.0f} |",
        f"| P90 | {p90:,.0f} |",
        f"| P99 | {p99:,.0f} |",
        f"| 最高 | {max(values) if values else 0:,} |",
        "",
        "## Top 20 笔记",
        "",
        "| # | 标题 | 作者 | 赞 | 藏 | 评 | 总互动 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(report["top_notes"], 1):
        lines.append(
            f"| {index} | {str(item['title'])[:42]} | {item['author']} | "
            f"{item['likes']} | {item['collects']} | {item['comments']} | {item['engagement']} |"
        )

    lines += [
        "",
        "## 标题 / CTA 模式",
        "",
        "| 模式 | 全样本命中 | Top20% 命中 |",
        "|---|---:|---:|",
    ]
    for name in list(TITLE_PATTERNS) + list(CTA_PATTERNS):
        lines.append(
            f"| {name} | {all_patterns.get(name, 0)} | {top_patterns.get(name, 0)} |"
        )

    lines += [
        "",
        "## 高频标签",
        "",
        "、".join(f"#{tag}（{count}）" for tag, count in report["top_tags"]) or "暂无",
        "",
        "## 使用建议",
        "",
        "- 这批样本适合做“内容模式”和“相对阈值”的第一版，不足以做严谨的统计校准。",
        "- 爆款候选线先参考 P80；等样本到 300+ 后再用 P90/P95。",
        "- 同作者基线仍需要每个作者 3 篇以上笔记，不能跨作者平均。",
        "- 下一步：从 Top 20 里挑 10 个作者，每个补 5 篇，做同作者飞轮。",
    ]
    return "\n".join(lines) + "\n", report


def main() -> None:
    args = parse_args()
    keywords = [keyword.strip() for keyword in args.keywords.split(",") if keyword.strip()]
    client = httpx.Client(timeout=90)
    base = args.base_url.rstrip("/")

    login = client.post(f"{base}/api/auth/login", json={"username": args.username, "password": args.password})
    if login.status_code != 200:
        raise SystemExit(f"login failed: {login.status_code} {login.text[:200]}")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    accounts_payload = client.get(f"{base}/api/accounts", headers=headers).json()
    accounts = accounts_payload.get("items") if isinstance(accounts_payload, dict) else accounts_payload
    pc = next((account for account in accounts if account.get("sub_type") == "pc"), None)
    if not pc:
        raise SystemExit("no PC account found")

    collected: list[dict[str, Any]] = []
    request_count = 0
    for keyword in keywords:
        for page in range(1, max(1, args.pages) + 1):
            if request_count >= args.max_requests:
                print(f"reached max requests ({args.max_requests}); stop")
                break
            request_count += 1
            print(f"[{request_count}] search {keyword!r} page {page} ...")
            response = client.post(
                f"{base}/api/xhs/pc/search/notes",
                headers=headers,
                json={
                    "account_id": pc["id"],
                    "keyword": keyword,
                    "page": page,
                    "sort_type_choice": args.sort,
                    "note_type": 0,
                    "note_time": 0,
                    "note_range": 0,
                    "pos_distance": 0,
                    "geo": "",
                    "enrich_authors": False,
                    "max_profiles": 1,
                    "max_fans": 0,
                    "min_likes": 0,
                    "min_like_fan_ratio": 0,
                    "sort_by": "default",
                },
            )
            if response.status_code in {401, 429} or response.status_code >= 500:
                print(f"stop on HTTP {response.status_code}: {response.text[:300]}")
                break
            if response.status_code != 200:
                print(f"skip HTTP {response.status_code}: {response.text[:200]}")
                continue
            items = response.json().get("items") or []
            print(f"  -> {len(items)} notes")
            collected.extend(items)
            if not args.dry_run and items:
                payload = {
                    "account_id": pc["id"],
                    "fetch_comments": False,
                    "notes": [
                        {
                            "note_id": str(item.get("note_id") or ""),
                            "note_url": item.get("note_url", ""),
                            "title": item.get("title", ""),
                            "content": item.get("content", ""),
                            "author_name": item.get("author_name", ""),
                            "author_id": item.get("author_id", ""),
                            "author_fans": int(item.get("author_fans") or 0),
                            "likes": int(item.get("likes") or 0),
                            "collects": int(item.get("collects") or 0),
                            "comments": int(item.get("comments") or 0),
                            "shares": int(item.get("shares") or 0),
                            "raw": item.get("raw") or {},
                        }
                        for item in items
                        if item.get("note_id")
                    ],
                }
                saved = client.post(f"{base}/api/notes/batch-save", headers=headers, json=payload)
                print(f"  -> save {saved.status_code}")
            if request_count < args.max_requests:
                delay = random.uniform(args.sleep_min, args.sleep_max)
                print(f"  sleep {delay:.1f}s")
                time.sleep(delay)

    unique = {str(item.get("note_id")): item for item in collected if item.get("note_id")}
    print(f"collected {len(collected)} rows / {len(unique)} unique")
    if args.dry_run:
        return

    backfill = client.post(f"{base}/api/xhs/analytics/backfill", headers=headers)
    print(f"backfill {backfill.status_code}: {backfill.text[:200]}")

    report, payload = build_report(list(unique.values()), keywords)
    output = Path(args.output_prefix)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".md").write_text(report, encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"report: {output.with_suffix('.md')}")
    print(f"json:   {output.with_suffix('.json')}")


if __name__ == "__main__":
    main()
