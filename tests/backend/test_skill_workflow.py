"""Skill 工作流执行：步骤抽取与完成标准核验。

These tests cover the pure parts. The model call is stubbed so the suite never
needs a network round trip.
"""

from __future__ import annotations

from backend.app.services.skill_workflow_service import (
    _extract_steps,
    _grade,
    _is_checkable,
)

RIAAEB = """# 低粉爆款内容骨架拆解

## R — 原文

> "找低粉爆款，直接拆。"

## E — 可执行步骤

1. **定义搜索词**
   - 从用户赛道中提取 5-10 个核心词。
   - 完成标准: 每个词都能在小红书搜索框直接使用。

2. **筛选低粉高数据样本**
   - 记录账号粉丝量、点赞收藏评论。
   - 完成标准: 至少得到 5 个样本。

3. **做共鸣原因解码**
   - 判断样本是否释放了用户不敢说的话。
   - 完成标准: 输出它为什么会被互动的心理原因。

## B — 边界

- 不要逐字模仿。
"""

VISUAL = """# 小红书封面锚点

## 选择模板与锚点

1. 先选一个完整封面模板。
2. 确定一个唯一锚点。

## 质量门

在调用图像工具前，先写一条内容专属艺术方向。

- `缩略图`：在约 80px 宽时仍先看见标题承诺。
- `文字`：标题逐字准确、层级清楚。
- `锚点`：主体确实服务标题。

## 边界

- 不把无来源的百分比作为视觉事实。
"""


def test_extract_steps_reads_riaaeb_steps_and_criteria():
    steps = _extract_steps(RIAAEB)

    assert [step["index"] for step in steps] == [1, 2, 3]
    assert steps[0]["title"] == "定义搜索词"
    assert "搜索框" in steps[0]["criterion"]
    assert "至少得到 5 个样本" in steps[1]["criterion"]


def test_extract_steps_reads_visual_quality_gate():
    steps = _extract_steps(VISUAL)

    assert [step["title"] for step in steps] == ["缩略图", "文字", "锚点"]
    assert "80px" in steps[0]["criterion"]


def test_extract_steps_returns_empty_for_spec_only_skill():
    """A router spec with neither E nor 质量门 has no runnable steps."""
    spec = """# 视觉路由器

## 先做预检

1. 先问封面精确标题。

## 选择专家

| 用户意图 | 交给 |
| --- | --- |
"""
    assert _extract_steps(spec) == []


def test_is_checkable_rejects_subjective_criteria():
    assert _is_checkable("至少得到 5 个样本")
    assert _is_checkable("列出 3-10 个具体问题点")
    assert not _is_checkable("用户能判断这像我会说的话")
    assert not _is_checkable("")


def _steps():
    return [
        {"index": 1, "title": "定义搜索词", "detail": [], "criterion": "至少 5 个词"},
        {"index": 2, "title": "共鸣解码", "detail": [], "criterion": "用户能判断这像我会说话"},
        {"index": 3, "title": "视觉骨架", "detail": [], "criterion": "输出视觉公式"},
    ]


def test_grade_counts_passed_failed_and_unverifiable():
    reported = [
        {"index": 1, "status": "done", "result": "AI工具、一人公司等 10 个词"},
        {"index": 2, "status": "done", "result": "释放了不敢说的话"},
        {"index": 3, "status": "failed", "result": "缺封面截图"},
    ]

    gate = _grade(_steps(), reported, artifact_md="# 产物")

    assert gate["passed"] == 1
    assert gate["unverifiable"] == 1
    assert gate["failed"] == 1
    assert gate["status"] == "failed"
    by_index = {check["index"]: check for check in gate["steps"]}
    assert by_index[2]["status"] == "unverifiable"
    assert by_index[3]["status"] == "failed"


def test_grade_fails_when_model_skips_a_step():
    """A silently omitted step must count as failed, not pass by default."""
    gate = _grade(_steps(), [{"index": 1, "status": "done", "result": "ok"}], "# 产物")

    by_index = {check["index"]: check for check in gate["steps"]}
    assert by_index[2]["status"] == "failed"
    assert "没有回报" in by_index[2]["reason"]
    assert by_index[3]["status"] == "failed"


def test_grade_fails_when_artifact_is_empty():
    reported = [{"index": index, "status": "done", "result": "ok"} for index in (1, 2, 3)]

    gate = _grade(_steps(), reported, "   ")

    assert gate["passed"] == 0
    assert gate["failed"] == 2
    assert gate["unverifiable"] == 1


def test_grade_passes_only_when_all_checkable_steps_deliver():
    reported = [{"index": index, "status": "done", "result": "ok"} for index in (1, 2, 3)]

    gate = _grade(_steps(), reported, "# 产物")

    assert gate["status"] == "passed"
    assert gate["passed"] == 2
    assert gate["unverifiable"] == 1
    assert gate["completion"] == round(2 / 3, 3)


def test_grade_aligns_steps_without_index_by_position():
    """模型只按顺序回报、不写 index 时，不能把 9 步全判「没有回报」。

    这是 gate 恒为 0 的另一种成因：产物写好了，步骤也逐条说了，
    只是没带 index。按顺序对齐后应该能正常核验。
    """
    reported = [
        {"status": "done", "result": "10 个词"},
        {"status": "done", "result": "像我会说的话"},
        {"status": "done", "result": "视觉公式"},
    ]

    gate = _grade(_steps(), reported, "# 产物")

    assert gate["not_reported"] == 0
    assert gate["failed"] == 0
    assert gate["passed"] == 2
    assert gate["unverifiable"] == 1


def test_grade_aligns_steps_by_title_when_index_is_noisy():
    reported = [
        {"index": "步骤 3", "title": "视觉骨架", "status": "done", "result": "公式"},
        {"index": "第 1 步", "title": "定义搜索词", "status": "done", "result": "词"},
        {"index": "2", "title": "共鸣解码", "status": "done", "result": "话"},
    ]

    gate = _grade(_steps(), reported, "# 产物")

    by_index = {check["index"]: check for check in gate["steps"]}
    assert by_index[1]["status"] == "passed"
    assert by_index[3]["status"] == "passed"
    assert gate["not_reported"] == 0


def test_grade_normalizes_chinese_and_boolean_status():
    reported = [
        {"index": 1, "status": "已完成", "result": "ok"},
        {"index": 2, "status": True, "result": "ok"},
        {"index": 3, "status": "跳过", "result": "没有截图"},
    ]

    gate = _grade(_steps(), reported, "# 产物")

    by_index = {check["index"]: check for check in gate["steps"]}
    assert by_index[1]["status"] == "passed"
    assert by_index[2]["status"] == "unverifiable"
    assert by_index[3]["status"] == "failed"
    # 有回报但状态读不懂，不能算失败；它只是无法自动核验
    assert gate["not_reported"] == 0


def test_grade_marks_unreported_separately_from_failed():
    """「模型说没做到」和「模型没提这一步」要在界面上分开。"""
    reported = [{"index": 1, "status": "done", "result": "ok"}]

    gate = _grade(_steps(), reported, "# 产物")

    by_index = {check["index"]: check for check in gate["steps"]}
    assert by_index[1]["reported"] is True
    assert by_index[2]["reported"] is False
    assert gate["not_reported"] == 2
    # 没回报仍然计入 failed（不能默认通过），但数字要单独可见
    assert gate["failed"] == 2
