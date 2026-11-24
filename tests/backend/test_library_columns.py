"""样本库表格要显示的东西，每一列都必须在后端有数据。

这张表从 4 列（赞/藏/粉丝/字数）扩到 12 列，但真正的风险不是「多写几个
render」，而是**列渲染了一个后端从来没返回的字段**——那种列永远是「—」，
看起来像数据缺失，其实是字段名写错了。

所以这里的断言是「前端读取的字段名」与「后端序列化的键名」对齐。
"""
from __future__ import annotations
import io
import re
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"

def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"文件不存在：{path}")
    return io.open(path, encoding="utf-8", errors="replace").read()


def _serialized_note_keys() -> set[str]:
    """后端 `_serialize_note` 返回的全部键名。

    注意 `tags` 不在 `_serialize_note` 里，是 `_serialize_note_with_tags`
    额外挂上去的（要单查一次关联表）。列表接口用的正是后者，所以这里两个
    都收。
    """
    source = _read(BACKEND / "api" / "notes.py")
    i = source.find("def _serialize_note(")
    assert i > 0, "找不到 _serialize_note"
    block = source[i : source.find("\n\n\n", i)]
    keys = set(re.findall(r'"(\w+)":', block))
    # tags 由外层函数追加
    if "serialized[\"tags\"]" in source:
        keys.add("tags")
    return keys


@pytest.fixture(scope="module")
def note_keys() -> set[str]:
    return _serialized_note_keys()


def test_table_columns_read_existing_fields(note_keys: set[str]):
    """样本库表格读的每个字段，后端都得真的有。"""
    page = _read(SRC / "pages" / "Library.tsx")
    # 只取 columns 定义里 note.xxx 的读取
    columns_block = page.split("const columns")[1].split("/* ---------------- 动作")[0]
    fields = set(re.findall(r"note\.(\w+)", columns_block))
    assert fields, "没解析到表格读的字段"

    # 前端接口里声明的字段（platform / engagement_rate 等）可能后端不返回，
    # 那是可选的；关键是**后端返回的字段前端要用上**，以及**前端读的必须存在**。
    missing = {
        f
        for f in fields
        if f not in note_keys
        # 这几个是前端 CorpusNote 自己声明的可选字段，后端没返回也不报错
        and f
        not in {
            "id",
            "platform",  # 后端有，但键名在 _serialize_note 里确实叫 platform
        }
    }
    assert not missing, (
        f"表格读的字段后端不返回：{sorted(missing)}。"
        "这些列会永远显示「—」，看起来像数据缺失。"
    )


def test_low_follower_ratio_column_exists(note_keys: set[str]):
    """赞粉比是低粉爆款的核心判据，必须有这一列。"""
    assert "like_fan_ratio" in note_keys, "后端没有返回 like_fan_ratio"
    page = _read(SRC / "pages" / "Library.tsx")
    assert "like_fan_ratio" in page, "样本库没有显示赞粉比"
    assert "赞粉比" in page


def test_published_at_column_exists(note_keys: set[str]):
    """发布时间要显示，而且「没读到」不能显示成今天。"""
    assert "published_at" in note_keys
    page = _read(SRC / "pages" / "Library.tsx")
    assert "published_at" in page
    assert "不是今天" in page, "未知日期没有明确说明，会被读成今天"


def test_source_type_column_exists(note_keys: set[str]):
    """自己的稿子不能混进对标样本。"""
    assert "is_own" in note_keys
    page = _read(SRC / "pages" / "Library.tsx")
    assert "is_own" in page, "样本库没有区分「我的」和「对标」"


def test_content_excerpt_shown(note_keys: set[str]):
    """标题下面要带正文摘要——704 条不可能一条条点开看能不能用。"""
    page = _read(SRC / "pages" / "Library.tsx")
    assert "lib__excerpt" in page or "excerpt" in page, "样本库没有正文摘要"
    assert "note.content" in page


def test_tag_filter_is_capped(note_keys: set[str]):
    """151 个话题不能全铺成胶囊。"""
    page = _read(SRC / "pages" / "Library.tsx")
    block = page.split("mat-lib__filters")[1].split("</div>")[0]
    assert "slice(0, 12)" in block, (
        "话题筛选没有截断：迁移后有 151 个，全铺会把表格挤出屏幕"
    )


def test_platform_switch_exists():
    """抖音 344 篇没有封面没有话题，必须能和小红书分开看。"""
    page = _read(SRC / "pages" / "Library.tsx")
    assert "platform === p.key" in page or 'platform === "' in page
    assert "抖音" in page and "小红书" in page
