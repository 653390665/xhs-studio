"""Module labels must not promise capabilities the code does not have.

Three modules (persona / benchmark / schedule) never reach ``module_skill_text``
because none of their entry points calls a model: the persona generator is gone
(HTTP 410), the benchmark report is deterministic aggregation, and scheduling is
a fixed date template. That is a design choice, not a defect — these Skills are
meant to be *run* (``run_skill_workflow`` → artifact + gate + open_questions),
not spliced into a writing prompt.

What *was* a defect is what the library told the user. ``feature`` read
「账号 → 画像 / AI 生成建议」 above a screen that is six empty inputs. Same shape
as an endpoint nobody calls: the interface describing a system that does not
exist.

These tests pin the honest labels so a future edit cannot quietly reintroduce
the promise.
"""

from __future__ import annotations

import pytest

from backend.app.services.skill_library_service import MODULES, MODULE_LABELS


def _by_key() -> dict[str, dict]:
    return {item["key"]: item for item in MODULES}


def test_every_module_declares_whether_it_is_auto_injected():
    """Silence is what allowed the implication. Every module states it."""
    for item in MODULES:
        assert "auto_injected" in item, f"{item['key']} 没有声明 auto_injected"
        assert isinstance(item["auto_injected"], bool)


def test_the_three_decision_modules_are_marked_as_run_on_demand():
    """No model call means no automatic injection — say so."""
    modules = _by_key()
    for key in ("persona", "benchmark", "schedule"):
        assert modules[key]["auto_injected"] is False, (
            f"{key} 的入口不调用模型，不能标注为自动注入"
        )


def test_generation_modules_are_marked_as_auto_injected():
    """The modules that really are spliced into prompts stay marked as such."""
    modules = _by_key()
    for key in ("draft", "topic", "visual"):
        assert modules[key]["auto_injected"] is True


def test_persona_does_not_promise_ai_generated_advice():
    """That generator returns 410; the screen is a form the owner fills."""
    feature = _by_key()["persona"]["feature"]
    assert "AI 生成建议" not in feature, (
        "画像生成接口已下线（410），不能再承诺 AI 生成建议"
    )
    assert "试运行" in feature or "人工" in feature


def test_schedule_does_not_promise_publishing():
    """Scheduling a post is a date template; the Skill produces a plan."""
    feature = _by_key()["schedule"]["feature"]
    assert "发布 / 洞察" not in feature, "排期入口不负责发布，也没有洞察分析"
    assert "试运行" in feature


def test_benchmark_feature_describes_the_artifact_not_a_report_endpoint():
    feature = _by_key()["benchmark"]["feature"]
    # The benchmark report endpoint returns 404 and the draft endpoint only
    # copies notes. The Skill's real product is a decomposition report.
    assert "试运行" in feature


def test_labels_stay_unique_and_complete():
    """MODULE_LABELS is derived; a duplicate key would silently drop a module."""
    assert len(MODULE_LABELS) == len(MODULES)
    for label in MODULE_LABELS.values():
        assert label.strip()
