from app.models.evidence import EvidenceBundle, EvidenceFact
from app.models.auth import AuthProtocol
from app.models.projects import ProjectSettings
from app.evidence.providers.auth_fixture import AuthFixtureEvidenceProvider
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.models.contracts import OperationContract
from app.workflow.auth_protocol import extract_auth_protocol, normalize_auth_text


def _operation() -> OperationContract:
    return OperationContract(
        operation_id="get-user-me",
        method="GET",
        path="/user/me",
        responses=[{"status_code": 200}],
    )


def test_requirement_document_can_explicitly_select_no_auth_prefix():
    evidence = EvidenceBundle(
        operation_id="get-user-me",
        facts=[
            EvidenceFact(
                evidence_id="E-DOC",
                source_type="requirement_document",
                reference="requirement_document:doc-1",
                fact="Token directly goes into authorization.",
            )
        ],
    )
    protocol = extract_auth_protocol(
        operation=_operation(),
        document_excerpt=(
            "登录接口签发的Token直接放入 authorization: <token>，当前不使用 Bearer 前缀。"
        ),
        evidence=evidence,
    )

    assert protocol == AuthProtocol(
        header_name="Authorization",
        prefix=None,
        status="explicit",
        evidence_ids=["E-DOC"],
        source="requirement_document",
    )
    normalized, changed = normalize_auth_text(
        "经authorization请求头携带Bearer前缀请求当前接口。", protocol
    )
    assert changed is True
    assert "Bearer" not in normalized
    assert "Token" in normalized


def test_contract_evidence_can_select_bearer_when_requirement_is_silent():
    evidence = EvidenceBundle(
        operation_id="get-user-me",
        facts=[
            EvidenceFact(
                evidence_id="E-OAS",
                source_type="openapi",
                reference="operation:get-user-me:security",
                fact="Authorization: Bearer <token>",
            )
        ],
    )
    protocol = extract_auth_protocol(
        operation=_operation(), document_excerpt="接口要求登录。", evidence=evidence
    )

    assert protocol.status == "explicit"
    assert protocol.prefix == "Bearer"
    assert protocol.evidence_ids == ["E-OAS"]


def test_unknown_protocol_does_not_accept_model_invented_bearer():
    protocol = AuthProtocol()
    normalized, changed = normalize_auth_text(
        "使用 Bearer <token> 请求当前接口。", protocol
    )

    assert changed is True
    assert "Bearer" not in normalized
    assert "项目配置的认证凭据" in normalized


def test_conflicting_same_rank_evidence_is_not_silently_resolved():
    evidence = EvidenceBundle(
        operation_id="get-user-me",
        facts=[
            EvidenceFact(
                evidence_id="E-OAS",
                source_type="openapi",
                reference="operation:get-user-me:security",
                fact="Authorization: Bearer <token>",
            ),
            EvidenceFact(
                evidence_id="E-YAML",
                source_type="operation_yaml",
                reference="yaml:auth.yml:preconditions",
                fact="Token has no prefix.",
            ),
        ],
    )
    protocol = extract_auth_protocol(
        operation=_operation(), document_excerpt=None, evidence=evidence
    )

    assert protocol.status == "conflict"
    assert protocol.prefix is None
    assert protocol.conflicts


def test_auth_fixture_provider_exposes_nonexistent_and_configured_expired_tokens():
    operation = _operation().model_copy(update={"contract_metadata": {"auth_required": True}})
    settings = ProjectSettings(
        sut_target={"base_url": "http://127.0.0.1:8081"},
        auth_provider={
            "enabled": True,
            "negative_fixtures": {"expired_token_ref": "env:TEST_EXPIRED_TOKEN"},
        },
    )
    provider = AuthFixtureEvidenceProvider()
    context = EvidenceContext(project_id="project-auth", operation=operation, settings=settings)

    assert provider.health(context)[0] == "healthy"
    facts = provider.retrieve(context, EvidenceQuery())
    assert {fact.metadata["fixture_kind"] for fact in facts} == {"nonexistent", "expired"}
    assert all("$AUTH_FIXTURE[" in fact.safe_excerpt for fact in facts)


def test_auth_fixture_provider_exposes_safe_valid_provider_readiness(monkeypatch):
    monkeypatch.setenv("TEST_LOGIN_PHONE", "13800000000")
    operation = _operation().model_copy(update={"contract_metadata": {"auth_required": True}})
    settings = ProjectSettings(
        sut_target={"base_url": "http://127.0.0.1:8081"},
        auth_provider={"enabled": True, "kind": "sms"},
    )
    provider = AuthFixtureEvidenceProvider()
    context = EvidenceContext(project_id="project-auth", operation=operation, settings=settings)

    facts = provider.retrieve(context, EvidenceQuery())

    valid = next(fact for fact in facts if fact.source_type == "auth_provider")
    assert valid.metadata == {"auth_mode": "automatic", "credential_kind": "valid"}
    assert "13800000000" not in valid.fact
    assert "literal Authorization" in valid.fact
