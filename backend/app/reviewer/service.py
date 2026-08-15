from __future__ import annotations

from app.cases.validator import validate_case
from app.models.cases import CaseSet
from app.models.evidence import EvidenceBundle
from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPointCollection
from app.workflow.models import ReviewerAgentOutput


class OnePassReviewService:
    """Deterministic compatibility review with the product's no-score contract.

    The production LangGraph Reviewer remains the only component allowed to ask
    an AI model for supplemental cases. This endpoint only reports omissions;
    it never scores, ranks, repairs, or executes cases.
    """

    def review(
        self,
        requirement: RequirementDocument,
        points: TestPointCollection,
        cases: CaseSet,
        evidence: EvidenceBundle,
    ) -> ReviewerAgentOutput:
        point_ids = {point.point_id for point in points.points}
        covered = {
            point_id
            for case in cases.cases
            for point_id in case.test_point_ids
            if point_id in point_ids
        }
        missing = sorted(point_ids - covered)
        evidence_ids = {fact.evidence_id for fact in evidence.facts}
        gaps = [
            f"{case.case_id}: {error}"
            for case in cases.cases
            for error in validate_case(
                case,
                known_test_points=point_ids,
                known_evidence=evidence_ids,
                operation=requirement.api,
            )
        ]
        return ReviewerAgentOutput(
            missing_test_point_ids=missing,
            remaining_gaps=gaps,
            unresolved_questions=list(requirement.unresolved_questions),
        )
