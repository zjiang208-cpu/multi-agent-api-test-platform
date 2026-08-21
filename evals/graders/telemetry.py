from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from evals.graders.common import ratio
from evals.models import TelemetryRecord


CALL_KEY = re.compile(r"^llm_(?P<stage>[a-zA-Z0-9]+)_call_(?P<index>\d+)_(?P<field>.+)$")
CALL_FIELDS = {
    "attempt",
    "duration_ms",
    "status",
    "mode",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "error_category",
}
STAGE_DURATION_KEY = re.compile(r"^llm_(?P<stage>[a-zA-Z0-9]+)_duration_ms$")


def telemetry_from_metadata(metadata: dict[str, Any]) -> list[TelemetryRecord]:
    grouped: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    stage_duration_ms: dict[str, int] = {}
    for key, value in metadata.items():
        normalized_key = str(key)
        stage_match = STAGE_DURATION_KEY.match(normalized_key)
        if stage_match:
            stage_duration_ms[stage_match.group("stage")] = _int(value, 0)
            continue
        match = CALL_KEY.match(normalized_key)
        if not match or match.group("field") not in CALL_FIELDS:
            continue
        stage = match.group("stage")
        index = int(match.group("index"))
        field = match.group("field")
        grouped[(stage, index)][field] = value
    records: list[TelemetryRecord] = []
    for (stage, index), fields in sorted(grouped.items()):
        parsed: dict[str, Any] = {
            "stage": stage,
            "attempt": _int(fields.get("attempt"), index),
            "duration_ms": _int(fields.get("duration_ms"), 0),
            "stage_duration_ms": stage_duration_ms.get(stage),
            "status": str(fields.get("status") or "unknown"),
            "mode": str(fields.get("mode") or "generate"),
        }
        for field in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
            parsed[field] = _optional_int(fields.get(field))
        parsed["error_category"] = fields.get("error_category")
        records.append(TelemetryRecord.model_validate(parsed))
    return records


def aggregate_telemetry(records: list[TelemetryRecord]) -> dict[str, Any]:
    if not records:
        return {
            "status": "pending_input",
            "reason": "no telemetry records supplied",
            "by_stage": {},
        }
    by_stage: dict[str, list[TelemetryRecord]] = defaultdict(list)
    for record in records:
        by_stage[record.stage].append(record)
    stages: dict[str, Any] = {}
    for stage, stage_records in sorted(by_stage.items()):
        repair_attempts = [record for record in stage_records if record.mode == "repair"]
        retries = [record for record in stage_records if record.attempt > 1 or record.mode != "generate"]
        first = min(stage_records, key=lambda record: record.attempt)
        token_fields = {
            field: _sum_optional(getattr(record, field) for record in stage_records)
            for field in ("prompt_tokens", "completion_tokens", "reasoning_tokens")
        }
        reported_duration = max(
            (record.stage_duration_ms or 0 for record in stage_records),
            default=0,
        )
        duration_ms = reported_duration or sum(record.duration_ms for record in stage_records)
        stages[stage] = {
            "calls": len(stage_records),
            "duration_ms": duration_ms,
            "duration_scope": "stage_total" if reported_duration else "call_sum",
            "avg_duration_ms": round(duration_ms / len(stage_records), 2),
            "retry_calls": len(retries),
            "repair_attempts": len(repair_attempts),
            "repair_successes": sum(record.status == "success" for record in repair_attempts),
            "first_pass_success": first.status == "success" and first.mode == "generate",
            "prompt_tokens": token_fields["prompt_tokens"],
            "completion_tokens": token_fields["completion_tokens"],
            "reasoning_tokens": token_fields["reasoning_tokens"],
            "repair_trigger_rate": ratio(len(repair_attempts), len(stage_records)),
            "repair_success_rate": ratio(len([record for record in repair_attempts if record.status == "success"]), len(repair_attempts)),
        }
    all_repairs = [record for record in records if record.mode == "repair"]
    first_pass = [
        min(stage_records, key=lambda record: record.attempt)
        for stage_records in by_stage.values()
    ]
    total_reported_duration = sum(
        stage.get("duration_ms", 0)
        for stage in stages.values()
        if stage.get("duration_scope") == "stage_total"
    )
    total_call_duration = sum(
        stage.get("duration_ms", 0)
        for stage in stages.values()
        if stage.get("duration_scope") == "call_sum"
    )
    return {
        "status": "ready",
        "calls": len(records),
        "duration_ms": total_reported_duration + total_call_duration,
        "duration_scope": "stage_total" if total_reported_duration else "call_sum",
        "retry_calls": sum(record.attempt > 1 or record.mode != "generate" for record in records),
        "repair_attempts": len(all_repairs),
        "first_pass_success_rate": ratio(
            sum(record.status == "success" and record.mode == "generate" for record in first_pass),
            len(first_pass),
        ),
        "repair_trigger_rate": ratio(len(all_repairs), len(records)),
        "repair_success_rate": ratio(
            sum(record.status == "success" for record in all_repairs),
            len(all_repairs),
        ),
        "prompt_tokens": _sum_optional(record.prompt_tokens for record in records),
        "completion_tokens": _sum_optional(record.completion_tokens for record in records),
        "reasoning_tokens": _sum_optional(record.reasoning_tokens for record in records),
        "by_stage": stages,
    }


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sum_optional(values) -> int | None:
    parsed = [value for value in values if value is not None]
    return sum(parsed) if parsed else None
