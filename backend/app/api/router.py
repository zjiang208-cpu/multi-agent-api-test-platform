from fastapi import APIRouter

from app.api.routes.config import router as config_router
from app.api.routes.cases import router as cases_router
from app.api.routes.documents import project_router as project_documents_router
from app.api.routes.documents import router as documents_router
from app.api.routes.operations import router as operations_router
from app.api.routes.queues import router as queues_router
from app.api.routes.projects import router as projects_router
from app.api.routes.requirements import router as requirements_router
from app.api.routes.reports import router as reports_router
from app.api.routes.runs import router as runs_router
from app.api.routes.testpoints import router as testpoints_router
from app.api.routes.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(config_router)
api_router.include_router(cases_router)
api_router.include_router(documents_router)
api_router.include_router(project_documents_router)
api_router.include_router(projects_router)
api_router.include_router(operations_router)
api_router.include_router(queues_router)
api_router.include_router(requirements_router)
api_router.include_router(reports_router)
api_router.include_router(runs_router)
api_router.include_router(testpoints_router)
api_router.include_router(workflows_router)
