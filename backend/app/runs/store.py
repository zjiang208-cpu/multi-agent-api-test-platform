from __future__ import annotations

from pathlib import Path
from threading import RLock

from app.models.execution import RunResult


_RUNS: dict[tuple[str, str], dict[str, RunResult]] = {}
_RUNS_LOCK = RLock()


class RunStore:
    """Process-local execution results cleared when the backend restarts."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root_dir = self.data_dir / "projects" / project_id / "runs"
        self._namespace = (str(self.data_dir), project_id)

    def save(self, run: RunResult) -> Path:
        with _RUNS_LOCK:
            runs = _RUNS.setdefault(self._namespace, {})
            runs[run.run_id] = run.model_copy(deep=True)
        # Compatibility return value only; no file is written.
        return self.root_dir / f"{run.run_id}.memory"

    def get(self, run_id: str) -> RunResult | None:
        with _RUNS_LOCK:
            run = _RUNS.get(self._namespace, {}).get(run_id)
            return run.model_copy(deep=True) if run is not None else None
