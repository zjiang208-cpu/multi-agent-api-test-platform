from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from evals.recovery.models import RecoveryEvalSample


def canonical_operation_id(operation_id: str, aliases: Mapping[str, str] | None = None) -> str:
    """Resolve an explicitly configured observed operation ID to its canonical ID."""

    aliases = aliases or {}
    current = str(operation_id)
    visited: set[str] = set()
    while current in aliases:
        if current in visited:
            raise ValueError(f"operation ID alias cycle detected at {current}")
        visited.add(current)
        current = str(aliases[current])
    return current


def operation_id_candidates(
    canonical_id: str,
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    """Return the canonical ID and explicit observed aliases accepted for it."""

    aliases = aliases or {}
    candidates = {str(canonical_id)}
    for observed_id in aliases:
        if canonical_operation_id(observed_id, aliases) == canonical_id:
            candidates.add(str(observed_id))
    return sorted(candidates)


def validate_recovery_suite(
    samples: list[RecoveryEvalSample],
    expected_operation_ids: set[str],
    *,
    operation_id_aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate suite completeness before calculating Recovery metrics."""

    aliases = {str(key): str(value) for key, value in (operation_id_aliases or {}).items()}
    issues: list[dict[str, Any]] = []
    by_operation: dict[str, list[RecoveryEvalSample]] = defaultdict(list)
    sample_ids: set[str] = set()
    mutation_ids: set[str] = set()

    for sample in samples:
        if sample.sample_id in sample_ids:
            issues.append({"type": "duplicate_sample_id", "sample_id": sample.sample_id})
        sample_ids.add(sample.sample_id)
        try:
            canonical_id = canonical_operation_id(sample.operation_id, aliases)
        except ValueError as exc:
            issues.append(
                {
                    "type": "invalid_operation_id_alias",
                    "sample_id": sample.sample_id,
                    "message": str(exc),
                }
            )
            continue
        by_operation[canonical_id].append(sample)
        if sample.mutation is not None:
            mutation_id = sample.mutation.mutation_id
            if mutation_id in mutation_ids:
                issues.append({"type": "duplicate_mutation_id", "mutation_id": mutation_id})
            mutation_ids.add(mutation_id)

    expected = {str(item) for item in expected_operation_ids}
    observed = set(by_operation)
    for operation_id in sorted(observed - expected):
        issues.append({"type": "unexpected_operation_id", "operation_id": operation_id})
    for operation_id in sorted(expected - observed):
        issues.append({"type": "missing_operation_id", "operation_id": operation_id})

    for operation_id in sorted(expected & observed):
        operation_samples = by_operation[operation_id]
        controls = [sample for sample in operation_samples if sample.mutation is None]
        mutations = [sample for sample in operation_samples if sample.mutation is not None]
        if len(controls) != 1:
            issues.append(
                {
                    "type": "control_count_invalid",
                    "operation_id": operation_id,
                    "count": len(controls),
                    "expected": 1,
                }
            )
        if not mutations:
            issues.append({"type": "mutation_missing", "operation_id": operation_id})

    return {
        "status": "ready" if not issues else "pending_input",
        "issues": issues,
        "expected_operation_ids": sorted(expected),
        "observed_operation_ids": sorted(observed),
        "operation_id_aliases": aliases,
        "alias_resolutions": {
            sample.operation_id: canonical_operation_id(sample.operation_id, aliases)
            for sample in samples
            if sample.operation_id in aliases
        },
    }
