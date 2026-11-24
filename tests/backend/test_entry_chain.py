"""入口链路必须「写得出来、点得动、落得下」。

这一轮改的东西全都是「写了入口但点不动」那一类问题的反面：
风险页每行的标签从纯文字变成真链接。这类缺陷单测跑不出来（后端全绿），
只有把「标签 → 目标路由 → 页面组件 → 按钮 → 接口」五段连起来看才看得见。

所以这里钉五段，任何一段断了都红。
"""

from __future__ import annotations
import re
from pathlib import Path

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _ts() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): _read(p)
        for p in SRC.rglob("*.ts*")
    }


def test_every_wired_label_is_a_real_link():
    """写了入口文字却不给路径，等于让用户自己去找。

    2026-11-18 第五轮结束时，风险页每行都写了「设置 › 自动运营」，
    但那是个 `<span>`——点不动，也没有 href。用户看到「入口在设置里」
    还得自己去侧栏翻。
    """
    comp = _read(SRC / "components" / "RiskControls.tsx")

    # 数据形状必须是 {label, path?}
    assert "Record<string, { label: string; path?: string }>" in comp, (
        "入口表退化成了纯字符串，标签又会变成不可点"
    )
    # 渲染时必须有 Link / button 两个分支
    assert "<Link" in comp, "标签没有渲染成路由链接"
    assert "rc__tag--link" in comp, "缺少可点标签的样式类"


def test_wired_paths_point_at_pages_that_exist():
    """标签里的路径必须真的能打开。

    两半都要查：
    1. 路由声明（App.tsx 的 Route 或 navigation.ts 的 tabs + Settings 分支）
    2. 目标页面组件真的被渲染（不是只有一条空路由）
    """
    comp = _read(SRC / "components" / "RiskControls.tsx")
    nav = _read(SRC / "app" / "navigation.ts")
    settings = _read(SRC / "pages" / "Settings.tsx")
    files = _ts()

    paths = re.findall(r'path:\s*"(/[^"#]+)"', comp)
    assert paths, "入口表里一个路径都没有"

    for path in paths:
        assert path in files["app/navigation.ts"] or path in files["app/App.tsx"], (
            f"{path} 不在导航或路由里"
        )

    # /settings/* 是同一个 Settings 组件按子路径分支，必须确认每个都有内容
    assert '"/settings/auto-ops"' in nav
    assert "AutoOpsPanel" in settings
    assert '"/settings/matrix"' in nav
    assert "MatrixPanel" in settings
    assert "/assets/library" in nav
    assert "rewriteSelected" in files["pages/Library.tsx"]


def test_entry_pages_call_endpoints_that_exist():
    """入口页上的按钮，调的接口必须真的在后端注册了。

    这条防的是「页面打开了、按钮也在、点下去 404」。
    """
    import sys

    sys.path.insert(0, str(REPO))

    from backend.app.main import app

    spec = app.openapi()
    routes = {
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
    }

    def has(method: str, path: str) -> bool:
        return any(m == method and p == path for m, p in routes)

    assert has("GET", "/api/auto-tasks"), "自动运营列表接口不存在"
    assert has("POST", "/api/auto-tasks"), "自动运营创建接口不存在"
    assert has("POST", "/api/auto-tasks/{task_id}/run"), "自动运营跑一次接口不存在"
    assert has("PATCH", "/api/auto-tasks/{task_id}"), "自动运营改接口不存在"
    assert has("DELETE", "/api/auto-tasks/{task_id}"), "自动运营删接口不存在"

    assert has("POST", "/api/xhs/matrix/suggest-directions")
    assert has("POST", "/api/xhs/matrix/generate")
    assert has("POST", "/api/notes/batch-rewrite-drafts")

    # 前端确实在调它们（不是只存在于后端）
    files = _ts()
    auto_lib = files["lib/autoTasks.ts"]
    for needle in ("/api/auto-tasks", "/run", "/api/auto-tasks/${id}"):
        assert needle in auto_lib, f"lib/autoTasks.ts 里没有 {needle}"
    assert "/api/xhs/matrix/generate" in files["components/MatrixPanel.tsx"]
    assert "batch-rewrite-drafts" in files["pages/Library.tsx"]


def test_blockers_are_explained_on_the_page_not_after_the_click():
    """前置条件不满足时，页面必须提前说清，而不是让用户点下去撞 4xx。

    · 自动运营要 pc + creator 两个账号（auto_tasks.py:178-179）
    · 矩阵要 2~5 个账号（matrix.py:36）
    · 批量改写一次最多 5 篇（notes.py 的 BatchRewriteRequest）

    光写一句「去设置绑定」不够——那句话本身也得是能点的链接，
    否则用户还得自己去侧栏找。这正是风险页刚犯过的错。
    """
    autoops = _read(SRC / "components" / "AutoOpsPanel.tsx")
    matrix = _read(SRC / "components" / "MatrixPanel.tsx")
    library = _read(SRC / "pages" / "Library.tsx")

    # 自动运营：缺 creator 时给出说明和去处，且去处是链接
    assert "创作中心账号" in autoops
    assert "canCreate" in autoops, "没有前置条件判断，直接让用户建任务"
    assert 'to="/settings/accounts"' in autoops, "说了「去账号页绑」却没给链接"

    # 矩阵：账号不够时说明「至少要两个」，按钮置灰，去处是链接
    assert "至少要两个" in matrix or "至少两个" in matrix
    assert "canRun" in matrix
    assert 'to="/settings/accounts"' in matrix, "说了「再绑一个」却没给链接"

    # 批量改写：超过 5 篇要明说，不能静默截断
    assert "一次最多改写 5 篇" in library


def test_scheduler_status_is_visible_where_the_switch_lives():
    """「自动发布」开关的效果取决于调度器在不在跑。

    这两件事必须在同一屏上，否则用户开了自动发布、以为从此自动，
    实际调度器没起，一次也不会发。
    """
    comp = _read(SRC / "components" / "RiskControls.tsx")
    assert "SchedulerStatus" in comp
    assert "/api/settings/scheduler" in comp, "读的是旧接口，改配置的入口不在"
    assert "启动调度器" in comp and "停止调度器" in comp

    # 后端两条端点都在
    import sys

    sys.path.insert(0, str(REPO))
    from backend.app.main import app

    spec = app.openapi()
    assert "get" in spec["paths"]["/api/settings/scheduler"]
    assert "put" in spec["paths"]["/api/settings/scheduler"]
