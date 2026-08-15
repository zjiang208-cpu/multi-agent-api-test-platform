from __future__ import annotations

from fastapi import APIRouter, Request

from app.providers.config import resolve_llm_config

router = APIRouter(tags=["config"])


@router.get("/config/status")
async def config_status(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "environment": settings.environment,
        "optional_providers": {
            "llm": "configured" if resolve_llm_config(settings).complete else "not_configured",
            "source_code": "not_configured",
            "database": "not_configured",
        },
        "execution_policy": {
            "remote_targets_allowed": settings.allow_remote_targets,
            "remote_sources_allowed": settings.allow_remote_sources,
            "credentials_exposed": False,
        },
    }
