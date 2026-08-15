from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ResourceNotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ResourceConflictError(DomainError):
    status_code = 409
    code = "conflict"


class HumanGateRequiredError(DomainError):
    status_code = 409
    code = "human_gate_required"


class WorkflowRunError(DomainError):
    """A design workflow failed after it was accepted for execution."""

    status_code = 502
    code = "workflow_failed"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
