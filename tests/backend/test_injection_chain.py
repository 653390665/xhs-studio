"""注入链：配置在库里、界面能改，生成时到底有没有真的进去。

诊断 I5–I9 是同一类问题——**「配了但没生效」**。这类 bug 特别难发现，因为
界面看起来完全正常：Skill 显示「已启用」，模板显示「已精炼」，账号有写法。
只有把提示词拆开数一遍，才知道某一段根本没进上下文。

这里钉的不是「函数能跑」，而是四个具体的失效形态：

1. `instruction[:4000]` 一刀切，排在最后的 topic Skill 一个字都进不去；
2. flat 模板点过「AI 精炼」后 `return guide` 短路，原始字段全丢；
3. persona / benchmark / schedule 三个模块没有任何调用方；
4. 三个页面三个「待发布」口径，其中两个还是错的。
"""
from __future__ import annotations
import io
import re
from pathlib import Path

import pytest

from backend.app.services.ai_service import (  # noqa: E402
    INSTRUCTION_BUDGET,
    _fit_budget,
    _template_style_block,
)

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"文件不存在：{path}")
    return io.open(path, encoding="utf-8", errors="replace").read()


# ---------------------------------------------------------------- I7 预算


def test_instruction_budget_covers_measured_max():
    """实测最大拼装 11809 字（定位 236 + 写法 7792 + topic 3781）必须放得下。

    预算低于这个数，排最后的 topic Skill 就会被截——而它正是标题公式的来源。
    """
    assert INSTRUCTION_BUDGET >= 11_809


def test_fit_budget_keeps_everything_under_budget():
    text = "定" * 236 + "写" * 7792 + "选" * 3781
    out = _fit_budget(text, INSTRUCTION_BUDGET)
    assert out == text
    assert "已省略" not in out


def test_fit_budget_says_what_was_dropped():
    """超预算不能静默截断：用户看不到「被砍了」只会怀疑配置没生效。"""
    text = "甲" * (INSTRUCTION_BUDGET + 500)
    out = _fit_budget(text, INSTRUCTION_BUDGET)
    assert "已省略" in out
    assert "500" in out
    # 保留部分不能超过预算太多（说明文字本身有几十字）
    assert len(out) < INSTRUCTION_BUDGET + 200


def test_titles_and_tags_use_budget_not_hard_slice():
    """`instruction[:4000]` 不能再出现（注释里提到可以）。"""
    source = _read(BACKEND / "services" / "ai_service.py")
    code = "\n".join(
        line
        for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    assert "instruction[:4000]" not in code
    assert code.count("_fit_budget(instruction, INSTRUCTION_BUDGET)") == 2, (
        "generate_titles 和 generate_tags 都要走预算"
    )


# ---------------------------------------------------------------- I6 flat 模板


FLAT = {
    "kind": "flat",
    "name": "AI 赛道 · 工具型",
    "ai_guide": "标题带数字，中段三步，结尾求收藏。",
    "title_formulas": ["数字 + 结果", "身份 + 反差"],
    "structure": ["开头：痛点（40%）", "中段：操作步骤（83%）", "结尾：收藏引导（78%）"],
    "cta_examples": ["先收藏，用的时候翻出来"],
    "keywords": ["效率", "工具", "模板"],
}


def test_flat_template_keeps_fields_after_refine():
    """精炼过（有 ai_guide）的 flat 模板不能只剩 guide。

    实测模板 1：payload 4974 字，修复前注入 205 字（4%）——比没精炼的更薄。
    """
    block = _template_style_block(FLAT)
    assert "标题带数字" in block, "精炼规范丢了"
    assert "数字 + 结果" in block, "标题公式被短路"
    assert "操作步骤" in block, "内容要点被短路"
    assert "先收藏" in block, "CTA 被短路"
    assert "效率" in block, "关键词被短路"


def test_flat_template_without_guide_still_renders_fields():
    payload = dict(FLAT)
    payload.pop("ai_guide")
    block = _template_style_block(payload)
    assert "数字 + 结果" in block
    assert "操作步骤" in block


def test_positional_template_keeps_guide_as_supplement():
    payload = {
        "kind": "positional",
        "name": "结构模板",
        "opening": [{"label": "失败场景", "count": 12, "pct": 67}],
        "body": [{"label": "操作步骤", "count": 15, "pct": 83}],
        "closing": [{"label": "求赞/收藏/关注", "count": 14, "pct": 78}],
        "skeletons": [{"label": "失败场景 → 操作步骤 → 求赞/收藏/关注", "count": 11, "pct": 61}],
        "structure": ["开头：失败场景（67%）", "中段：操作步骤（83%）", "结尾：求赞/收藏/关注（78%）"],
        "ai_guide": "骨架不变，只把百分比翻成可执行的句子。",
    }
    block = _template_style_block(payload)
    assert "失败场景" in block
    assert "骨架不变" in block


# ---------------------------------------------------------------- I8 未接线 Skill


def test_persona_skill_reaches_generation():
    """persona 两篇（账号档案 / 变现倒推定位）合计 7308 字，以前没有调用方。"""
    source = _read(BACKEND / "api" / "ai.py")
    assert "def _persona_skill_prompt(" in source
    # 三条生成路径都要拼上：写稿、对话、改写
    assert source.count("_persona_skill_prompt(") >= 4, (
        "定义 1 处 + generate_note / draft_chat / rewrite_note 各 1 处"
    )
    for func in ("generate_note", "draft_chat", "rewrite_note"):
        start = source.find(f"def {func}(")
        assert start > 0, f"找不到 {func}"
        block = source[start : start + 6000]
        assert "_persona_skill_prompt(" in block, f"{func} 没有拼 persona Skill"
        # 拼了变量但没用上是最常见的半成品
        assert "persona_text" in block, f"{func} 拼了 persona 但没用进 instruction"


def test_persona_prompt_is_empty_without_account():
    """没有账号就必须返回空串：定位缺失时宁可不注入，也不能借用别人的。"""
    source = _read(BACKEND / "api" / "ai.py")
    start = source.find("def _persona_skill_prompt(")
    block = source[start : start + 2000]
    assert "if not account_id:" in block
    assert 'return ""' in block


def test_benchmark_skill_reaches_analysis():
    source = _read(BACKEND / "services" / "agent_service.py")
    start = source.find("def _analyze_benchmark(")
    assert start > 0
    block = source[start : source.find("\ndef ", start + 10)]
    assert 'module_skill_text(' in block and '"benchmark"' in block, (
        "低粉爆款拆解 Skill 没有任何调用方"
    )
    assert '"method"' in block, "读出来了但没放进返回值，模型看不到"


def test_schedule_skill_reaches_planning():
    source = _read(BACKEND / "services" / "agent_service.py")
    start = source.find("def _plan_schedule(")
    assert start > 0
    block = source[start : source.find("\ndef ", start + 10)]
    assert '"schedule"' in block, "排期与复盘 Skill 没有任何调用方"
    assert '"method"' in block


def test_all_six_modules_have_a_caller():
    """Skill 库六个模块，每个都得有生成/执行路径，否则勾选是假的。"""
    haystack = "\n".join(
        _read(BACKEND / part)
        for part in (
            "api/ai.py",
            "api/matrix.py",
            "api/notes.py",
            "services/agent_service.py",
            "services/scheduler_service.py",
            "services/topic_bank_service.py",
        )
    )
    missing = [
        module
        for module in ("persona", "benchmark", "draft", "topic", "schedule", "visual")
        if f'"{module}"' not in haystack
    ]
    assert not missing, f"这些模块没有任何调用方：{missing}"


def test_title_task_records_how_much_was_injected():
    """任务详情要能回答「我勾的 Skill 到底注入了多少字」。

    只记 `instruction[:4000]` 是历史上最典型的静默截断；事后无从查证。
    现在任务 payload 里留两个长度，不用打开日志就能判断某段有没有进去。
    """
    source = _read(BACKEND / "api" / "ai.py")
    assert source.count('"instruction_chars": len(') >= 2, (
        "生成标题和生成标签都要记注入长度"
    )
    assert source.count('"topic_skill_chars": len(') >= 2


def test_generation_context_records_persona():
    """`context` 没有 persona 痕迹时，事后分不清「没配」和「配了没用上」。"""
    source = _read(BACKEND / "api" / "ai.py")
    start = source.find("def _generation_context(")
    block = source[start : source.find("\n@router", start)]
    assert '"persona_chars"' in block


def test_meta_lines_from_skill_manuals_are_filtered():
    """Skill 手册里的「先输出暂定标题公式」会被模型当成要输出的内容。

    实测：注入七类选题库后生成 3 个标题，第一条是「暂定标题公式」——
    那不是标题。修法是提示词划边界 + 出口过滤双保险。
    """
    from backend.app.services.ai_service import _looks_like_meta

    # 手册元话语
    for line in ("暂定标题公式", "（暂定标题公式）", "标题公式", "以下是三个标题", "说明："):
        assert _looks_like_meta(line), f"{line!r} 应该被过滤"
    # 真正的标题不能被误杀
    for line in (
        "合并单元格一排序就报错，怎么破",
        "暂定五月去大理的四个理由",
        "标题公式我用了两年，最有效的只有这一条",
        "3 步拆开合并单元格",
    ):
        assert not _looks_like_meta(line), f"{line!r} 是正常标题，被误删了"


def test_tags_filter_meta_lines_too():
    """标签路径同样注入了 topic Skill，也会吐出元话语。

    `generate_tags` 是按逗号切分的，切完每段都要过一遍过滤——
    否则标签里会多出一个「暂定标题公式」。
    """
    source = _read(BACKEND / "services" / "ai_service.py")
    start = source.rfind("def generate_tags(")
    block = source[start : source.find("\n    def ", start + 10)]
    assert "_looks_like_meta(item)" in block
    assert "【边界】" in block


def test_title_prompt_tells_model_to_ignore_manual_format():
    """注入整本手册后，必须在提示词里声明「不执行它的输出格式」。"""
    source = _read(BACKEND / "services" / "ai_service.py")
    # Protocol 里也有同名声明，取真正的实现（最后一次出现）
    start = source.rfind("def generate_titles(")
    assert start > 0
    block = source[start : source.find("\n    def ", start + 10)]
    assert "【边界】" in block
    assert "本次只输出标题本身" in block


# ---------------------------------------------------------------- I5 flat 自检


def test_flat_template_checks_are_wired():
    source = _read(BACKEND / "services" / "publish_preflight_service.py")
    assert "def _flat_template_checks(" in source
    assert "checks.extend(_flat_template_checks(db, user, draft))" in source, (
        "定义了但没调用，flat 模板的自检仍然是静默通过"
    )
    for key in ("tpl_title", "tpl_structure", "tpl_cta", "tpl_keywords"):
        assert key in source, f"缺少 {key} 检查"


def test_flat_checks_skip_positional():
    """positional 走 _structure_checks（能算覆盖度），不要再重复一遍。"""
    source = _read(BACKEND / "services" / "publish_preflight_service.py")
    start = source.find("def _flat_template_checks(")
    block = source[start : source.find("\ndef ", start + 10)]
    assert 'payload.get("kind") == "positional"' in block


def test_structure_check_accepts_flat_templates():
    """`/structure-check` 对 flat 模板以前直接 400。

    用户选了 AI 赛道模板，点「结构检查」得到的是一句「这个模板不是按
    开头/中段/结尾拆的位置模板」——它确实不是，但这不是错误，是问题问错了。
    现在改成返回检查清单，并明确 `coverage: null`（0 会被读成完全不符合）。
    """
    source = _read(BACKEND / "api" / "platforms" / "xhs" / "insights.py")
    start = source.find("def check_template_structure(")
    assert start > 0
    block = source[start : source.find("\n@router", start)]
    assert "无法做结构检查" not in block, "flat 模板仍然直接 400"
    assert "_flat_template_checks" in block, "flat 分支没有走检查清单"
    assert '"coverage": None' in block, "flat 返回 0 会被读成「完全不符合」"


# ---------------------------------------------------------------- I9 待发布口径


def test_pending_publish_definition_is_one_place():
    """待发布 = pending + scheduled。定义只能在 publish_queue_service 里。"""
    service = _read(BACKEND / "services" / "publish_queue_service.py")
    assert 'PENDING_PUBLISH_STATUSES: tuple[str, ...] = ("pending", "scheduled")' in service
    assert "def publish_job_counts(" in service
    assert "def pending_publish_count(" in service


def test_publishing_is_not_pending():
    """正在发的不该算进「等你确认」，否则数字和列表对不上。"""
    service = _read(BACKEND / "services" / "publish_queue_service.py")
    start = service.find("PENDING_PUBLISH_STATUSES")
    line = service[start : service.find("\n", start)]
    assert "publishing" not in line


def test_overview_uses_shared_count():
    source = _read(BACKEND / "api" / "platforms" / "xhs" / "analytics.py")
    assert "publish_job_counts(db, current_user" in source
    assert '"pending_publishes": publish_counts["pending"]' in source
    # 旧的 4 状态 in_ 查询必须消失（uploading 根本不是 job 状态）
    assert 'PublishJob.status.in_(["pending", "uploading"' not in source


def test_agent_counts_are_not_limited_rows():
    """助手页以前 `len(publish_jobs)` 而查询带 limit(5)：30 条待发布显示 5。"""
    source = _read(BACKEND / "services" / "agent_service.py")
    assert '"pending_publish_jobs": publish_counts["pending"]' in source


def test_publish_list_returns_whole_table_counts():
    source = _read(BACKEND / "api" / "publish.py")
    start = source.find("def get_publish_jobs(")
    block = source[start : source.find("\n@router", start)]
    assert "publish_job_counts(" in block
    assert '"counts": counts' in block, "前端拿不到整表统计，只能数分页后的行"


def test_frontend_uses_backend_counts():
    source = _read(SRC / "pages" / "Publish.tsx")
    assert "counts?.pending" in source, "前端还在自己数分页后的行"
    # 队列和日历必须共用一个取数函数，否则缓存里先到的那个决定行为
    assert source.count("loadPublishJobs") >= 3
    assert "page_size=500" in source, "日历只要 20 条，第 21 条起的排期会消失"


def test_overview_separates_publishing_from_pending():
    """今日页要把「正在发」和「等确认」分开说。

    以前 publishing 被算进 pending_publishes，用户看到 3 条待确认，
    点进去只有 1 条有确认按钮——另外 2 条已经在发了。
    """
    source = _read(SRC / "pages" / "Overview.tsx")
    assert "publishing_jobs" in source
    assert "正在发" in source


def test_no_hardcoded_pending_status_list_in_frontend():
    source = _read(SRC / "pages" / "Publish.tsx")
    # 允许 fallback（旧后端没有 counts 时数这一页），但主路径必须用后端统计
    assert source.count('count("pending")') <= 1
