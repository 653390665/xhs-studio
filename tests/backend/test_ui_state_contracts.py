"""第一批修复的守护测试：界面状态词表 + 请求形状。

这几条都是「前后端各自都对、接起来就错」的地方，单元测试抓不到：

  · Publish 的状态表用的是后端从来不产出的词（queued/running/success），
    于是「已发布」恒为 0、条目显示英文。
  · Agent 把 plan 对象传给要数组的端点，必然 422。
  · 选题生成写死 account_id: 1。
  · 自检结果不随内容变化失效，改完了按钮还是灰的。
  · 送发布前保存失败不中断，带着旧正文发出去。
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


# --- 发布状态词表 -----------------------------------------------------------


def test_publish_status_labels_match_backend():
    """前端的状态表必须覆盖后端实际写的每个值。

    后端写：pending / scheduled / publishing / published / failed / cancelled
    （`grep 'job.status = ' backend/app/services/publish_service.py`）
    """
    service = _read(BACKEND / "services" / "publish_service.py")
    api = _read(BACKEND / "api" / "publish.py")
    backend_states = set(re.findall(r'job\.status\s*=\s*"(\w+)"', service))
    backend_states |= set(re.findall(r'status="(\w+)"', api))

    page = _read(SRC / "pages" / "Publish.tsx")
    block = page.split("const STATUS_LABEL")[1].split("};")[0]
    frontend_states = set(re.findall(r"^\s*(\w+):\s*\{", block, re.M))

    missing = backend_states - frontend_states
    assert not missing, (
        f"前端状态表缺后端会写的状态：{sorted(missing)}。"
        "缺了就会显示英文原文、统计恒为 0。"
    )


def test_publish_stats_use_backend_vocabulary():
    """统计口径不能再用 success / running 这种后端不产出的词。"""
    page = _read(SRC / "pages" / "Publish.tsx")
    stats = page.split("const stats = useMemo")[1].split("}, [items])")[0]
    assert '"published"' in stats, "「已发布」统计应该数 published"
    assert '"publishing"' in stats, "「发布中」统计应该数 publishing"
    assert 'count("success")' not in stats
    assert 'count("running")' not in stats


def test_publish_page_reports_read_failure():
    """读不到队列时不能落进「还没有要发的稿子」。"""
    page = _read(SRC / "pages" / "Publish.tsx")
    assert "jobs.error" in page, "发布页没有判 jobs.error"


# --- Agent plan 形状 --------------------------------------------------------


def test_agent_plan_step_matches_backend():
    """前端 PlanStep 的字段必须能装下后端 AgentPlanStep。"""
    backend = _read(BACKEND / "api" / "agent.py")
    step_block = backend.split("class AgentPlanStep")[1].split("class ")[0]
    backend_fields = set(re.findall(r"^\s{4}(\w+):", step_block, re.M))
    assert backend_fields, "没解析到 AgentPlanStep 字段"

    page = _read(SRC / "pages" / "Agent.tsx")
    ts_block = page.split("interface PlanStep {")[1].split("}")[0]
    ts_fields = set(re.findall(r"^\s*(\w+)\??:", ts_block, re.M))

    # 后端必填的 tool 必须在；args / reason 可以有默认值但字段名要对上
    assert "tool" in ts_fields, "PlanStep 缺 tool"
    missing = backend_fields - ts_fields
    assert not missing, f"PlanStep 缺字段：{sorted(missing)}"


def test_agent_sends_steps_array_not_plan_object():
    """`/api/agent/runs` 要 list，不能传 {steps, summary} 整个对象。"""
    page = _read(SRC / "pages" / "Agent.tsx")
    call = page.split('post<AgentRun>("/api/agent/runs"')[1].split("})")[0]
    assert "plan.steps" in call or "plan:" in call, "没找到 plan 传参"
    assert "plan," not in call.replace("plan.steps", ""), (
        "还在把整个 plan 对象传过去，后端会 422"
    )


# --- 选题账号 ---------------------------------------------------------------


def test_topic_generation_uses_real_account():
    """选题生成不能写死 account_id: 1。"""
    page = _read(SRC / "pages" / "Plan.tsx")
    assert "account_id: 1," not in page, "选题生成还在写死 account_id: 1"
    assert "accountId" in page, "选题页应该从账号列表取 id"


# --- 自检状态失效 -----------------------------------------------------------


def test_check_result_invalidated_on_edit():
    """改内容要清掉上一次自检结果，否则改完了按钮还是灰的。"""
    page = _read(SRC / "pages" / "Write.tsx")
    schedule = page.split("const schedule = useCallback")[1].split("}, [persist])")[0]
    assert "setCheck(null)" in schedule, (
        "schedule() 没有清 check：自检报错后改完正文，送发布按钮仍是灰的"
    )


# --- 送发布前保存失败要中断 -------------------------------------------------


def _fn_body(source: str, start_marker: str, end_marker: str) -> str:
    """取出从 start_marker 到 end_marker 之间那段。找不到就返回空串。

    比 `split(x)[1]` 安全：文件里常有同名函数（`send(message)` 与 `send()`），
    取错了段会得出完全相反的结论。
    """
    i = source.find(start_marker)
    if i < 0:
        return ""
    j = source.find(end_marker, i)
    return source[i : j if j > 0 else len(source)]


def test_send_aborts_when_save_fails():
    """保存失败必须中止送发布，否则发出去的是旧正文。"""
    page = _read(SRC / "pages" / "Write.tsx")
    # 注意：文件里有两个 send——ChatPane 的 send(message) 和 Artifact 的 send()。
    # 必须锚定无参那个，否则会去检查对话发消息的逻辑。
    send_fn = _fn_body(page, "async function send() {", "const blocked")
    assert "persist()" in send_fn, "send 里没有先保存"
    assert re.search(r"if\s*\(\s*!ok\s*\)", send_fn), (
        "send 没有检查保存结果：保存失败会带着旧正文继续送发布"
    )
    # persist 必须真的返回布尔，不能只 toast 然后吞掉
    persist = _fn_body(page, "const persist = useCallback", "}, [draft.id")
    assert "Promise<boolean>" in persist, "persist 没有返回布尔"
    assert "return true" in persist and "return false" in persist


# --- 卸载时落盘 -------------------------------------------------------------


def test_unmount_flushes_pending_edits():
    """切页/关页时要真的把改动发出去，不能只 clearTimeout。

    文件里有多处 effect 会 clearTimeout（例如「服务器上的草稿被别处改了」
    那条也会清定时器但它不该保存）。所以要求：**至少有一处**在清理函数里
    调了 saveDraft，而不是「每一处都必须」。
    """
    page = _read(SRC / "pages" / "Write.tsx")
    blocks = page.split("useEffect(() => {")
    flushed = [
        block
        for block in blocks
        if "clearTimeout(timer.current)" in block.split("}, [")[0]
        and "saveDraft(" in block.split("}, [")[0]
    ]
    assert flushed, (
        "没有任何卸载 effect 在清理时落盘——900ms 内切页改动就丢了"
    )


# --- 批量删除 ---------------------------------------------------------------


def test_batch_delete_invalidates_in_finally():
    """删除中途失败，前面已删的也必须从界面消失。"""
    page = _read(SRC / "pages" / "Library.tsx")
    fn = page.split("async function removeSelected(")[1].split(
        "async function applyTag"
    )[0]
    # 注释里也会出现 "finally" 这个词，必须锚定代码——`} finally {`
    assert "} finally {" in fn, "removeSelected 没有 finally 块"
    finally_block = fn.split("} finally {")[1]
    assert "invalidate" in finally_block, (
        "invalidate 不在 finally 里：中途失败会把已删的行留在界面上"
    )
