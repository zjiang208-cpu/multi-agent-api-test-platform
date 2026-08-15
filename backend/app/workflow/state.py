from __future__ import annotations

from typing import Any, TypedDict

from app.models.contracts import OperationContract
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection
from app.workflow.models import FinalCaseSet, ReviewerAgentOutput, WorkflowStatus
from app.models.cases import CaseSet, TestCase


class WorkflowEvent(TypedDict):
    node: str
    status: str
    message: str


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    project_id: str
    operation_id: str
    include_optional_evidence: bool
    input_document_id: str | None
    input_document: str | None
    operation: OperationContract
    evidence: EvidenceBundle
    requirement: RequirementDocument
    test_points: TestPointCollection
    draft_cases: CaseSet
    designer_notes: list[str]
    supplemental_cases: list[TestCase]
    supplement_notes: list[str]
    reviewer_output: ReviewerAgentOutput
    final_cases: FinalCaseSet
    status: WorkflowStatus
    errors: list[str]
    events: list[WorkflowEvent]
    metadata: dict[str, Any]
