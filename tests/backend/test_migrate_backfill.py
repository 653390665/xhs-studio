"""回填脚本的守护测试。

`migrate_backfill.py` 修的是「第一版迁移漏掉/写坏了」的东西。它有两个
容易重犯的错，所以单独钉住：

  1. **按自增 id 搬引用**。老库 note.id=12 和活库 note.id=12 不是同一篇
     （中间跳过了 61 篇），直接搬 `source_note_ids` / `note_db_id` /
     `ref_id` 会让引用全部错位，而且「id 存在」所以查不出来。
     必须按 `note_id` 字符串重建映射。

  2. **话题全量建标签**。正文里能抠出 1125 个不同话题，其中 835 个只出现
     一次（一次性活动名、作者自造词）。全建成标签，筛选条里排一千多个
     胶囊，比空着更糟。
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO))

from scripts.migrate_backfill import MIN_TAG_COUNT, extract_tags  # noqa: E402


def test_extract_tags_handles_both_hashtag_shapes():
    """小红书的 `#话题[话题]#` 和裸 `#话题#` 都要认。"""
    text = "今天聊#宁波[话题]# 和 #超级个体# 两个方向"
    assert extract_tags(text) == ["宁波", "超级个体"]


def test_extract_tags_ignores_douyin_style():
    """抖音的 `#话题` 没有闭合井号，不能按这个规则切——会误吞整句。"""
    text = "#情感 #原生家庭 你反复爱上的类型"
    assert extract_tags(text) == []


def test_extract_tags_dedupes_case_insensitively():
    text = "#AI工具[话题]# #ai工具[话题]# #AI工具[话题]#"
    assert extract_tags(text) == ["AI工具"]


def test_extract_tags_skips_overlong():
    """超过 30 字的多半是误匹配（整段文字里夹了井号）。"""
    long_name = "很" * 40
    assert extract_tags(f"#{long_name}[话题]# #正常[话题]#") == ["正常"]


def test_min_tag_count_is_sane():
    """阈值不能是 1（会产生上千个一次性标签），也不能太高（覆盖不到）。"""
    assert 2 <= MIN_TAG_COUNT <= 10, (
        f"MIN_TAG_COUNT={MIN_TAG_COUNT}：1 会产生 1125 个标签，"
        "超过 10 会丢掉一半有话题的笔记"
    )


def test_backfill_maps_by_note_id_not_autoincrement():
    """引用必须按 note_id 重建，不能直接搬自增 id。"""
    script = io.open(REPO / "scripts" / "migrate_backfill.py", encoding="utf-8").read()
    assert "id_map[old.id] = new.id" in script, "没有建立 old.id → new.id 映射"
    assert "live_by_note_id.get(old.note_id" in script, (
        "映射不是按 note_id 字符串建立的——按自增 id 搬会让引用全部错位"
    )


def test_backfill_is_idempotent_by_business_key():
    """重跑不能翻倍：每个块都要先查已有。"""
    script = io.open(REPO / "scripts" / "migrate_backfill.py", encoding="utf-8").read()
    for marker in (
        "existing_asset_keys",
        "existing_metric",
        "existing_members",
        "existing_analysis",
        "existing_topics",
    ):
        assert marker in script, f"缺少幂等判断：{marker}"


def test_backfill_does_not_invent_published_at():
    """解析不出来就留空，不能默认成今天。

    默认成今天会让「近 7 天」筛选把所有未知日期的笔记都算进来，
    低粉爆款榜瞬间被灌满。
    """
    script = io.open(REPO / "scripts" / "migrate_backfill.py", encoding="utf-8").read()
    block = script.split("published_at 全 NULL")[1].split("# I1：")[0]
    assert "if parsed is not None" in block, (
        "解析失败时必须跳过，不能落一个默认时间"
    )
