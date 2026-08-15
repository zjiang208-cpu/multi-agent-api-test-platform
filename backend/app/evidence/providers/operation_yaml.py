from __future__ import annotations

from app.core.security import sanitize_text
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.evidence import EvidenceFact


class OperationYamlEvidenceProvider:
    provider_type = "operation_yaml"

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        if not context.operation.contract_metadata:
            return "not_configured", "selected operation has no YAML metadata"
        refs = [ref.reference or "" for ref in context.operation.source_refs]
        if not any(ref.lower().endswith((".yaml", ".yml")) for ref in refs):
            return "not_configured", "selected operation is not sourced from an operation YAML contract"
        return "healthy", "operation YAML contract metadata is available"

    def retrieve(self, context: EvidenceContext, _: EvidenceQuery) -> list[EvidenceFact]:
        metadata = context.operation.contract_metadata
        source = next(
            (ref.reference for ref in context.operation.source_refs if (ref.reference or "").lower().endswith((".yaml", ".yml"))),
            f"operation:{context.operation.operation_id}",
        )
        facts: list[EvidenceFact] = []
        for key, label in (
            ("preconditions", "Preconditions"),
            ("business_rules", "Business rules"),
            ("expected_behaviors", "Expected behaviors"),
            ("scenarios", "Response scenarios"),
        ):
            values = metadata.get(key, [])
            if not values:
                continue
            text = sanitize_text("; ".join(str(value) for value in values), max_length=4000)
            facts.append(
                EvidenceFact(
                    source_type=self.provider_type,
                    reference=f"yaml:{source}:{key}",
                    operation_id=context.operation.operation_id,
                    fact=f"{label} declared by the selected operation YAML contract.",
                    safe_excerpt=text[:4000],
                    metadata={"source": source, "field": key},
                )
            )
        return facts
