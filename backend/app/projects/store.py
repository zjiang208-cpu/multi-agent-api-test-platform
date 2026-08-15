from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from app.models.projects import TestProject


class ProjectStore:
    """Small durable Phase 1 store; replaceable by SQLAlchemy later."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.file_path = self.data_dir / "projects.json"
        self._lock = RLock()

    def list(self) -> list[TestProject]:
        with self._lock:
            values = self._read()
        return sorted(values, key=lambda project: project.created_at)

    def get(self, project_id: str) -> TestProject | None:
        return next((item for item in self.list() if item.project_id == project_id), None)

    def save(self, project: TestProject) -> TestProject:
        with self._lock:
            values = self._read()
            replaced = False
            for index, item in enumerate(values):
                if item.project_id == project.project_id:
                    values[index] = project
                    replaced = True
                    break
            if not replaced:
                values.append(project)
            self._write(values)
        return project

    def delete(self, project_id: str) -> bool:
        with self._lock:
            values = self._read()
            remaining = [item for item in values if item.project_id != project_id]
            if len(remaining) == len(values):
                return False
            self._write(remaining)
            return True

    def _read(self) -> list[TestProject]:
        if not self.file_path.exists():
            return []
        with self.file_path.open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
        return [TestProject.model_validate(item) for item in raw]

    def _write(self, projects: list[TestProject]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [project.model_dump(mode="json") for project in projects]
        fd, temp_name = tempfile.mkstemp(
            prefix="projects-", suffix=".json.tmp", dir=self.data_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.file_path)
        finally:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()

