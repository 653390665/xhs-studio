from __future__ import annotations

import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api import accounts, account_positioning, agent, ai, auth, auto_tasks, capture_tokens, corpus, distill_batches, drafts, evidence_distill, files, keyword_groups, login_sessions, matrix, model_configs, notes, notifications, publish, risk_controls, scheduler_settings, search_gateway, skill_library, skills, styles, system, tags, tasks, topics
from backend.app.api.platforms import registry
from backend.app.api.platforms.douyin import capture as douyin_capture
from backend.app.api.platforms.douyin import extract as douyin_extract
from backend.app.api.platforms.xhs import analytics, crawl, creator, insights, monitoring, pc, tools, trends
from backend.app.adapters.xhs.pc_api_adapter import XhsAuthExpired
from backend.app.core.config import get_settings
from backend.app.core.database import SessionLocal, get_db, init_db
from backend.app.core.security import decode_token
from backend.app.models import ApiLog
from backend.app.core.error_messages import translate_detail, translate_validation_item
from backend.app.services.scheduler_service import run_due_auto_tasks, shutdown_due_publish_scheduler, start_due_publish_scheduler

import logging

logger = logging.getLogger("backend.app.main")

_INSECURE_SECRET_KEYS = {"", "dev-only-change-me", "CHANGE_ME_VIA_ENV_VAR"}

# 写稿宿主已经整体退场。开发服务器由 Vite 插件显式返回 410；
# 打包版的 SPA fallback 也必须先拦住 /harness，否则旧书签会拿到
# index.html，看起来“还活着”，正是本项目一直在清理的静默降级。
RETIRED_HARNESS_MESSAGE = (
    "写稿宿主（DeepSeek Harness）已下线。\n"
    "写稿请到 /write；旧页面不会回退，也不会假装还能用。"
)


def _is_retired_harness_path(path: str) -> bool:
    return path == "/harness" or path.startswith("/harness/")


def _validate_secret_key(settings) -> None:
    """Refuse to start with a public or trivially short JWT signing key."""
    key = (settings.secret_key or "").strip()
    if key in _INSECURE_SECRET_KEYS or len(key) < 32:
        raise RuntimeError(
            "SECRET_KEY 未配置、仍是公开占位符或长度不足 32 字符。"
            "源码/安装包入口会自动生成持久密钥；直接运行 ASGI 时请先在 "
            ".env 或部署环境设置 SECRET_KEY。"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_secret_key(get_settings())
    init_db()
    _mark_stale_agent_runs()
    settings = get_settings()
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = start_due_publish_scheduler(settings.scheduler_interval_seconds)
        started_jobs = [job.id for job in scheduler.get_jobs()]
        logger.info(
            "调度器已启动（每 %s 秒检查一次）：%s。到期任务是真发，不是演练。",
            settings.scheduler_interval_seconds,
            "、".join(started_jobs),
        )
    else:
        # Silence here is what let the calendar say 「届时自动发布」while nothing
        # was running. Say it once, loudly, at the only moment an operator looks.
        logger.warning(
            "调度器未启用（SCHEDULER_ENABLED=false）：排期任务不会自动发布，"
            "到点后需要手动点「发布」。要开启自动发布，在 .env 设置 "
            "SCHEDULER_ENABLED=true 并重启。"
        )
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        shutdown_due_publish_scheduler(scheduler)


def _mark_stale_agent_runs() -> None:
    """A run left in 'running' after a restart has no worker anymore."""
    from sqlalchemy import update

    from backend.app.core.database import SessionLocal
    from backend.app.models import AgentRun

    db = SessionLocal()
    try:
        db.execute(
            update(AgentRun)
            .where(AgentRun.status == "running")
            .values(status="failed", error="服务重启，运行已中断")
        )
        db.commit()
    finally:
        db.close()


def _validated_cors_origins(raw: str) -> list[str]:
    origins = [origin.strip() for origin in (raw or "").split(",") if origin.strip()]
    if "*" in origins:
        raise RuntimeError(
            "backend_cors_origins 不能包含 '*'：allow_credentials=True 时浏览器会拒绝该组合"
        )
    return origins


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, lifespan=lifespan)

    origins = _validated_cors_origins(settings.backend_cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _record_api_error(request, call_next):
        """Persist failed API calls so the diagnostics panel has evidence.

        Only failures are written. Request bodies are never stored: the
        diagnostics view must not become a second copy of drafts or cookies.
        """
        started = time.perf_counter()
        response = await call_next(request)
        if (
            request.url.path.startswith("/api/")
            and response.status_code >= 400
            and request.app.dependency_overrides.get(get_db) is None
        ):
            try:
                user_id = None
                authorization = request.headers.get("authorization", "")
                if authorization.lower().startswith("bearer "):
                    try:
                        token_payload = decode_token(authorization.split(" ", 1)[1])
                        raw_user_id = token_payload.get("user_id")
                        user_id = int(raw_user_id) if raw_user_id is not None else None
                    except Exception:  # noqa: BLE001 - invalid/expired token is still just a log
                        user_id = None
                path = request.url.path
                platform = "xhs" if "/xhs/" in path else "douyin" if "/douyin/" in path else None
                db = SessionLocal()
                try:
                    db.add(
                        ApiLog(
                            user_id=user_id,
                            platform=platform,
                            endpoint=path,
                            status="error" if response.status_code >= 500 else "warning",
                            meta={
                                "method": request.method,
                                "status_code": response.status_code,
                                "duration_ms": round((time.perf_counter() - started) * 1000),
                            },
                        )
                    )
                    db.commit()
                finally:
                    db.close()
            except Exception:  # noqa: BLE001 - observability must never break the request
                logger.warning("failed to record API error", exc_info=True)
        return response

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "xhs-studio"}

    @app.exception_handler(XhsAuthExpired)
    async def _xhs_auth_expired_handler(_request, exc: XhsAuthExpired):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_request, exc: StarletteHTTPException):
        """Keep error copy Chinese across every endpoint and client."""
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": translate_detail(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_request, exc: RequestValidationError):
        from fastapi.responses import JSONResponse

        detail = [translate_validation_item(item) for item in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": detail}),
        )

    app.include_router(registry.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(login_sessions.router, prefix="/api")
    app.include_router(notes.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(drafts.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(model_configs.router, prefix="/api")
    app.include_router(search_gateway.router, prefix="/api")
    app.include_router(tags.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.include_router(keyword_groups.router, prefix="/api")
    app.include_router(publish.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(pc.router, prefix="/api")
    app.include_router(creator.router, prefix="/api")
    app.include_router(crawl.router, prefix="/api")
    app.include_router(monitoring.router, prefix="/api")
    app.include_router(insights.router, prefix="/api")
    app.include_router(trends.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(douyin_extract.router, prefix="/api")
    app.include_router(douyin_capture.router, prefix="/api")
    app.include_router(capture_tokens.router, prefix="/api")
    app.include_router(auto_tasks.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(skills.router, prefix="/api")
    app.include_router(account_positioning.router, prefix="/api")
    app.include_router(corpus.router, prefix="/api")
    app.include_router(distill_batches.router, prefix="/api")
    app.include_router(evidence_distill.router, prefix="/api")
    app.include_router(skill_library.router, prefix="/api")
    app.include_router(styles.router, prefix="/api")
    app.include_router(topics.router, prefix="/api")
    app.include_router(risk_controls.router, prefix="/api")
    app.include_router(matrix.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(scheduler_settings.router, prefix="/api")

    # Serve pre-built frontend in production / Docker
    if settings.frontend_serve_static:
        frontend_dist = Path(settings.frontend_build_dir)
        if frontend_dist.is_dir():
            from starlette.responses import FileResponse, PlainTextResponse

            # Serve index.html for SPA client-side routing (non-API, non-file paths)
            @app.middleware("http")
            async def _spa_fallback(request, call_next):
                path = request.url.path
                if _is_retired_harness_path(path):
                    return PlainTextResponse(
                        RETIRED_HARNESS_MESSAGE,
                        status_code=410,
                        headers={"Cache-Control": "no-store"},
                    )
                response = await call_next(request)
                if (
                    response.status_code == 404
                    and not path.startswith("/api")
                    and "." not in path.split("/")[-1]
                ):
                    return FileResponse(str(frontend_dist / "index.html"))
                return response

            app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
