"""第一批修复（蒸馏确定性 / 去重 / 样本库默认视图）的契约测试。

三件事，对应三条真实反馈：

1. 「工作台蒸馏，同一批素材多次蒸馏出不同方案」
   → `/api/ai/polish-text` 以前没有 temperature / seed，`_complete` 默认 0.7。

2. 「写法和能力也是同样问题」
   → `distill_profile_from_notes` 只 `db.add()`；活库 23 份里有重复批次。

3. 「封面问题，内容缺失，数据维度缺失」
   → 第一页全是 `douyin_extract`（转写稿，本来就没有图/互动）；
     「补采粉丝数」把抖音 344 篇也算进缺口，数字永远不下降。
"""
from __future__ import annotations
import io
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"

def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"文件不存在：{path}")
    return io.open(path, encoding="utf-8", errors="replace").read()


# ---------------------------------------------------------------- 样本库视图


def test_library_defaults_to_xhs():
    """默认必须落在有封面有互动的那一类。

    `/api/notes` 按 created_at desc 排，`douyin_extract` 时间最新，永远占满
    第一页——于是打开样本库看到 20 条全空，第一反应是「数据丢了」。
    """
    page = _read(SRC / "pages" / "Library.tsx")
    start = page.find('useKeptState<"all" | "xhs" | "douyin">')
    assert start > 0
    # 只取到 `);` 为止，别把后面 scoped 里的 `platform === "all"` 也吃进来
    block = page[start : page.find(");", start) + 2]
    assert '"materials|lib-platform"' in block
    after_key = block.split('"materials|lib-platform"', 1)[1]
    assert '"xhs"' in after_key, "默认仍然是「全部」，第一页会全是转写稿"
    assert '"all"' not in after_key, "默认不能再是全部"


def test_library_explains_douyin_gap():
    """切到抖音时要说清「不是没读到，是来源本来就没有」。"""
    page = _read(SRC / "pages" / "Library.tsx")
    assert 'platform === "douyin"' in page
    assert "导入语料" in page
    assert "口播转写" in page
    assert "本来就没有" in page


def test_fans_backfill_only_counts_xhs():
    """「缺 N 篇」必须是可补的数量。

    以前用全库算：抖音 344 篇永远补不上（没有适配器、也没有 author_id），
    于是点了补采、数字还是 537。
    """
    page = _read(SRC / "pages" / "Library.tsx")
    start = page.find("const backfillable = useMemo(")
    assert start > 0, "没有单独算可补集合"
    block = page[start : start + 300]
    assert 'n.platform === "xhs"' in block

    # backfill() 只能提交 xhs 的 id
    fn = page.find("async function backfill()")
    fn_block = page[fn : fn + 900]
    assert 'n.platform === "xhs"' in fn_block


def test_douyin_tag_filter_is_hidden():
    """抖音没有话题，话题筛选条不该出现在那一档。"""
    page = _read(SRC / "pages" / "Library.tsx")
    assert '{tags.length > 0 && platform !== "douyin" ? (' in page
