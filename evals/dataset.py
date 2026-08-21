from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from evals.models import EvalDatasetManifest, GroundTruthPoint


def load_manifest(path: Path) -> EvalDatasetManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return EvalDatasetManifest.model_validate(payload)


def scaffold_manifest_from_baseline(
    baseline_path: Path,
    output_path: Path,
    *,
    dataset_id: str = "baseline_v1",
) -> EvalDatasetManifest:
    """Create an annotation-only manifest from a local metrics snapshot.

    The generated file intentionally contains no model output or execution data.
    A human must fill ``points`` and change annotation statuses to ``verified``.
    """

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    api_by_code = {
        item.get("api_code"): item
        for item in payload.get("apis", [])
        if isinstance(item, dict) and item.get("api_code")
    }
    operations: list[dict[str, Any]] = []
    for entry in payload.get("baseline_definition", []):
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        api_code, source_reference = entry
        api = api_by_code.get(api_code, {})
        operations.append(
            {
                "operation_id": api.get("operation_id") or str(api_code),
                "method": api.get("method"),
                "path": api.get("path"),
                "source_reference": source_reference,
                "annotation_status": "pending",
                "points": [],
            }
        )
    manifest = EvalDatasetManifest(
        dataset_id=dataset_id,
        version="1.0.0",
        source=f"local-only:{baseline_path.name}",
        annotation_status="pending",
        operations=operations,
        notes="Generated scaffold. Fill and verify Ground Truth Test Points before scoring.",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return manifest


def enrich_manifest_with_catalog(
    manifest: EvalDatasetManifest,
    catalog_path: Path,
) -> EvalDatasetManifest:
    """Attach document-reviewed candidate points to historical baseline operations."""

    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    catalog_operations = {
        str(item.get("source_reference")): item
        for item in payload.get("operations", [])
        if isinstance(item, dict) and item.get("source_reference")
    }
    for operation in manifest.operations:
        candidate = catalog_operations.get(operation.source_reference or "")
        if candidate is None:
            continue
        operation.points = [GroundTruthPoint.model_validate(point) for point in candidate.get("points", [])]
        operation.annotation_status = "draft"
        operation.notes = candidate.get("notes") or "Candidate points extracted from local requirement catalog."
    manifest.annotation_status = "draft"
    manifest.notes = (
        "Enriched from local requirement catalog. Candidate Ground Truth is draft and requires human confirmation before scoring."
    )
    return manifest
