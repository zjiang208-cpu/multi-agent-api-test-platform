from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ArtifactError(ValueError):
    pass


class YamlArtifactStore:
    """Validated YAML artifacts kept below one configured root."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()

    def path_for(self, kind: str, artifact_id: str) -> Path:
        self._validate_segment(kind, "artifact kind")
        self._validate_segment(artifact_id, "artifact id")
        path = (self.root_dir / kind / f"{artifact_id}.yaml").resolve()
        if self.root_dir not in path.parents:
            raise ArtifactError("artifact path escapes configured root")
        return path

    def save(self, kind: str, artifact_id: str, model: T) -> Path:
        path = self.path_for(kind, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f"{artifact_id}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with open(fd, "w", encoding="utf-8", newline="\n", closefd=True) as stream:
                yaml.safe_dump(
                    model.model_dump(mode="json", by_alias=True),
                    stream,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return path

    def load(self, kind: str, artifact_id: str, model_type: type[T]) -> T:
        path = self.path_for(kind, artifact_id)
        if not path.is_file():
            raise ArtifactError(f"artifact not found: {kind}/{artifact_id}")
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        if not isinstance(raw, dict):
            raise ArtifactError("artifact root must be a YAML mapping")
        return model_type.model_validate(raw)

    @staticmethod
    def _validate_segment(value: str, label: str) -> None:
        if not value or not SAFE_ID.fullmatch(value):
            raise ArtifactError(f"invalid {label}")
