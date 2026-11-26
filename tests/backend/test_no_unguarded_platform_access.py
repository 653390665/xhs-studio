"""No code may reach the platform without going through the paced adapter.

The 2026-10-28 incident was not a logic bug: a script called
``XhsPcApiAdapter._api()`` and then the SDK directly, so the budget — installed
on the public methods — never ran. Documentation alone would not have prevented
it, so this test scans the repository instead.

Scope: everything under ``backend/``. Scripts outside the package (throwaway
one-offs in a temp dir) are out of reach here; that gap is covered by
``docs/CRAWL_OPERATIONS.md`` §2.1.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "backend" / "app" / "adapters" / "xhs" / "pc_api_adapter.py"

# Importing the SDK directly is the same hole as calling ``_api()``.
SDK_ENTRYPOINTS = (
    "xhs_pc_apis",
    "xhs_creator_apis",
)

# Files allowed to touch the raw SDK, with the reason.
ALLOWED = {
    # The adapter itself is the one place that may.
    "backend/app/adapters/xhs/pc_api_adapter.py",
    "backend/app/adapters/xhs/creator_api_adapter.py",
    # Login/bootstrap happens before an account exists and needs the raw client.
    "backend/app/api/login_sessions.py",
    # Low-level auth helpers.
    "backend/app/adapters/xhs/request_env.py",
}


def _python_files():
    return [
        p
        for p in (REPO / "backend").rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def test_no_module_calls_the_raw_sdk_outside_the_adapter():
    offenders: list[str] = []
    for path in _python_files():
        rel = _relative(path)
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for entry in SDK_ENTRYPOINTS:
            if re.search(rf"^\s*(from|import)\s+{entry}\b", text, re.M):
                offenders.append(f"{rel}: imports {entry}")

    assert not offenders, (
        "这些文件绕过了限速 adapter 直接引用平台 SDK：\n  "
        + "\n  ".join(offenders)
        + "\n请改用 XhsPcApiAdapter 的公开方法或 HTTP API。"
        "见 docs/CRAWL_OPERATIONS.md §2.1"
    )


def test_no_module_reaches_for_the_private_api_handle():
    """``XhsPcApiAdapter._api()`` outside the adapter class is the incident's hole.

    Matches only when the receiver looks like the PC adapter (``adapter._api()``,
    ``self.adapter._api()``, ``XhsPcApiAdapter(...)._api()``) — the creator
    adapter has an unrelated ``_api()`` of its own, and its calls are paced at a
    different layer.
    """
    offenders: list[str] = []
    pattern = re.compile(r"(?:adapter|pc_adapter|XhsPcApiAdapter\([^)]*\))\._api\(\)")
    for path in _python_files():
        rel = _relative(path)
        if rel == "backend/app/adapters/xhs/pc_api_adapter.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(rel)

    assert not offenders, (
        "``adapter._api()`` 绕过了限速，这些文件不应调用：\n  " + "\n  ".join(offenders)
    )


def test_every_public_platform_method_paces():
    """Static check: each platform-facing method body must pace before calling.

    两种合法写法：
      · 直接 ``self._pace(action)``
      · 走 ``self._call_with_backoff(fn, action)`` —— 它内部先 pace 再发请求，
        撞 429/461 时退避重试（每次重试仍然过预算）

    后者是 2026-11-27 加的：apis 层没有重试，一次瞬时限流会直接变成
    用户可见的失败。但「带重试」不等于「绕过限速」，所以两种都算合规。
    """
    source = ADAPTER.read_text(encoding="utf-8")

    must_pace = (
        "search_note",
        "get_note_info",
        "get_note_comments",
        "get_user_notes",
        "get_user_notes_page",
        "get_user_info",
    )

    for name in must_pace:
        match = re.search(
            rf"\n    def {name}\(.*?(?=\n    def |\nclass |\Z)", source, re.S
        )
        assert match, f"{name} 未找到定义"
        body = match.group(0)
        paced = "_pace(" in body or "_call_with_backoff(" in body
        assert paced, f"{name} 既没 _pace() 也没 _call_with_backoff()，会绕过限速"


def test_call_with_backoff_itself_paces():
    """上面放宽了断言，这里守住真正的底线：那个 helper 必须 pace。"""
    source = ADAPTER.read_text(encoding="utf-8")
    match = re.search(
        r"\n    def _call_with_backoff\(.*?(?=\n    def |\nclass |\Z)", source, re.S
    )
    assert match, "_call_with_backoff 未找到"
    body = match.group(0)
    assert "_pace(" in body, (
        "_call_with_backoff 必须调用 _pace：重试不能变成绕过预算的旁路"
    )


def test_adapter_documents_the_bypass_hazard():
    """The warning must stay at the call site, not only in a doc file."""
    source = ADAPTER.read_text(encoding="utf-8")
    assert "_pace" in source
    assert "bypass" in source.lower() or "绕过" in source


def test_crawl_operations_doc_exists():
    doc = REPO / "docs" / "CRAWL_OPERATIONS.md"
    assert doc.is_file(), "采集操作规范缺失"
    text = doc.read_text(encoding="utf-8")
    # The doc must name the real accident, not a hypothetical.
    assert "294" in text, "规范应记录真实事故的数据规模"
    assert "_api()" in text, "规范应点名直接调用 _api() 的危险"
