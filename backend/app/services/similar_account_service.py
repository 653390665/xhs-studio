"""Rank candidate accounts into 同阶对标 (peer) and 高阶标杆 (benchmark)."""

from __future__ import annotations

from typing import Any

PEER_RATIO = (0.5, 2.0)
BENCHMARK_RATIO = (3.0, 8.0)


def _aggregate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_author: dict[str, dict[str, Any]] = {}
    for item in items:
        author_id = str(item.get("author_id") or "").strip()
        if not author_id:
            continue
        entry = by_author.setdefault(
            author_id,
            {
                "user_id": author_id,
                "nickname": str(item.get("author_name") or ""),
                "avatar": str(item.get("author_avatar") or ""),
                "fans": int(item.get("author_fans") or 0),
                "notes": 0,
                "total_engagement": 0,
                "sample_title": "",
                "sample_url": "",
            },
        )
        if not entry["fans"]:
            entry["fans"] = int(item.get("author_fans") or 0)
        entry["notes"] += 1
        engagement = int(item.get("likes") or 0) + int(item.get("collects") or 0) + int(item.get("comments") or 0)
        entry["total_engagement"] += engagement
        if not entry["sample_title"]:
            entry["sample_title"] = str(item.get("title") or "")
            entry["sample_url"] = str(item.get("note_url") or "")
    return list(by_author.values())


def rank_accounts(
    items: list[dict[str, Any]],
    *,
    seed_fans: int = 0,
    limit: int = 8,
) -> dict[str, Any]:
    """Split candidate authors into peer / benchmark groups.

    ``seed_fans`` is the user's own follower count; without it we fall back to
    the median follower count of the candidates.
    """
    accounts = _aggregate(items)
    if not accounts:
        return {"peer": [], "benchmark": [], "seed_fans": seed_fans, "candidates": 0}

    known_fans = sorted(account["fans"] for account in accounts if account["fans"] > 0)
    base_fans = seed_fans or (known_fans[len(known_fans) // 2] if known_fans else 0)

    for account in accounts:
        avg_engagement = account["total_engagement"] / max(account["notes"], 1)
        account["avg_engagement"] = round(avg_engagement, 1)
        account["engagement_per_fan"] = round(avg_engagement / max(account["fans"], 1), 2) if account["fans"] else 0
        if base_fans and account["fans"]:
            ratio = account["fans"] / base_fans
            account["fans_ratio"] = round(ratio, 2)
            # closer to the seed is better; heavy accounts are "benchmarks"
            proximity = 1 - min(abs(ratio - 1), 1)
            account["score"] = round(
                0.55 * proximity
                + 0.30 * min(account["engagement_per_fan"], 3) / 3
                + 0.15 * min(account["notes"], 5) / 5,
                4,
            )
        else:
            account["fans_ratio"] = 0
            account["score"] = round(0.6 * min(account["notes"], 5) / 5 + 0.4 * min(account["engagement_per_fan"], 3) / 3, 4)

    peer = [
        account
        for account in accounts
        if account["fans_ratio"] and PEER_RATIO[0] <= account["fans_ratio"] <= PEER_RATIO[1]
    ]
    benchmark = [
        account
        for account in accounts
        if account["fans_ratio"] and BENCHMARK_RATIO[0] <= account["fans_ratio"] <= BENCHMARK_RATIO[1]
    ]

    peer.sort(key=lambda row: (row["score"], row["avg_engagement"]), reverse=True)
    benchmark.sort(key=lambda row: (row["score"], row["fans"]), reverse=True)

    def reason(account: dict[str, Any], kind: str) -> str:
        if not account["fans_ratio"]:
            return f"同关键词下 {account['notes']} 篇笔记，平均互动 {int(account['avg_engagement'])}"
        if kind == "peer":
            return (
                f"粉丝量约为你的 {account['fans_ratio']} 倍，平均互动 {int(account['avg_engagement'])}，"
                "可以直接参考玩法"
            )
        return (
            f"粉丝量约为你的 {account['fans_ratio']} 倍，平均互动 {int(account['avg_engagement'])}，"
            "模式成熟可对标"
        )

    for account in peer:
        account["reason"] = reason(account, "peer")
    for account in benchmark:
        account["reason"] = reason(account, "benchmark")

    return {
        "seed_fans": base_fans,
        "candidates": len(accounts),
        "peer": peer[:limit],
        "benchmark": benchmark[:limit],
    }


__all__ = ["rank_accounts"]
