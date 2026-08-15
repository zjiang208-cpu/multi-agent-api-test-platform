from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import ResourceNotFoundError
from app.evidence.providers.database import DatabaseSchemaEvidenceProvider
from app.evidence.providers.openapi import OpenApiEvidenceProvider
from app.evidence.providers.operation_yaml import OperationYamlEvidenceProvider
from app.evidence.providers.source import JavaSpringSourceEvidenceProvider
from app.evidence.protocol import EvidenceContext, EvidenceQuery
from app.evidence.registry import EvidenceRegistry
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument, RequirementEvidenceRef
from app.projects.service import ProjectService
from app.requirements.operation_store import OperationStore
from app.requirements.requirement_store import RequirementStore


class RequirementBuildResult:
    def __init__(self, requirement: RequirementDocument, evidence: EvidenceBundle) -> None:
        self.requirement = requirement
        self.evidence = evidence


class RequirementBuilder:
    def __init__(self, project_service: ProjectService, data_dir: Path) -> None:
        self.project_service = project_service
        self.data_dir = data_dir

    def build(
        self,
        project_id: str,
        operation_id: str,
        *,
        include_optional_evidence: bool = False,
    ) -> RequirementBuildResult:
        project = self.project_service.get(project_id)
        operation = OperationStore(self.data_dir, project_id).get(operation_id)
        if operation is None:
            raise ResourceNotFoundError(f"operation not found: {operation_id}")

        context = EvidenceContext(project_id=project_id, operation=operation, settings=project.settings)
        evidence = EvidenceRegistry(
            [
                OpenApiEvidenceProvider(),
                OperationYamlEvidenceProvider(),
                JavaSpringSourceEvidenceProvider(),
                DatabaseSchemaEvidenceProvider(),
            ]
        ).collect(context, EvidenceQuery(include_optional=include_optional_evidence))
        requirement_store = RequirementStore(self.data_dir, project_id)
        requirement_id = self._requirement_id(operation.operation_id)
        version = 1
        if requirement_store.exists(requirement_id):
            version = requirement_store.get(requirement_id).version + 1

        unresolved = [
            f"{provider} evidence was unavailable: {status}"
            for provider, status in evidence.provider_status.items()
            if status.startswith("error:")
        ]
        unresolved.extend(operation.contract_metadata.get("unresolved_questions", []))
        conflicts = list(evidence.conflicts)
        requirement = RequirementDocument(
            requirement_id=requirement_id,
            version=version,
            api=operation,
            preconditions=self._preconditions(operation, project.settings.sut_target.auth_ref),
            business_rules=self._business_rules(operation),
            expected_behaviors=self._expected_behaviors(operation),
            conflicts=conflicts,
            unresolved_questions=unresolved,
            evidence_refs=[
                RequirementEvidenceRef(
                    evidence_id=fact.evidence_id,
                    source_type=fact.source_type,
                    reference=fact.reference,
                    confidence=fact.confidence,
                )
                for fact in evidence.facts
            ],
            confidence="question" if unresolved or conflicts else "confirmed",
            source_snapshot=evidence.snapshot_id,
            change_summary="Built from the selected operation contract and configured evidence providers.",
        )
        requirement_store.save(requirement)
        return RequirementBuildResult(requirement, evidence)

    @staticmethod
    def _requirement_id(operation_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9]+", "-", operation_id).strip("-").upper() or "OPERATION"
        return f"REQ-{safe}-001"

    @staticmethod
    def _preconditions(operation, auth_ref: str | None) -> list[str]:
        values = [
            *operation.contract_metadata.get("preconditions", []),
        ]
        values.extend(
            f"Required {item.location} parameter '{item.name}' is available."
            for item in operation.parameters
            if item.required
        )
        if auth_ref:
            values.append("The configured authentication reference is resolvable at execution time.")
        return values

    @staticmethod
    def _business_rules(operation) -> list[str]:
        return [
            *operation.contract_metadata.get("business_rules", []),
            f"The operation accepts HTTP {operation.method} at path {operation.path}.",
            *[
                f"Parameter '{item.name}' is {('required' if item.required else 'optional')} and has type {item.schema_type}."
                for item in operation.parameters
            ],
        ]

    @staticmethod
    def _expected_behaviors(operation) -> list[str]:
        values = [
            *operation.contract_metadata.get("expected_behaviors", []),
            "The response status is one of the statuses declared by the operation contract: "
            + ", ".join(str(item.status_code) for item in operation.responses)
            + "."
        ]
        if operation.request_body is not None:
            values.append("The request body follows the declared request-body contract.")
        if any(item.schema_definition is not None for item in operation.responses):
            values.append("A response with a declared schema conforms to that schema.")
        return values
