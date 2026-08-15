from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import AppSettings
from app.core.errors import register_exception_handlers
from app.executor.auth import AutomaticAuthProvider
from app.projects.store import ProjectStore


def create_app(
    settings: AppSettings | None = None,
    project_store: ProjectStore | None = None,
) -> FastAPI:
    app_settings = settings or AppSettings()
    store = project_store or ProjectStore(app_settings.data_dir)

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="基于 Multi-Agent 的接口自动化测试平台",
    )
    app.state.settings = app_settings
    app.state.project_store = store
    app.state.auth_provider = AutomaticAuthProvider()
    # Queues remain on disk for audit, but automatic UI recovery is scoped to
    # this backend lifetime. A restart therefore starts with an empty task view.
    app.state.runtime_session_id = f"runtime-{uuid4().hex}"
    app.state.workflow_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="workflow-queue",
    )
    app.include_router(api_router, prefix=app_settings.api_prefix)
    register_exception_handlers(app)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "api-test-platform"}

    @app.on_event("startup")
    async def start_auth_refresh() -> None:
        app.state.auth_provider.start(store)

    @app.on_event("shutdown")
    async def shutdown_workflow_executor() -> None:
        await app.state.auth_provider.stop()
        app.state.workflow_executor.shutdown(wait=False, cancel_futures=False)

    return app


app = create_app()
