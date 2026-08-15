from __future__ import annotations

import hashlib
import json

from app.models.requirements import RequirementDocument


def requirement_fingerprint(requirement: RequirementDocument) -> str:
    """Hash semantic requirement content, excluding generated IDs/timestamps."""

    value = {
        "api": requirement.api.model_dump(mode="json", by_alias=True),
        "preconditions": requirement.preconditions,
        "business_rules": requirement.business_rules,
        "expected_behaviors": requirement.expected_behaviors,
        "conflicts": requirement.conflicts,
        "unresolved_questions": requirement.unresolved_questions,
        "evidence_refs": [
            {
                "source_type": item.source_type,
                "reference": item.reference,
                "confidence": item.confidence,
            }
            for item in requirement.evidence_refs
        ],
    }
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

