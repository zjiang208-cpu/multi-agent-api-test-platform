from __future__ import annotations

from uuid import uuid4

from app.models.execution import RunResult
from app.models.reports import ReportSnapshot


class ReportService:
    @staticmethod
    def build(run: RunResult) -> ReportSnapshot:
        total_assertions = sum(len(item.assertion_results) for item in run.results)
        failed_assertions = sum(
            sum(not assertion.passed for assertion in item.assertion_results)
            for item in run.results
        )
        statuses = {item.status for item in run.results}
        if not statuses or statuses == {"passed"}:
            status = "passed"
        elif statuses == {"failed"}:
            status = "failed"
        elif statuses == {"error"}:
            status = "error"
        else:
            status = "mixed"
        return ReportSnapshot(
            report_id=f"report-{uuid4().hex}",
            run_id=run.run_id,
            project_id=run.project_id,
            requirement_id=run.requirement_id,
            queue_run_id=run.queue_run_id,
            status=status,
            total_cases=len(run.results),
            passed_cases=run.passed_count,
            failed_cases=run.failed_count,
            error_cases=run.error_count,
            assertion_total=total_assertions,
            assertion_failures=failed_assertions,
            traceability={
                "cases": len(run.results),
                "execution_results": len(run.results),
                "assertions": total_assertions,
            },
            failure_case_ids=[item.case_id for item in run.results if item.status != "passed"],
            by_api=ReportService._by_api(run),
        )

    @staticmethod
    def _by_api(run: RunResult) -> dict[str, dict[str, int]]:
        grouped: dict[str, dict[str, int]] = {}
        for result in run.results:
            key = result.api_operation_id or result.requirement_id
            summary = grouped.setdefault(key, {"total": 0, "passed": 0, "failed": 0, "error": 0})
            summary["total"] += 1
            if result.status == "passed":
                summary["passed"] += 1
            elif result.status == "failed":
                summary["failed"] += 1
            elif result.status == "error":
                summary["error"] += 1
        return grouped
