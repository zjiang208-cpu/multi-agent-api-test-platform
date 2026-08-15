from __future__ import annotations

from app.models.cases import CaseSet, TestCase
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection
from app.providers.llm import CallBudget, LlmProvider
from app.cases.validator import validate_case
from app.workflow.prompts import DESIGNER_AGENT_SYSTEM, DESIGNER_PROMPT


class DesignerService:
    def __init__(self, provider: LlmProvider, *, prompt_version: str | None = None, budget: CallBudget | None = None) -> None:
        self.provider = provider
        self.prompt_version = prompt_version or DESIGNER_PROMPT.definition.version
        self.budget = budget or CallBudget()

    def design(
        self,
        requirement: RequirementDocument,
        points: TestPointCollection,
        evidence: EvidenceBundle,
    ) -> CaseSet:
        self.budget.consume()
        prompt = self._user_prompt(requirement, points, evidence)
        result = self.provider.complete(
            system=DESIGNER_AGENT_SYSTEM,
            user=prompt,
            response_model=CaseSet,
        )
        known_points = {point.point_id for point in points.points}
        known_evidence = {fact.evidence_id for fact in evidence.facts}
        errors = [
            error
            for case in result.cases
            for error in validate_case(
                case,
                known_test_points=known_points,
                known_evidence=known_evidence,
                operation=requirement.api,
            )
        ]
        if errors:
            raise ValueError("designer produced invalid cases: " + "; ".join(errors))
        if result.requirement_id != requirement.requirement_id:
            raise ValueError("designer output requirement_id does not match input")
        return result.model_copy(update={"prompt_version": self.prompt_version})

    @staticmethod
    def _user_prompt(requirement, points, evidence) -> str:
        return (
            "Requirement:\n"
            + requirement.model_dump_json()
            + "\nTest points:\n"
            + points.model_dump_json()
            + "\nEvidence:\n"
            + evidence.model_dump_json()
            + "\nRules: cover every test point; cite evidence refs; use only supported assertion types."
        )
