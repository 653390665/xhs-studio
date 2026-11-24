"""界面上「已经做完的能力」必须真的接上线。

背景（2026-11-14 的审查）：

    后端有 distill_batches 表，写稿页读它，但**没有任何地方写它**；
    后端有 send-to-publish，前端**零调用**，所以发布板块永远是空的；
    后端有 structure-check，接进了 preflight，但新草稿的 template_id
    恒为 null，所以那条检查永远不会触发。

三条都是「验收时手工调 API 能过、用户点鼠标过不去」。单元测试抓不到，
因为每一层单独看都是对的——错的是线没接。

所以这组测试守的是**调用关系**：前端源码里必须出现这些调用。
它们是廉价的结构断言，但能防住「又断一次而没人发现」。
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

def _read_all(pattern: str) -> str:
    if not SRC.is_dir():
        pytest.skip(f"前端源码不在 {SRC}")
    chunks = []
    for path in SRC.rglob(pattern):
        chunks.append(io.open(path, encoding="utf-8", errors="replace").read())
    return "\n".join(chunks)


def _strip_comments(source: str) -> str:
    """去掉 // 行注释和 /* */ 块注释，只留代码。

    为什么需要：删掉一个实现之后，注释里常常还会提到它（"这里原来有一次
    refreshWriterStyle()"）。那种记录是好的，但不该让「已删除」的断言失败。
    """
    import re

    text = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


@pytest.fixture(scope="module")
def frontend() -> str:
    return _read_all("*.ts") + "\n" + _read_all("*.tsx")


# --- 断链 1：提炼产出要写进 distill_batches --------------------------------


def test_frontend_writes_distill_batches(frontend: str):
    """写稿页的「素材」下拉读 distill-batches，就必须有人写它。"""
    assert "distill-batches" in frontend
    # GET 不算：只有出现 POST 才算真的写
    writes = [
        line
        for line in frontend.splitlines()
        if "distill-batches" in line and ('post' in line or 'upsert' in line.lower())
    ]
    assert writes, (
        "前端没有任何地方向 /api/xhs/distill-batches 写入。"
        "写稿页的批次下拉会永远是空的——这正是 2026-11-14 修掉的那条断链。"
    )


def test_batch_sync_module_exists_and_is_used(frontend: str):
    """批次同步要有唯一出口，不能散在各页面各写一份。"""
    assert (SRC / "lib" / "batchSync.ts").is_file(), "缺少 lib/batchSync.ts"
    # 逐个页面确认，而不是在合并文本里数出现次数——
    # 数次数会把「函数定义 + 导出」也算进去，定义在、调用没有也照样通过。
    studio = io.open(SRC / "pages" / "Studio.tsx", encoding="utf-8").read()
    projects = io.open(SRC / "pages" / "Projects.tsx", encoding="utf-8").read()
    assert "pushBatchFromResults" in studio, "工作台保存模板时没有同步批次"
    assert "pushBatchFromSkillMd" in projects, "提炼完成后没有同步批次"


# --- 断链 2：草稿要能送进发布队列 -------------------------------------------


def test_frontend_calls_send_to_publish(frontend: str):
    """后端的 send-to-publish 必须有人调，否则发布板块永远是空的。"""
    assert "send-to-publish" in frontend, (
        "前端没有调用 send-to-publish。用户自检通过之后没有任何按钮能把稿子送出去。"
    )


def test_write_page_has_send_action(frontend: str):
    """写稿页要有「送发布」这个动作，而不只是自检。"""
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    assert "sendToPublish" in write, "写稿页没有引入 sendToPublish"
    assert "送发布" in write, "写稿页没有「送发布」按钮"


# --- 断链 3：结构模板要能选，选了要能存 -------------------------------------


def test_write_page_passes_template_id(frontend: str):
    """写稿页必须能把 templateId 传给 generateNote。"""
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    assert "loadStructureTemplates" in write, "写稿页没有读结构模板列表"
    assert re.search(r"templateId[,:]", write), "写稿页没有把 templateId 传给生成"


def test_generate_note_serializes_template_id(frontend: str):
    """生成请求体里要真的带 template_id。"""
    lib = io.open(SRC / "lib" / "writing.ts", encoding="utf-8").read()
    generate = lib.split("export function generateNote")[1].split("export function")[0]
    assert "template_id" in generate, "generateNote 没有序列化 template_id"


def test_draft_update_accepts_template_id(frontend: str):
    """保存草稿要能写 template_id，否则「换模板」存不下来。"""
    lib = io.open(SRC / "lib" / "writing.ts", encoding="utf-8").read()
    save = lib.split("export function saveDraft")[1].split("export function")[0]
    assert "template_id" in save, "saveDraft 没有把 templateId 映射成 template_id"


# --- 第 4–11 项：界面上的「能用了但不好用」 --------------------------------


def test_no_dead_host_bridge_calls(frontend: str):
    """写稿宿主已退场，不能再有「推给宿主」的调用。

    `refreshWriterMethods` 曾经是 `return null`，于是「同步给写稿」按钮点一次
    必然弹「同步失败：写稿宿主可能没起来」——宿主 2026-11-13 就没了。

    检查前先剥掉注释：删掉实现之后，注释里还会提到这些名字（那是记录
    「为什么删」，不该被当成调用）。
    """
    code = _strip_comments(frontend)
    for name in ("refreshWriterMethods", "refreshWriterStyle", "refreshWriterTemplate"):
        assert name not in code, f"{name} 是给已退场宿主用的，不该还在前端"


def test_topic_page_passes_topic_to_writer(frontend: str):
    """选题的「用它写」要把主题带过去，不能回到空白输入框。"""
    plan = io.open(SRC / "pages" / "Plan.tsx", encoding="utf-8").read()
    assert "/write?topic=" in plan, "选题页没有把标题带进写稿页"


def test_write_page_reads_topic_query(frontend: str):
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    assert "useSearchParams" in write, "写稿页没有读 URL 上的 topic"
    assert 'searchParams.get("topic")' in write


def test_write_page_shows_generation_context(frontend: str):
    """context 存了 9 个字段，至少要有一条能看见「这篇是用什么写的」。"""
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    assert "draft.context" in write or "draft.context ??" in write, (
        "写稿页没有读 context"
    )
    assert "这篇是用什么写的" in write


def test_write_page_supports_review_status(frontend: str):
    """草稿要能标采用/弃用，否则列表里 41 篇 pending 没有区分度。"""
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    lib = io.open(SRC / "lib" / "writing.ts", encoding="utf-8").read()
    assert "reviewDraft" in lib, "writing.ts 没有 reviewDraft"
    assert "reviewDraft" in write, "写稿页没有调用 reviewDraft"
    assert "采用" in write and "弃用" in write


def test_overview_steps_follow_progress(frontend: str):
    """今日三步要读真实的写法/批次/草稿数量，不能一直是新手引导。"""
    ov = io.open(SRC / "pages" / "Overview.tsx", encoding="utf-8").read()
    assert "loadStyleProfiles" in ov, "今日页没有读写法数量"
    assert "distill-batches" in ov, "今日页没有读批次数量"
    assert "hasStyle" in ov and "hasDraft" in ov
    assert "is-done" in ov


def test_overview_embeds_positioning_guide(frontend: str):
    """账号定位的引导要在今日里直接走完，不能只给一个「去设置」的跳转。

    定位是每天开工前该想一下的事；把人推去设置页面对六个空输入框，
    正是「太死板」的来源。
    """
    ov = io.open(SRC / "pages" / "Overview.tsx", encoding="utf-8").read()
    assert "PositioningGuide" in ov, "今日页没有内嵌定位引导"
    assert "现在开始" in ov, "今日页没有直接开始引导的按钮"
    assert "重新定一次" in ov, "定位已有内容时也要能重新引导"
    # 仍然保留手动改的出口，但不能是唯一出口
    assert "/settings/positioning" in ov


def test_studio_draft_box_is_renamed(frontend: str):
    """工作台的「草稿箱」存的是模板，不是 /write 的草稿，不能同名。"""
    studio = io.open(SRC / "pages" / "Studio.tsx", encoding="utf-8").read()
    assert "模板草稿" in studio, "工作台没有把草稿箱改名成模板草稿"


def test_skill_picker_shows_description(frontend: str):
    """Skill 勾选要能判断该不该勾，只给名字等于抽签。"""
    write = io.open(SRC / "pages" / "Write.tsx", encoding="utf-8").read()
    assert "skill.description" in write, "Skill 勾选列表没有显示简介"
    assert "skill.triggers" in write, "Skill 勾选列表没有显示触发词"


def test_positioning_has_draft_action(frontend: str):
    """定位页六个空框要有「从笔记里猜一版」。"""
    panel = io.open(
        SRC / "components" / "PositioningPanel.tsx", encoding="utf-8"
    ).read()
    lib = io.open(SRC / "lib" / "positioning.ts", encoding="utf-8").read()
    assert "draftPositioning" in lib, "positioning.ts 没有 draftPositioning"
    assert "draftPositioning" in panel, "定位页没有调用起草"
    assert "从笔记里猜" in panel
