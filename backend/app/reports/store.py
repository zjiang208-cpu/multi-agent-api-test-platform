from __future__ import annotations

from pathlib import Path
from threading import RLock

from app.models.reports import ReportSnapshot


_REPORTS: dict[tuple[str, str], dict[str, ReportSnapshot]] = {}
_REPORTS_LOCK = RLock()


class ReportStore:
    """Process-local reports that are cleared when the backend restarts."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root_dir = self.data_dir / "projects" / project_id / "reports"
        self._namespace = (str(self.data_dir), project_id)

    def save(self, report: ReportSnapshot) -> Path:
        with _REPORTS_LOCK:
            reports = _REPORTS.setdefault(self._namespace, {})
            reports[report.report_id] = report.model_copy(deep=True)
        # Compatibility return value only; no file is written.
        return self.root_dir / f"{report.report_id}.memory"

    def get(self, report_id: str) -> ReportSnapshot | None:
        with _REPORTS_LOCK:
            report = _REPORTS.get(self._namespace, {}).get(report_id)
            return report.model_copy(deep=True) if report is not None else None

    def list(self) -> list[ReportSnapshot]:
        with _REPORTS_LOCK:
            reports = _REPORTS.get(self._namespace, {})
            return [report.model_copy(deep=True) for report in reports.values()]
