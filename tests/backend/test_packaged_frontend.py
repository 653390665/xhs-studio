"""打包版必须能自己把界面跑起来。

这一组测试守的是三件在打包版上才会暴露的事，开发模式（5173 + 8000）永远撞不到：

1. **后端地址不能用绝对地址**。安装器启动时端口由 `pick_port` 选，
   8000 被占用就换 8001/8002。写死 `http://127.0.0.1:8000` 的结果是
   「界面能打开，每个请求都失败」，而错误看起来像后端挂了。
   构建产物的 `API_BASE` 必须是空串（同源）。

2. **前端静态文件要真的被打进载荷**。`FRONTEND_SERVE_STATIC=true` 但
   `frontend/dist` 没进包，结果是打开一片白页——比报错更难查。

3. **SPA 深链接要回 index.html**。打包版没有 Vite 的 fallback，
   `/write/capabilities` 直接刷新必须还是页面，不是 404。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO / "frontend" / "dist"


def test_bundle_has_no_hardcoded_backend_port():
    """构建产物里不能出现写死的开发端口。

    搜索的是打包后的 JS。开发模式允许出现（那时确实需要一个绝对地址），
    但 `frontend/dist` 是给安装器用的，里面出现它就说明构建时忘了区分环境。
    """
    if not FRONTEND_DIST.is_dir():
        pytest.skip("frontend/dist 还没构建")

    js_files = list((FRONTEND_DIST / "assets").glob("*.js"))
    assert js_files, "frontend/dist/assets 里没有 JS，构建产物不完整"

    offenders = []
    for path in js_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "127.0.0.1:8000" in text:
            offenders.append(path.name)
    assert not offenders, (
        "打包产物里出现了写死的 127.0.0.1:8000："
        f"{offenders}。端口由 pick_port 动态选，写死会让打包版每个请求都失败。"
    )


def test_bundle_contains_the_new_frontend():
    """构建产物必须是新前端（5 入口那套），不是老前端的 antd 页面。"""
    if not FRONTEND_DIST.is_dir():
        pytest.skip("frontend/dist 还没构建")

    js_files = list((FRONTEND_DIST / "assets").glob("*.js"))
    assert js_files

    text = "".join(
        path.read_text(encoding="utf-8", errors="replace") for path in js_files
    )
    # 新前端独有：三个板块名是这一轮定的 IA
    for label in ("提炼批次", "写法与能力", "样本库"):
        assert label in text, f"构建产物里找不到「{label}」，可能装的是老前端"
    # 老前端的标志性依赖
    assert "ant-design" not in text, "构建产物里有 antd，装错了前端"


def test_index_html_points_at_the_built_bundle():
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        pytest.skip("frontend/dist 还没构建")
    html = index.read_text(encoding="utf-8")
    assert "/assets/" in html, "index.html 没有引用构建后的 bundle"
    # 开发模式会引用 /src/main.tsx；打包版不该有
    assert "/src/main.tsx" not in html, "index.html 还指向开发入口，装的是未构建的源码"


def test_spa_fallback_serves_deep_links():
    """深链接返回 index.html，而不是 404。

    用一个最小的 FastAPI app 复现 `main.py` 的挂载方式，
    不启动真后端（那需要数据库和完整配置）。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.responses import FileResponse, PlainTextResponse

    from backend.app.main import (
        RETIRED_HARNESS_MESSAGE,
        _is_retired_harness_path,
    )

    if not (FRONTEND_DIST / "index.html").is_file():
        pytest.skip("frontend/dist 还没构建")

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.middleware("http")
    async def spa_fallback(request, call_next):
        path = request.url.path
        if _is_retired_harness_path(path):
            return PlainTextResponse(RETIRED_HARNESS_MESSAGE, status_code=410)
        response = await call_next(request)
        if (
            response.status_code == 404
            and not path.startswith("/api")
            and "." not in path.split("/")[-1]
        ):
            return FileResponse(str(FRONTEND_DIST / "index.html"))
        return response

    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    client = TestClient(app)

    # 深链接：三个新 IA 的路径各测一条
    for path in ("/write", "/write/capabilities", "/assets/library"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} 返回 {response.status_code}"
        assert "<div id=\"root\">" in response.text, f"{path} 没有返回 SPA 骨架"

    # API 不能被 fallback 吃掉
    assert client.get("/api/health").json() == {"status": "ok"}

    # 已下线的写稿宿主不能伪装成 SPA 页面
    for path in ("/harness", "/harness/", "/harness/project-bridge.mjs"):
        response = client.get(path)
        assert response.status_code == 410, f"{path} 返回 {response.status_code}"
        assert "已下线" in response.text

    # 静态资源要真的能读到
    asset = next((FRONTEND_DIST / "assets").glob("*.js"))
    response = client.get(f"/assets/{asset.name}")
    assert response.status_code == 200
    assert len(response.content) > 1000
