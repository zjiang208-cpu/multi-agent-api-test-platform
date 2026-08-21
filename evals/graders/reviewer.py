from __future__ import annotations

from typing import Any

from evals.graders.common import ratio
from evals.models import EvalSample, GeneratedReviewerOutput


REVIEWER_FINDING_FIELDS = (
    "missing_test_point_ids",
    "invalid_case_ids",
    "duplicate_case_ids",
    "unsupported_assertion_ids",
    "semantic_gaps",
    "remaining_gaps",
)


def _finding_counts(reviewer: GeneratedReviewerOutput) -> dict[str, int]:
    return {
        field: len(getattr(reviewer, field, []))
        for field in REVIEWER_FINDING_FIELDS
    }


def grade_reviewer(
    sample: EvalSample,
    baseline_output: GeneratedReviewerOutput | None = None,
) -> dict[str, Any]:
    reviewer = sample.reviewer_output
    if reviewer is None:
        return {
            "status": "pending_input",
            "reason": "reviewer_output is missing",
            "gap_recall": ratio(0, 0),
            "gap_precision": ratio(0, 0),
            "false_positive_rate": ratio(0, 0),
        }
    mutation = sample.mutation
    actual = [str(item) for item in getattr(reviewer, mutation.reviewer_field, [])] if mutation else []
    baseline = (
        [str(item) for item in getattr(baseline_output, mutation.reviewer_field, [])]
        if mutation and baseline_output is not None
        else []
    )
    net_actual = set(actual) - set(baseline)
    expected = set(mutation.target_ids) if mutation else set()
    detected = net_actual & expected
    extras = net_actual - expected
    if mutation is None:
        finding_counts = _finding_counts(reviewer)
        return {
            "status": "pending_input",
            "reason": "reviewer mutation is required for gap recall/precision",
            "finding_counts": finding_counts,
            "finding_count_total": sum(finding_counts.values()),
        }
    return {
        "mutation_id": mutation.mutation_id,
        "mutation_kind": mutation.kind,
        "reviewer_field": mutation.reviewer_field,
        "target_match": mutation.target_match,
        "expected_targets": sorted(expected),
        "detected_targets": sorted(detected),
        "baseline_findings": sorted(set(baseline)),
        "extra_findings": sorted(extras),
        "gap_recall": (
            ratio(1 if detected else 0, 1)
            if mutation.target_match == "any"
            else ratio(len(detected), len(expected))
        ),
        "gap_precision": ratio(len(detected), len(net_actual)),
        "false_positive_rate": ratio(len(extras), len(net_actual)),
    }


def aggregate_reviewer_suite(sample_reports: list[dict[str, Any]]) -> dict[str, Any]:
    mutations = [
        sample["reviewer"]
        for sample in sample_reports
        if sample.get("variant") == "reviewer_mutation"
        and isinstance(sample.get("reviewer"), dict)
        and sample["reviewer"].get("mutation_id")
    ]
    if not mutations:
        return {"status": "pending_input", "reason": "no reviewer mutation samples"}
    detected_mutations = [
        item for item in mutations if item.get("gap_recall", {}).get("value") == 1.0
    ]
    detected_targets = sum(len(item.get("detected_targets", [])) for item in mutations)
    extra_findings = sum(len(item.get("extra_findings", [])) for item in mutations)
    net_findings = detected_targets + extra_findings
    return {
        "status": "ready",
        "mutation_count": len(mutations),
        "detected_mutations": len(detected_mutations),
        "missed_mutation_ids": [
            item["mutation_id"] for item in mutations if item not in detected_mutations
        ],
        "defect_recall": ratio(len(detected_mutations), len(mutations)),
        "gap_precision_micro": ratio(detected_targets, net_findings),
        "false_positive_rate_micro": ratio(extra_findings, net_findings),
    }
