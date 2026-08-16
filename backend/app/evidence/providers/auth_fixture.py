from __future__ import annotations

from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.evidence import EvidenceFact
from app.providers.llm import SecretReferenceError, resolve_secret_reference


class AuthFixtureEvidenceProvider:
    """Expose safe authentication-negative placeholders without real secrets."""

    provider_type = "auth_fixture"

    def health(self, context: EvidenceContext) -> tuple[str, str]:
        settings = context.settings
        auth_configured = bool(
            settings.auth_provider.enabled
            or settings.sut_target.auth_ref
            or context.operation.contract_metadata.get("auth_required")
        )
        if not auth_configured:
            return "not_configured", "selected operation has no configured authentication"
        return "healthy", "safe authentication-negative fixture placeholders are available"

    def retrieve(
        self,
        context: EvidenceContext,
        _: EvidenceQuery,
    ) -> list[EvidenceFact]:
        facts: list[EvidenceFact] = []
        valid_provider_fact = self._configured_provider_fact(context)
        if valid_provider_fact is not None:
            facts.append(valid_provider_fact)
        facts.extend([
            EvidenceFact(
                source_type=self.provider_type,
                reference=f"auth-fixture:{context.operation.operation_id}:nonexistent-token",
                operation_id=context.operation.operation_id,
                fact=(
                    "A per-execution high-entropy token that is not expected to exist in the "
                    "target session store is available. Use the exact placeholder "
                    "$AUTH_FIXTURE[nonexistent:token]; the backend resolves it only at execution."
                ),
                safe_excerpt="$AUTH_FIXTURE[nonexistent:token]",
                metadata={"fixture_kind": "nonexistent", "token_placeholder": "$AUTH_FIXTURE[nonexistent:token]"},
            )
        ])
        expired_ref = context.settings.auth_provider.negative_fixtures.expired_token_ref
        if expired_ref:
            facts.append(
                EvidenceFact(
                    source_type=self.provider_type,
                    reference=f"auth-fixture:{context.operation.operation_id}:expired-token",
                    operation_id=context.operation.operation_id,
                    fact=(
                        "A configured expired-token fixture is available through the safe "
                        "placeholder $AUTH_FIXTURE[expired:token]. The real value is resolved "
                        "from the project environment at execution and is never sent to the model."
                    ),
                    safe_excerpt="$AUTH_FIXTURE[expired:token]",
                    metadata={
                        "fixture_kind": "expired",
                        "token_placeholder": "$AUTH_FIXTURE[expired:token]",
                    },
                )
            )
        return facts

    @staticmethod
    def _configured_provider_fact(context: EvidenceContext) -> EvidenceFact | None:
        """Expose provider readiness without exposing any credential value."""

        settings = context.settings
        if settings.sut_target.auth_ref:
            try:
                resolve_secret_reference(settings.sut_target.auth_ref)
            except SecretReferenceError:
                return None
            mode = "explicit auth_ref"
        elif not settings.auth_provider.enabled:
            return None
        elif settings.auth_provider.kind == "http":
            login = settings.auth_provider.login
            if login is None:
                return None
            try:
                for reference in login.credential_refs.values():
                    resolve_secret_reference(reference)
            except SecretReferenceError:
                return None
            mode = "configured HTTP Auth Provider"
        else:
            try:
                resolve_secret_reference(settings.auth_provider.sms.phone_ref)
            except SecretReferenceError:
                return None
            mode = "configured SMS Auth Provider"
        return EvidenceFact(
            source_type="auth_provider",
            reference=f"auth-provider:{context.operation.operation_id}:valid-credential",
            operation_id=context.operation.operation_id,
            fact=(
                f"{mode} is configured for this project. The backend will resolve and inject "
                "the current valid credential locally at execution; the model must not write "
                "a literal Authorization, Cookie, or Token value."
            ),
            safe_excerpt="valid credential is injected by the configured Auth Provider at execution",
            metadata={"auth_mode": "automatic", "credential_kind": "valid"},
        )
