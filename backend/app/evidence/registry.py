from __future__ import annotations

from app.evidence.protocol import EvidenceContext, EvidenceProvider, EvidenceQuery
from app.models.evidence import EvidenceBundle


class EvidenceRegistry:
    def __init__(self, providers: list[EvidenceProvider]) -> None:
        self.providers = providers

    def collect(self, context: EvidenceContext, query: EvidenceQuery) -> EvidenceBundle:
        facts = []
        statuses: dict[str, str] = {}
        conflicts: list[str] = []
        for provider in self.providers:
            try:
                state, message = provider.health(context)
                statuses[provider.provider_type] = f"{state}: {message}"
                explicitly_enabled_database = (
                    provider.provider_type == "database_schema"
                    and context.settings.database.enabled
                )
                should_retrieve = (
                    provider.provider_type in {"openapi", "operation_yaml", "auth_fixture"}
                    or explicitly_enabled_database
                    or query.include_optional
                )
                if should_retrieve and state == "healthy":
                    facts.extend(provider.retrieve(context, query))
            except Exception as exc:  # provider failures stay visible, never become guesses
                statuses[provider.provider_type] = f"error: {type(exc).__name__}: {exc}"
        if len(facts) > query.max_facts:
            conflicts.append(f"evidence fact limit reached: {query.max_facts}")
            facts = facts[: query.max_facts]
        return EvidenceBundle(
            operation_id=context.operation.operation_id,
            facts=facts,
            provider_status=statuses,
            conflicts=conflicts,
        )
