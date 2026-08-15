from __future__ import annotations

from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.evidence import EvidenceFact


class OpenApiEvidenceProvider:
    provider_type = "openapi"

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        return "healthy", "selected operation contract is available"

    def retrieve(self, context: EvidenceContext, _: EvidenceQuery) -> list[EvidenceFact]:
        operation = context.operation
        facts = [
            EvidenceFact(
                source_type=self.provider_type,
                reference=f"operation:{operation.operation_id}",
                operation_id=operation.operation_id,
                fact=f"The operation uses HTTP {operation.method} at path {operation.path}.",
                safe_excerpt=operation.summary or None,
            ),
            EvidenceFact(
                source_type=self.provider_type,
                reference=f"operation:{operation.operation_id}:parameters",
                operation_id=operation.operation_id,
                fact=(
                    "Parameters: "
                    + ", ".join(
                        f"{item.location}.{item.name} ({'required' if item.required else 'optional'}, {item.schema_type})"
                        for item in operation.parameters
                    )
                ),
            ),
            EvidenceFact(
                source_type=self.provider_type,
                reference=f"operation:{operation.operation_id}:responses",
                operation_id=operation.operation_id,
                fact=(
                    "Declared response statuses: "
                    + ", ".join(str(item.status_code) for item in operation.responses)
                ),
            ),
        ]
        if operation.request_body is not None:
            facts.append(
                EvidenceFact(
                    source_type=self.provider_type,
                    reference=f"operation:{operation.operation_id}:request-body",
                    operation_id=operation.operation_id,
                    fact="The operation declares a request body contract.",
                )
            )
        return facts

