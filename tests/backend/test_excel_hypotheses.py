"""Excel 专属假设：检测器行为与选择。"""
from __future__ import annotations

from backend.app.services.evidence_distill_service import _select_hypotheses
from backend.app.services.excel_hypotheses import (
    EXCEL_HYPOTHESES,
    detect_excel_cta,
    detect_excel_failure,
    detect_excel_steps,
    detect_excel_taunt,
    detect_excel_time,
)


def test_failure_scene():
    assert detect_excel_failure("让你把表格拖上去，结果你拖了半天也没拖上去") == 1.0
    assert detect_excel_failure("今天讲一下 Excel 的筛选功能") == 0.0


def test_taunt():
    assert detect_excel_taunt("你不是说自己精通办公软件吗") == 1.0
    assert detect_excel_taunt("这个函数很简单") == 0.0


def test_time_promise():
    assert detect_excel_time("五秒搞定一万个序号") == 1.0
    assert detect_excel_time("我们先看数据") == 0.0


def test_screen_steps():
    assert detect_excel_steps("你先点击表格，然后选择布局") == 1.0
    assert detect_excel_steps("这个功能很好用") == 0.0


def test_cta_close():
    assert detect_excel_cta("这一步就完成了。\n点赞收藏，学会了吗") == 1.0
    assert detect_excel_cta("这一步就完成了。\n下期见") == 0.0


def test_excel_set_is_selectable():
    name, hypotheses = _select_hypotheses([], "excel")
    assert name == "excel"
    assert hypotheses is EXCEL_HYPOTHESES
    assert len(hypotheses) == 5
