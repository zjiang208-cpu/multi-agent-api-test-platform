from __future__ import annotations

from datetime import datetime, timezone

from app.core.errors import ResourceConflictError, ResourceNotFoundError
from app.models.projects import TestProject, TestProjectCreate, TestProjectUpdate
from app.projects.store import ProjectStore


class ProjectService:
    def __init__(self, store: ProjectStore, max_projects: int = 100) -> None:
        self.store = store
        self.max_projects = max_projects

    def list(self) -> list[TestProject]:
        return self.store.list()

    def get(self, project_id: str) -> TestProject:
        project = self.store.get(project_id)
        if project is None:
            raise ResourceNotFoundError(f"project not found: {project_id}")
        return project

    def create(self, request: TestProjectCreate) -> TestProject:
        if len(self.store.list()) >= self.max_projects:
            raise ResourceConflictError("project limit reached")
        if any(item.name.casefold() == request.name.casefold() for item in self.store.list()):
            raise ResourceConflictError(f"project name already exists: {request.name}")
        return self.store.save(TestProject.new(request))

    def update(self, project_id: str, request: TestProjectUpdate) -> TestProject:
        current = self.get(project_id)
        if request.name is not None:
            for item in self.store.list():
                if item.project_id != project_id and item.name.casefold() == request.name.casefold():
                    raise ResourceConflictError(f"project name already exists: {request.name}")
        updated = current.model_copy(
            update={
                key: value
                for key, value in {
                    "name": request.name,
                    "description": request.description,
                    "settings": request.settings,
                    "updated_at": datetime.now(timezone.utc),
                }.items()
                if value is not None
            }
        )
        return self.store.save(updated)

    def delete(self, project_id: str) -> None:
        if not self.store.delete(project_id):
            raise ResourceNotFoundError(f"project not found: {project_id}")

