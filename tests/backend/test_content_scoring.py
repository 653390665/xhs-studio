"""Content scoring + similar-account ranking (pure rules, no model calls)."""

from __future__ import annotations

from backend.app.services.content_scoring_service import score_note, score_title
from backend.app.services.similar_account_service import rank_accounts


def test_title_score_has_six_dimensions():
    result = score_title("3 个方法，普通人也能做出爆款笔记", "这里讲三个可执行的方法。")

    assert len(result["dimensions"]) == 6
    assert 0 <= result["score"] <= 100
    assert result["grade"] in {"S", "A", "B", "C"}


def test_title_score_prefers_concrete_hook():
    strong = score_title("打工人别再踩坑｜3 个方法，30 分钟做出爆款笔记", "打工人做笔记的三个方法。")
    weak = score_title("随便写写", "")

    assert strong["score"] > weak["score"] + 20
    assert strong["grade"] in {"S", "A"}
    assert weak["grade"] in {"B", "C"}


def test_title_score_penalises_banned_words():
    clean = score_title("3 个方法，普通人也能做出爆款笔记", "方法正文")
    risky = score_title("3 个方法，普通人也能做出爆款笔记，绝对最好", "方法正文")

    risk_dim = next(item for item in risky["dimensions"] if item["key"] == "risk")
    assert risk_dim["score"] < 20
    assert risky["score"] < clean["score"]


def test_note_score_has_six_dimensions():
    body = (
        "打工人早上时间紧，我用 3 个方法解决了早餐问题。\n\n"
        "1. 隔夜燕麦：前一晚 5 分钟装好\n"
        "2. 鸡蛋三明治：3 分钟搞定\n"
        "3. 豆浆粉冲泡：1 分钟\n\n"
        "你更想先试哪一个？评论区告诉我。\n#早餐 #打工人 #通勤"
    )
    result = score_note("打工人早餐｜3 个 5 分钟方案", body)

    assert len(result["dimensions"]) == 6
    assert result["score"] >= 60
    assert result["char_count"] > 50
    assert result["grade"] in {"S", "A", "B"}


def test_note_score_flags_missing_structure_and_cta():
    result = score_note("标题", "一段没有结构也没有互动引导的正文")

    keys = {item["key"]: item["score"] for item in result["dimensions"]}
    assert keys["structure"] <= 9
    assert keys["cta"] <= 8
    assert result["suggestions"]


def test_rank_accounts_splits_peer_and_benchmark():
    items = [
        {"author_id": "a", "author_name": "同阶", "author_fans": 8000, "likes": 300, "collects": 100, "comments": 20, "title": "A"},
        {"author_id": "a", "author_name": "同阶", "author_fans": 8000, "likes": 200, "collects": 50, "comments": 10, "title": "A2"},
        {"author_id": "b", "author_name": "高阶", "author_fans": 40000, "likes": 900, "collects": 300, "comments": 60, "title": "B"},
        {"author_id": "c", "author_name": "太头部", "author_fans": 900000, "likes": 9999, "collects": 1, "comments": 1, "title": "C"},
    ]

    result = rank_accounts(items, seed_fans=10000, limit=5)

    assert result["seed_fans"] == 10000
    assert [item["user_id"] for item in result["peer"]] == ["a"]
    assert [item["user_id"] for item in result["benchmark"]] == ["b"]
    assert result["peer"][0]["notes"] == 2
    assert result["peer"][0]["reason"]


def test_rank_accounts_handles_empty_input():
    result = rank_accounts([], seed_fans=1000)

    assert result["peer"] == []
    assert result["benchmark"] == []
    assert result["candidates"] == 0


def test_note_score_includes_skill_alignment_checks():
    body = (
        "上周我在公司楼下便利店买早餐，排队时发现一个现象：越赶时间的人越容易买错。\n"
        "我连续记了 5 天，最赶的那天反而多花了 8 块钱。\n"
        "所以我现在只做一件事：前一天晚上把早餐固定成两套，早上不用选。\n"
        "你会怎么安排早上的 5 分钟？"
    )
    result = score_note("5 分钟早餐：我连续记了 5 天", body, ["早餐", "通勤", "效率"])
    checks = {item["key"]: item for item in result["skill_alignment"]}
    assert set(checks) == {"opening_5s", "single_mechanism", "real_detail", "humanize", "compliance"}
    assert checks["real_detail"]["status"] == "pass"
    assert checks["opening_5s"]["status"] in {"pass", "warn"}

    abstract = score_note(
        "在这个时代如何提升效率",
        "首先，我们要认知升级；其次，要形成闭环；最后，要找到底层逻辑。\n"
        "总而言之，赋能自己，形成复利。",
        ["效率"],
    )
    abstract_checks = {item["key"]: item for item in abstract["skill_alignment"]}
    assert abstract_checks["humanize"]["status"] == "warn"
