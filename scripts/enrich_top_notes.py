"""Fetch full note details for the Top N AI/OPC samples and update the library.

Only N detail requests; no comments, no author enrichment, no media downloads.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="测试1")
    parser.add_argument("--password", default="jmds6130")
    parser.add_argument("--input", default="data/ai_opc_sample.json")
    parser.add_argument("--output", default="data/ai_opc_top_details.json")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--sleep-min", type=float, default=10.0)
    parser.add_argument("--sleep-max", type=float, default=14.0)
    return parser.parse_args()


def note_payload(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw") or {}
    return {
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
        "raw": raw if isinstance(raw, dict) else {},
    }


def main() -> None:
    args = parse_args()
    sample = json.loads(Path(args.input).read_text(encoding="utf-8"))
    top_notes = sample.get("top_notes") or []
    if not top_notes:
        raise SystemExit("no top_notes in input; run crawl_ai_opc_sample.py first")

    client = httpx.Client(timeout=120)
    base = args.base_url.rstrip("/")
    login = client.post(f"{base}/api/auth/login", json={"username": args.username, "password": args.password})
    if login.status_code != 200:
        raise SystemExit(f"login failed: {login.status_code} {login.text[:200]}")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    accounts = client.get(f"{base}/api/accounts", headers=headers).json()["items"]
    pc = next(account for account in accounts if account.get("sub_type") == "pc")

    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(top_notes[: max(1, args.top)], 1):
        url = item.get("note_url") or ""
        if not url:
            print(f"[{index}] skip: no url")
            continue
        print(f"[{index}] detail {str(item.get('title'))[:40]!r}")
        response = client.post(
            f"{base}/api/xhs/pc/notes/detail",
            headers=headers,
            json={"account_id": pc["id"], "url": url},
        )
        if response.status_code in {401, 429} or response.status_code >= 500:
            print(f"  stop on HTTP {response.status_code}: {response.text[:300]}")
            break
        if response.status_code != 200:
            print(f"  skip HTTP {response.status_code}: {response.text[:200]}")
            continue
        detail = response.json()
        merged = {
            **item,
            **detail,
            "note_url": detail.get("note_url") or url,
            "likes": detail.get("likes") or item.get("likes") or 0,
            "collects": detail.get("collects") or item.get("collects") or 0,
            "comments": detail.get("comments") or item.get("comments") or 0,
            "shares": detail.get("shares") or item.get("shares") or 0,
        }
        enriched.append(merged)
        saved = client.post(
            f"{base}/api/notes/batch-save",
            headers=headers,
            json={"account_id": pc["id"], "fetch_comments": False, "notes": [note_payload(merged)]},
        )
        print(
            f"  -> content {len(str(merged.get('content') or ''))} chars, "
            f"tags {len(merged.get('tags') or [])}, save {saved.status_code}"
        )
        if index < args.top:
            delay = random.uniform(args.sleep_min, args.sleep_max)
            print(f"  sleep {delay:.1f}s")
            time.sleep(delay)

    Path(args.output).write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved {len(enriched)} details -> {args.output}")


if __name__ == "__main__":
    main()
