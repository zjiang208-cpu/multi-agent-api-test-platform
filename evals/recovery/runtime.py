from __future__ import annotations

from typing import Any

from app.models.cases import CaseSet
from app.workflow.models import ReviewerAgentOutput

from evals.recovery.models import RecoveryMutationSpec


def mutate_recovery_cases(cases: CaseSet, mutation: RecoveryMutationSpec) -> CaseSet:
    """Apply a single omission to a private Draft CaseSet without changing it on disk."""

    target = next(
        (case for case in cases.cases if case.case_id == mutation.target_case_id),
        None,
    )
    if target is None:
        raise ValueError(f"case not found in workflow snapshot: {mutation.target_case_id}")
    if mutation.kind == "delete_case":
        remaining = [case for case in cases.cases if case.case_id != target.case_id]
    else:
        raise ValueError(f"unsupported recovery mutation kind: {mutation.kind}")
    return cases.model_copy(deep=True, update={"cases": remaining})


def reviewer_summary(output: ReviewerAgentOutput) -> dict[str, Any]:
    """Keep only structured Reviewer facts needed by the redacted report."""

    suggested_points = [
        point_id
        for spec in output.suggested_case_specs
        for point_id in spec.target_test_point_ids
    ]
    return {
        "missing_test_point_ids": list(output.missing_test_point_ids),
        "invalid_case_ids": list(output.invalid_case_ids),
        "duplicate_case_ids": list(output.duplicate_case_ids),
        "unsupported_assertion_ids": list(output.unsupported_assertion_ids),
        "semantic_gaps": list(output.semantic_gaps),
        "remaining_gaps": list(output.remaining_gaps),
        "suggested_test_point_ids": list(dict.fromkeys(suggested_points)),
        "suggested_case_count": len(output.suggested_case_specs),
    }
