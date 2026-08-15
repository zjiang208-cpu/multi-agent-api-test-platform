from __future__ import annotations

from app.models.execution import AssertionResult, ExecutionResult, RunResult
from app.reports.service import ReportService
from app.reports.store import ReportStore


def test_report_snapshot_aggregates_failures_and_traceability(tmp_path):
    run = RunResult(
        run_id="run-1",
        project_id="project-1",
        requirement_id="REQ-1",
        results=[
            ExecutionResult(
                result_id="result-1",
                case_id="CASE-1",
                requirement_id="REQ-1",
                status="passed",
                method="GET",
                url="http://127.0.0.1/items/1",
                assertion_results=[
                    AssertionResult(assertion_id="A-1", passed=True, message="assertion passed")
                ],
            ),
            ExecutionResult(
                result_id="result-2",
                case_id="CASE-2",
                requirement_id="REQ-1",
                status="failed",
                method="GET",
                url="http://127.0.0.1/items/2",
                assertion_results=[
                    AssertionResult(assertion_id="A-2", passed=False, message="assertion failed")
                ],
            ),
        ],
        passed_count=1,
        failed_count=1,
        error_count=0,
    )
    report = ReportService.build(run)
    assert report.status == "mixed"
    assert report.assertion_total == 2
    assert report.assertion_failures == 1
    assert report.failure_case_ids == ["CASE-2"]
    store = ReportStore(tmp_path, "project-1")
    store.save(report)
    assert ReportStore(tmp_path, "project-1").get(report.report_id).run_id == "run-1"
    assert len(ReportStore(tmp_path, "project-1").list()) == 1
    assert not (tmp_path / "projects" / "project-1" / "reports").exists()
