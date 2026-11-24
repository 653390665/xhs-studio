"""第四批（体验出口）的契约测试。

这一批的共同形态是「后端有、前端零调用」。单元测试抓不到——因为每一层
单独看都是对的，缺的是**线**。所以断言的是调用关系，不是行为。

覆盖：
  I12  找资料 → `/api/ai/outline`（不再偷偷建草稿）
  I17  助手 → `confirm-publish`（awaiting_confirmation 时有按钮）
  S7   `/api/tasks`（任务记录能查失败原因）
  S8   `/api/notifications`（后台失败看得见）
  S9   发布队列 `retry` / `delete`
  S10  `/api/settings/risk-controls`
  I15  `pagehide` + keepalive（关标签页也落盘）
  I19  三份 `_serialize_draft` 统一
  I20  两个 `_serialize_publish_job` 统一
"""
from __future__ import annotations
import io
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


def _strip_comments(source: str) -> str:
    """去掉注释。删掉实现之后注释里还会提到名字，那是记录不是调用。"""
    import re

    text = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


# ---------------------------------------------------------------- I12 找资料


def test_search_uses_outline_endpoint_not_generate():
    """看角度不能建草稿。

    原来调 `/api/ai/generate-note`：正文被丢弃，但草稿真的存进了库；
    而 `angles` 后端从来没返回，列表永远空。
    """
    page = _read(SRC / "pages" / "Search.tsx")
    code = _strip_comments(page)
    assert '"/api/ai/outline"' in code, "找资料没有走 /api/ai/outline"
    assert 'post<Outline>("/api/ai/generate-note"' not in code, (
        "还在调生成接口——看一次角度会多一篇草稿"
    )


def test_outline_endpoint_does_not_create_draft():
    """后端 `/outline` 里不能出现 `db.add(AiDraft(`。"""
    source = _read(BACKEND / "api" / "ai.py")
    start = source.find('@router.post("/outline")')
    assert start > 0, "没有 /outline 端点"
    block = source[start : source.find("\n@router", start + 10)]
    assert "AiDraft(" not in block, "/outline 建了草稿，语义就退化了"
    assert '"angles"' in block, "返回里没有 angles"
    assert "ai_outline" in block, "没有记任务，失败排不了"


def test_outline_returns_usable_shape():
    """前端读 `angles` / `notes`，后端就得给这两个键。"""
    page = _read(SRC / "pages" / "Search.tsx")
    assert "outline.angles" in page
    assert "outline.notes" in page
    assert "用它写" in page, "角度生成出来没有落笔入口"


# ---------------------------------------------------------------- I17 助手确认


def test_agent_has_confirm_publish_button():
    """停在 awaiting_confirmation 时必须有按钮。

    后端 `POST /runs/{id}/confirm-publish` 一直都在，前端只在一行注释里
    提过它。用户看到的是英文状态词，找不到地方回答。
    """
    page = _read(SRC / "pages" / "Agent.tsx")
    code = _strip_comments(page)
    assert "confirm-publish" in code, "没有调用确认发布"
    assert "awaiting_confirmation" in code, "没有识别待确认状态"
    assert "确认发布这条" in page, "待确认时没有可点的按钮"


def test_agent_status_words_are_chinese():
    """后端五个状态值都要有中文。"""
    page = _read(SRC / "pages" / "Agent.tsx")
    for status in (
        "running",
        "awaiting_confirmation",
        "completed",
        "failed",
        "cancelled",
    ):
        assert status in page, f"缺少状态 {status} 的映射"
    assert "等你确认发布" in page


# ---------------------------------------------------------------- S7 任务记录


def test_backend_tasks_layer_exists():
    lib = _read(SRC / "lib" / "backendTasks.ts")
    assert "/api/tasks" in lib
    assert "cancelTask" in lib and "retryTask" in lib
    assert "taskError" in lib, "没有从 payload.error 取失败原因"


def test_task_panel_is_mounted():
    page = _read(SRC / "pages" / "Settings.tsx")
    assert "TaskPanel" in page, "任务记录没有挂进设置页"
    panel = _read(SRC / "components" / "TaskPanel.tsx")
    assert "taskError" in panel
    assert "重试" in panel and "取消" in panel


def test_task_panel_shows_failure_reason():
    """失败原因要展开显示，不能只藏在 tooltip 里。"""
    panel = _read(SRC / "components" / "TaskPanel.tsx")
    assert "tsk__error" in panel
    assert "<p className=" in panel or "taskError(task)" in panel


# ---------------------------------------------------------------- S8 通知


def test_notifications_are_read_by_frontend():
    lib = _read(SRC / "lib" / "notifications.ts")
    assert "/api/notifications" in lib
    assert "read-all" in lib
    shell = _read(SRC / "components" / "Shell.tsx")
    assert "Notifications" in shell, "通知没有挂进外壳"


def test_publish_failure_creates_notification():
    """发布失败要留通知。

    `notifications` 表有五个写入函数，但最需要通知的发布失败路径从来没调过。
    """
    service = _read(BACKEND / "services" / "publish_service.py")
    start = service.find("def _mark_failed(")
    assert start > 0
    block = service[start : service.find("\n    def ", start + 10)]
    assert "notify_publish_failed" in block, "发布失败没有写通知"

    scheduler = _read(BACKEND / "services" / "scheduler_service.py")
    start = scheduler.find("def _fail_job(")
    block = scheduler[start : scheduler.find("\ndef ", start + 10)]
    assert "notify_publish_failed" in block, "定时发布失败没有写通知"


def test_notification_targets_lead_somewhere():
    """点一条通知要能去解决它，不能原地不动。"""
    lib = _read(SRC / "lib" / "notifications.ts")
    assert "notificationTarget" in lib
    for route in ("/publish", "/settings/accounts", "/assets"):
        assert route in lib, f"通知缺少指向 {route} 的分支"


# ---------------------------------------------------------------- S9 队列出口


def test_publish_queue_has_retry_and_delete():
    page = _read(SRC / "pages" / "Publish.tsx")
    code = _strip_comments(page)
    assert "/retry" in code, "失败的 job 不能重试"
    assert "`/api/publish/jobs/${job.id}`" in code, "失败的 job 不能删除"
    assert "重试" in page and "删除" in page


# ---------------------------------------------------------------- S10 风控


def test_risk_controls_ui_exists():
    page = _read(SRC / "pages" / "Settings.tsx")
    assert "RiskControls" in page, "风险开关没有挂进设置"
    component = _read(SRC / "components" / "RiskControls.tsx")
    assert "/api/settings/risk-controls" in component
    assert "acknowledge_risk" in component, "高风险开关没有确认环节"
    assert "暂未开放" in component, "保留字段没标出来，点了会报错"


def test_risk_controls_route_registered():
    nav = _read(SRC / "app" / "navigation.ts")
    assert "/settings/risk" in nav, "导航里没有风险开关入口"


# ---------------------------------------------------------------- I15 落盘


def test_unsaved_edits_survive_tab_close():
    """关标签页也要落盘。

    组件卸载那次只覆盖「路由切换」；改完直接 Ctrl+W 走的是 `pagehide`，
    必须带 keepalive，否则浏览器会把请求丢掉。
    """
    page = _read(SRC / "pages" / "Write.tsx")
    assert "pagehide" in page, "没有监听 pagehide"
    assert "keepalive" in page, "卸载时的保存没有带 keepalive"

    api = _read(SRC / "lib" / "api.ts")
    assert "keepalive" in api, "请求层不支持 keepalive"


# ---------------------------------------------------------------- I19 / I20 序列化


def test_draft_serializer_is_shared():
    """三份 `_serialize_draft` 必须统一。

    第三份（notes.py）只有 6 个键，`batch-rewrite-drafts` 拿到的草稿
    没有 tags / context / review_status，界面分不清「空」和「没返回」。
    """
    serializers = _read(BACKEND / "schemas" / "serializers.py")
    assert "def serialize_draft(" in serializers
    assert "DRAFT_FIELDS" in serializers

    # 三个 router 都必须引用它，而不是各写一份字典
    from backend.app.schemas.serializers import DRAFT_FIELDS

    assert "context" in DRAFT_FIELDS
    assert "review_status" in DRAFT_FIELDS
    assert "tags" in DRAFT_FIELDS
    assert len(DRAFT_FIELDS) >= 18

    for name in ("ai.py", "drafts.py", "notes.py"):
        source = _read(BACKEND / "api" / name)
        imported = "from backend.app.schemas.serializers import" in source
        assert imported, f"{name} 没有引用共享序列化器"
        start = source.find("def _serialize_draft(")
        assert start > 0
        block = source[start : start + 900]
        assert "return serialize_draft(draft)" in block, (
            f"{name} 还在自己拼字典——迟早又漂一次"
        )


def test_publish_job_serializer_is_shared():
    serializers = _read(BACKEND / "schemas" / "serializers.py")
    assert "def serialize_publish_job(" in serializers

    from backend.app.schemas.serializers import PUBLISH_JOB_FIELDS

    # 这七个是 drafts.py 那份漏掉的
    for key in (
        "origin",
        "skill_version",
        "pillar",
        "experiment",
        "external_note_id",
        "publish_error",
        "published_at",
    ):
        assert key in PUBLISH_JOB_FIELDS, f"共享序列化器缺 {key}"

    for name in ("drafts.py", "publish.py"):
        source = _read(BACKEND / "api" / name)
        assert "schemas.serializers import" in source, f"{name} 没引用共享序列化器"


# ---------------------------------------------------------------- batchSync


def test_batch_sync_failure_is_reported():
    """提炼批次同步失败不能只 console.warn。

    三处调用方都是 `void pushBatch(...)` 紧跟着 `toast.success`：
    后端真失败时用户看到「提炼成功」，写稿页的「素材」下拉却是空的。
    """
    for page in ("Studio.tsx", "Projects.tsx"):
        source = _read(SRC / "pages" / page)
        code = _strip_comments(source)
        assert "void pushBatchFrom" not in code, f"{page} 还在 `void` 掉同步结果"
        assert "const synced = await pushBatchFrom" in code or "synced" in code, (
            f"{page} 没有检查同步结果"
        )


# ---------------------------------------------------------------- 表达


def test_search_page_mentions_source_reliability():
    """角度列表要带「这些角度依赖哪条资料」。"""
    page = _read(SRC / "pages" / "Search.tsx")
    assert "outline.notes" in page
