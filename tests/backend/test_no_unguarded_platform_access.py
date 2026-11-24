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
    """Static check: each platform-facing method body must call ``_pace``."""
    source = ADAPTER.read_text(encoding="utf-8")

    # Methods that hit the platform and therefore must pace.
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
        assert "_pace(" in body, f"{name} 没有调用 _pace()，会绕过限速"


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
