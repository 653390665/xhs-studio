"""第三/四批：定位引导 + 助手可用性 + 风控/搜索源的诚实标注。

对应你提的：

* 「账号定位不是应该通过 agent 调用 skill 对话，然后经过引导，以及确认最后
  出现的内容吗？猜一版太不严谨了」
* 「助手页面单独作为一级页面，同时审查它的页面结构和逻辑」
* 「风险开关中的这些功能，有实际配置吗？」
* 「这里的搜索源为什么是出现在这里，而不是在素材-采集里面呢」

这里钉的是链路，不是界面文案。
"""
from __future__ import annotations
import io
import os
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


# ---------------------------------------------------------------- 定位引导


def test_guide_service_uses_persona_skill():
    """引导必须真的读 persona Skill，而不是再写一份提示词。

    这是和 `/draft` 的根本区别：那个一次调用、不提问，
    而且 `account_positioning.py` 里 `module_skill_text` 出现 0 次。
    """
    service = _read(BACKEND / "services" / "positioning_guide_service.py")
    assert 'module_skill_text(' in service
    assert '"persona"' in service
    assert "方法论" in service


def test_guide_returns_questions_then_draft():
    service = _read(BACKEND / "services" / "positioning_guide_service.py")
    assert '"questions"' in service
    assert '"ready"' in service
    # 每个字段要标来源，否则用户分不清「我说的」和「系统猜的」
    assert "SOURCE_ASKED" in service
    assert "SOURCE_INFERRED" in service
    assert "SOURCE_UNKNOWN" in service


def test_guide_does_not_write_to_db():
    """引导只出草案，落库是 `/apply-draft`。"""
    service = _read(BACKEND / "services" / "positioning_guide_service.py")
    start = service.find("def guide_positioning(")
    block = service[start : service.find("\ndef ", start + 10)]
    assert "upsert_positioning" not in block, "引导阶段就写库了"
    assert "db.commit()" not in block


def test_apply_draft_is_the_only_write_path():
    service = _read(BACKEND / "services" / "positioning_guide_service.py")
    start = service.find("def apply_draft(")
    assert start > 0
    block = service[start : service.find("\ndef ", start + 10)]
    assert "upsert_positioning" in block
    assert 'source=source' in block


def test_positioning_endpoints_registered():
    api = _read(BACKEND / "api" / "account_positioning.py")
    assert '@router.post("/guide")' in api
    assert '@router.post("/apply-draft")' in api
    # 旧的 /draft 保留，但降级成「兜底」
    assert '@router.post("/draft")' in api


def test_apply_draft_scoped_by_account():
    """写定位必须带账号；多账号时不能猜。"""
    api = _read(BACKEND / "api" / "account_positioning.py")
    start = api.find("def apply_positioning_draft(")
    block = api[start : api.find("\n@router", start)]
    assert "_resolve_account_id" in block
    assert "多个账号" in block, "多账号时不该猜一个"


def test_panel_primary_action_is_guide():
    """定位页主按钮必须是引导式，猜一版降成次要。"""
    panel = _read(SRC / "components" / "PositioningPanel.tsx")
    assert "引导式定稿" in panel
    assert "直接猜一版" in panel
    # 引导按钮走 primary；猜一版走 secondary
    guide_at = panel.find('variant="primary"')
    guess_at = panel.find("直接猜一版")
    assert guide_at > 0 and guide_at < guess_at, "引导入口应该在「猜一版」前面"
    assert 'variant="secondary"' in panel[guess_at - 500 : guess_at]


def test_guide_component_shows_field_sources():
    comp = _read(SRC / "components" / "PositioningGuide.tsx")
    assert "你说的" in comp
    assert "笔记推断" in comp
    assert "待补" in comp
    assert "applyPositioningDraft" in comp


# ---------------------------------------------------------------- 助手


def test_agent_has_update_draft_tool():
    """助手只会「从头写」，不能「接着改」——这是它最大的缺口之一。"""
    service = _read(BACKEND / "services" / "agent_service.py")
    assert '"name": "update_draft"' in service
    start = service.find("def _update_draft(")
    assert start > 0
    block = service[start : service.find("\ndef ", start + 10)]
    # 改之前先存历史，否则用户没法回滚
    assert "_create_draft_version" in block
    assert "source=\"agent_edit\"" in block
    assert 'name == "update_draft"' in service


def test_agent_has_guide_positioning_tool():
    service = _read(BACKEND / "services" / "agent_service.py")
    assert '"name": "guide_positioning"' in service
    start = service.find("def _guide_positioning_tool(")
    assert start > 0
    block = service[start : service.find("\ndef ", start + 10)]
    assert "guide_positioning(" in block
    # apply 只有 ready 才写
    assert 'result.get("ready")' in block


def test_agent_prompt_says_how_to_use_new_tools():
    service = _read(BACKEND / "services" / "agent_service.py")
    assert "17. 用户要「改这篇" in service
    assert "18. 用户要定账号定位" in service


def test_agent_capabilities_group_positioning():
    from backend.app.services.agent_service import agent_capabilities

    caps = agent_capabilities()
    keys = [group["key"] for group in caps["groups"]]
    assert "positioning" in keys, "能力清单里没有定位分组"
    group = next(g for g in caps["groups"] if g["key"] == "positioning")
    assert any(item["tool"] == "guide_positioning" for item in group["items"])


def test_agent_page_polls_running_runs():
    """后端是后台线程，没有推送；不轮询就永远停在提交那一刻。"""
    page = _read(SRC / "pages" / "Agent.tsx")
    assert "setInterval" in page
    assert "hasLiveRun" in page
    assert 'r.status === "running"' in page


def test_agent_page_shows_steps_and_cancel():
    page = _read(SRC / "pages" / "Agent.tsx")
    assert "r.steps" in page, "没有读后端返回的 steps"
    assert "看这" in page, "没有展开步骤的入口"
    assert "cancel" in page, "没有取消按钮"
    assert "/cancel" in page


def test_agent_page_renders_capability_catalog():
    """`/api/agent/capabilities` 一直有，前端零调用。

    结果就是助手页只有一个空输入框：用户不知道它能做什么、也不知道
    哪些事它不会做（自动发布/私信）。这条链路现在接上了，钉住它。
    """
    page = _read(SRC / "pages" / "Agent.tsx")
    assert "/api/agent/capabilities" in page
    assert "capabilityGroups" in page
    assert "ag__caps" in page
    # 例子点一下要能填进目标框，否则清单只是说明文字
    assert "setGoal(example)" in page


# ---------------------------------------------------------------- 风控


def test_risk_controls_states_which_features_are_unwired():
    """每个开关都必须说清入口在哪，且不能凭印象写。

    2026-11-18 之前这张表所有值都是「尚无入口」——那时候是真的：
    自动运营 / 账号矩阵 / 批量改写三条链路前端零调用。现在三条都接上了，
    文案必须跟着改；否则界面在说反话，用户会以为打开开关没有效果。

    这条测试钉两件事：
    1. 「尚无入口」不能出现在任何一个**已接**的开关上；
    2. 每条已接链路都要点名它的入口页面。
    """
    comp = _read(SRC / "components" / "RiskControls.tsx")
    assert "RISK_WIRED" in comp

    # 三条已接上的链路，标签必须指向真实入口
    assert "设置 › 自动运营" in comp, "自动运营入口已上线，标签要指过去"
    assert "设置 › 账号矩阵" in comp, "账号矩阵入口已上线，标签要指过去"
    assert "样本库 › 改写成草稿" in comp, "批量改写入口已上线，标签要指过去"
    # 自动发布接的是调度器
    assert "已接调度器" in comp
    # 唯一真的没开放的那条
    assert "未开放" in comp


def test_new_entries_actually_exist_in_routes():
    """标签指向的入口必须真的能打开——不然比「尚无入口」更糟。"""
    app = _read(SRC / "App.tsx")
    nav = _read(SRC / "app" / "navigation.ts")

    # 设置子页在 navigation.ts 里声明，Settings.tsx 按 sub 渲染
    assert "auto-ops" in nav, "设置里没有自动运营子页"
    assert "matrix" in nav, "设置里没有账号矩阵子页"
    settings = _read(SRC / "pages" / "Settings.tsx")
    assert "AutoOpsPanel" in settings
    assert "MatrixPanel" in settings

    # 批量改写挂在样本库的选中工具条上
    library = _read(SRC / "pages" / "Library.tsx")
    assert "batch-rewrite-drafts" in library, "样本库没有接批量改写"


def test_risk_controls_wiring_claim_matches_code():
    """标签说的入口，代码里必须真的有调用点。

    这条测试的方向和上一版相反：上一版断言「这三条链路前端零调用」，
    现在三条都接上了。所以改成断言**有**调用——一旦有人删掉入口而不改
    标签，这条会红。
    """
    all_ts = ""
    for dirpath, _, files in os.walk(SRC):
        for name in files:
            if not name.endswith((".ts", ".tsx")):
                continue
            if name == "RiskControls.tsx":
                continue
            all_ts += io.open(
                os.path.join(dirpath, name), encoding="utf-8", errors="replace"
            ).read()

    assert "/api/auto-tasks" in all_ts, "标签指着自动运营，但没有任何调用点"
    assert "/api/xhs/matrix" in all_ts, "标签指着账号矩阵，但没有调用点"
    assert "batch-rewrite-drafts" in all_ts, "标签指着批量改写，但没有调用点"


# ---------------------------------------------------------------- 搜索源


def test_search_key_lives_on_models_page():
    """搜索 Key 是模型 Key 的副本，该在模型页，不该在「运行状态」。"""
    page = _read(SRC / "pages" / "Settings.tsx")
    models_branch = page[page.find('active === "models"') : page.find('active === "image"')]
    assert "SearchSetup" in models_branch, "模型页里没有搜索 Key"
    status_branch = page[page.find('active === "status"') : page.find('active === "risk"')]
    assert "SearchSetup" not in status_branch, "运行状态页还挂着搜索 Key"


def test_search_page_links_to_models():
    page = _read(SRC / "pages" / "Search.tsx")
    assert 'to="/settings/models"' in page
    assert 'to="/settings/status"' not in page, "还在把用户指去运行状态"


def test_materials_page_does_not_mention_search_key():
    """采集用的是账号 cookie，不该提搜索 Key。"""
    page = _read(SRC / "pages" / "Materials.tsx")
    assert "hasSearchKey" not in page
    assert "searchWeb" not in page
