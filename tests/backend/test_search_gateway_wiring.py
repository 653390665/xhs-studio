"""前端接线：找资料必须读「检索网关」的配置，而不是默认文本模型。

为什么守这一条
--------------
`/api/search/gateway` 是新接口，前端如果忘了接，界面会一直显示
「还没配搜索源」或者反过来永远可用——两种都会把人带沟里。
这套仓库的 `test_frontend_wiring.py` 已有同类做法（读源码断言关键调用），
这里沿用，不引浏览器跑端到端。
"""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _read(rel: str) -> str:
    path = FRONTEND / rel
    assert path.is_file(), f"缺少前端文件 {rel}"
    return path.read_text(encoding="utf-8")


def test_search_page_reads_the_gateway_endpoint():
    """Search 页的「没配搜索源」必须来自检索网关，不能是模型状态。"""
    src = _read("pages/Search.tsx")
    assert "/api/search/gateway" in src, (
        "Search.tsx 没读 /api/search/gateway：界面会按「模型配没配」来提示，"
        "默认模型只做 chat 时永远显示可用，点搜索才 404"
    )
    # 只看真实调用，注释里提到不算
    assert "writerBootstrap(" not in src and "import { writerBootstrap }" not in src, (
        "Search.tsx 还在用 writerBootstrap 判断检索可用性，这两件事不是一回事"
    )


def test_search_setup_can_save_and_clear_the_gateway():
    src = _read("components/SearchSetup.tsx")
    assert "/api/search/gateway" in src
    assert "put<" in src, "SearchSetup 必须能保存（PUT /api/search/gateway）"
    assert "search_model_name" in src or "model_name" in src


def test_notice_points_at_the_search_subsection():
    """提示里要指出「找资料用的检索」，否则用户会去改默认模型。"""
    src = _read("pages/Search.tsx")
    assert "找资料用的检索" in src, (
        "提示文案没指向「设置 → 模型 → 找资料用的检索」，用户会去重配默认模型"
    )
