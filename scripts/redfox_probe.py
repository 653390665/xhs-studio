"""Probe the RedFox Xiaohongshu REST provider.

Use this to confirm the live request/response shapes and that the read-only
provider normalizes them correctly. Nothing is written anywhere.

Usage (from the project root, with the project venv):

    set REDFOX_API_KEY=ak_xxx
    python scripts/redfox_probe.py --keyword AI
    python scripts/redfox_probe.py --user 5a73c5fa4eacab4c4ccc9778
    python scripts/redfox_probe.py --note https://www.xiaohongshu.com/explore/xxxx
    python scripts/redfox_probe.py --works 5a73c5fa4eacab4c4ccc9778
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.adapters.xhs.redfox_api_adapter import (  # noqa: E402
    XhsRedfoxApiAdapter,
    redfox_usage_snapshot,
)
from backend.app.core.config import get_settings  # noqa: E402


def _dump(label: str, payload: object) -> None:
    print(f"\n=== {label} ===")
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(text if len(text) <= 4000 else text[:4000] + "\n... (truncated)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the RedFox XHS REST provider")
    parser.add_argument("--keyword", default="", help="run a content search")
    parser.add_argument("--user", default="", help="look up a user profile (userId)")
    parser.add_argument("--note", default="", help="look up a note detail by URL or workId")
    parser.add_argument("--works", default="", help="look up a user's works")
    parser.add_argument("--insights", default="", help="爆款笔记洞察 for a keyword")
    parser.add_argument("--low-fan", default="", help="黑马爆文榜 category (e.g. 综合全部)")
    parser.add_argument("--ranking", default="", choices=["", "daily", "weekly"], help="爆款榜单 period")
    parser.add_argument("--users", default="", help="search accounts by keyword")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.redfox_api_key:
        print("未配置 redfox_api_key / REDFOX_API_KEY，无法探测。", file=sys.stderr)
        return 2

    print(f"RedFox base: {settings.redfox_api_base_url}")
    adapter = XhsRedfoxApiAdapter()
    try:
        if args.keyword:
            success, message, payload = adapter.search_note(args.keyword, page=1)
            print(f"search success={success} message={message}")
            if success:
                from backend.app.api.platforms.xhs.pc import _normalize_search_item

                items = payload["data"]["items"]
                _dump("search normalized[0]", _normalize_search_item(items[0]) if items else {})
        if args.user:
            success, message, payload = adapter.get_user_info(args.user)
            print(f"user success={success} message={message}")
            _dump("user profile", payload)
        if args.note:
            success, message, payload = adapter.get_note_info(args.note)
            print(f"note success={success} message={message}")
            _dump("note detail", payload)
        if args.works:
            success, message, payload = adapter.get_user_notes_page(args.works, "0")
            print(f"works success={success} message={message}")
            if success:
                notes = payload["data"]["notes"]
                _dump("works[0]", notes[0] if notes else {})
        if args.insights:
            success, message, payload = adapter.search_viral_insights(args.insights)
            print(f"insights success={success} message={message}")
            if success:
                data = payload["data"]
                print(f"  items={len(data['items'])} total={data['total']} hot_topics={len(data['hot_topics'])} related={len(data['related_searches'])}")
                _dump("insights item[0]", data["items"][0] if data["items"] else {})
        if args.low_fan:
            success, message, payload = adapter.get_low_fan_ranking(args.low_fan, "")
            print(f"low_fan success={success} message={message}")
            if success:
                items = payload["data"]["items"]
                print(f"  items={len(items)}")
                _dump("low_fan item[0]", items[0] if items else {})
        if args.ranking:
            success, message, payload = adapter.get_ranking(args.ranking, "", "综合全部")
            print(f"ranking({args.ranking}) success={success} message={message}")
            if success:
                items = payload["data"]["items"]
                print(f"  items={len(items)}")
                _dump("ranking item[0]", items[0] if items else {})
        if args.users:
            success, message, payload = adapter.search_users(args.users, page=1)
            print(f"users success={success} message={message}")
            if success:
                items = payload["data"]["items"]
                print(f"  items={len(items)} total={payload['data']['total']}")
                _dump("users[0]", items[0] if items else {})
    finally:
        adapter.close()
        print(f"\n今日 RedFox 用量：{redfox_usage_snapshot()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
