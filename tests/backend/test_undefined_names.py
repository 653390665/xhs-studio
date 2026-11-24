"""模块里用了但没导入的名字 —— 这类 bug 只有在运行时才炸。

诊断报告里的三条（`insights.py:591,599` 的 `_detail_business_error` /
`_normalize_detail_payload`）就是这种：文件能 import、服务能启动、接口列表
里也看得见，直到用户真的点「从作者笔记蒸馏风格」，才 500 NameError。

静态检查比运行时便宜得多，也比「等用户踩」早得多。检查是保守的——
所有被赋值的名字（含 for 目标、函数参数、推导式变量）都算已定义，
所以不会因为写法特别而误报。
"""
from __future__ import annotations
import ast
import io
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend" / "app"

# 只查这几个「改了容易漏」的大文件：路由多、跨模块 import 多。
WATCHED = [
    "api/platforms/xhs/insights.py",
    "api/platforms/xhs/analytics.py",
    "api/ai.py",
    "api/publish.py",
    "api/drafts.py",
    "api/notes.py",
    "services/agent_service.py",
    "services/ai_service.py",
    "services/publish_preflight_service.py",
    "services/publish_queue_service.py",
    "services/scheduler_service.py",
    "services/skill_evolution_service.py",
    "services/skill_library_service.py",
]

BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, dict) is False else set(__builtins__)


def _bound_names(tree: ast.AST) -> set[str]:
    """Everything bound anywhere in the module: imports, defs, assigns, params."""
    names: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                names.add(alias.asname or alias.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            names.add(node.name)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            names.add(node.name)
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            names.add(node.name)
            self.generic_visit(node)

        def visit_arg(self, node: ast.arg) -> None:
            names.add(node.arg)
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            # 赋值 / for 目标 / with as / 推导式变量都走这里
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)
            self.generic_visit(node)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name:
                names.add(node.name)
            self.generic_visit(node)

        def visit_Global(self, node: ast.Global) -> None:
            names.update(node.names)

        def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
            names.update(node.names)

    Collector().visit(tree)
    return names


def _loaded_names(tree: ast.AST) -> set[str]:
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)
    return loaded


@pytest.mark.parametrize("relative", WATCHED)
def test_no_undefined_module_names(relative: str):
    path = BACKEND / relative
    if not path.is_file():
        pytest.skip(f"文件不存在：{path}")
    source = io.open(path, encoding="utf-8-sig", errors="replace").read()
    tree = ast.parse(source)

    bound = _bound_names(tree)
    missing = sorted(
        name
        for name in _loaded_names(tree)
        if name not in bound
        and name not in BUILTINS
        # __future__ 的 annotations、dunder、typing 里的字符串前向引用
        and not name.startswith("__")
    )
    assert not missing, (
        f"{relative} 用了未定义/未导入的名字：{missing}。"
        "这类错误 import 阶段不会报，接口被真的调用时才 500。"
    )


def test_insights_imports_the_detail_helpers():
    """点名守一次：这两个名字曾经只被调用、没有被导入。

    用户点「从作者笔记蒸馏风格」→ 拉到详情 → 第 591 行 NameError → 500。
    """
    source = io.open(
        BACKEND / "api" / "platforms" / "xhs" / "insights.py",
        encoding="utf-8",
        errors="replace",
    ).read()
    assert "from backend.app.api.platforms.xhs.pc import (" in source
    header = source[source.find("from backend.app.api.platforms.xhs.pc import (") :][:400]
    assert "_detail_business_error" in header
    assert "_normalize_detail_payload" in header
