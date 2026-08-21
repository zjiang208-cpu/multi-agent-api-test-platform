from __future__ import annotations

from uuid import uuid4

from app.cases.validator import validate_case
from app.evidence.providers.database import DatabaseFixtureResolver
from app.models.cases import TestCase
from app.providers.llm import SecretReferenceError
from app.workflow.fingerprint import requirement_fingerprint
from app.workflow.models import FinalCaseSet
from app.workflow.prompts import DESIGNER_PROMPT
from app.workflow.state import WorkflowState


class DesignNodesMixin:
    """Designer、Reviewer、补充设计和最终用例装配节点。"""

    def _designer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        output = self.designer_agent.invoke(
            {
                "mode": "initial",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "evidence": self._downstream_evidence(state),
            }
        )
        draft = self._strip_unrequested_schema_assertions(
            self._canonicalize_redacted_auth_cases(
                self._normalize_case_evidence(output.draft_cases, state), state
            ),
            state["requirement"],
        ).model_copy(
            update={
                "prompt_version": (
                    f"{DESIGNER_PROMPT.definition.version}@{DESIGNER_PROMPT.sha256[:12]}"
                )
            }
        )
        valid_cases, designer_notes = self._partition_valid_cases(
            draft.cases, state, source="initial"
        )
        valid_cases = self._merge_cross_cutting_contract_cases(valid_cases)
        draft = draft.model_copy(update={"cases": valid_cases})
        return self._update(
            state,
            draft_cases=draft,
            designer_notes=designer_notes,
            status="DRAFT_CASES_READY",
            node="designer_agent",
            message=(
                f"Designer Agent produced {len(draft.cases)} draft cases."
                f"{self._metric_suffix(self.designer_agent)}"
            ),
        )

    def _reviewer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        output = self.reviewer_agent.invoke(
            {
                "review_stage": "initial",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "draft_cases": state["draft_cases"],
                "evidence": self._downstream_evidence(state),
            }
        )
        self._validate_review_output(output, state)
        return self._update(
            state,
            reviewer_output=output,
            node="reviewer_agent",
            message=(
                f"Reviewer Agent completed semantic review and proposed "
                f"{len(output.suggested_case_specs)} bounded case specifications."
                f"{self._metric_suffix(self.reviewer_agent)}"
            ),
        )

    @staticmethod
    def _route_after_review(state: WorkflowState) -> str:
        return "supplement" if state["reviewer_output"].suggested_case_specs else "finish"

    def _supplement_designer_agent_node(self, state: WorkflowState) -> dict[str, Any]:
        review = state["reviewer_output"]
        output = self.designer_agent.invoke(
            {
                "mode": "supplement",
                "operation": state["operation"],
                "requirement": state["requirement"],
                "test_points": state["test_points"],
                "evidence": self._downstream_evidence(state),
                "existing_cases": state["draft_cases"],
                "review_feedback": review,
            }
        )
        supplemental_set = self._strip_unrequested_schema_assertions(
            self._canonicalize_redacted_auth_cases(
                self._normalize_case_evidence(output.draft_cases, state), state
            ),
            state["requirement"],
        )
        supplemental_cases = [
            case.model_copy(update={"source": "reviewer_added"})
            for case in supplemental_set.cases
        ]
        supplement_notes: list[str] = list(state.get("designer_notes", []))
        if len(supplemental_cases) > len(review.suggested_case_specs):
            supplement_notes.append(
                "Supplement Designer exceeded Reviewer case specification limit; "
                "extra cases were discarded."
            )
            supplemental_cases = supplemental_cases[: len(review.suggested_case_specs)]
        existing_ids = {case.case_id for case in state["draft_cases"].cases}
        existing_semantics = {
            self._case_semantic_key(case): case.case_id for case in state["draft_cases"].cases
        }
        retained_supplements: list[TestCase] = []
        for case in supplemental_cases:
            if case.case_id in existing_ids:
                supplement_notes.append(
                    f"Skipped duplicate supplemental case ID: {case.case_id}"
                )
                continue
            semantic_key = self._case_semantic_key(case)
            if semantic_key in existing_semantics:
                supplement_notes.append(
                    "Skipped semantic duplicate supplemental case: "
                    f"{case.case_id} duplicates {existing_semantics[semantic_key]}"
                )
                continue
            existing_ids.add(case.case_id)
            existing_semantics[semantic_key] = case.case_id
            retained_supplements.append(case)
        required_points = {
            point_id
            for spec in review.suggested_case_specs
            for point_id in spec.target_test_point_ids
        }
        supplied_points = {
            point_id
            for case in [*state["draft_cases"].cases, *retained_supplements]
            for point_id in case.test_point_ids
        }
        uncovered_targets = sorted(required_points - supplied_points)
        if uncovered_targets:
            supplement_notes.append(
                "Supplement Designer did not cover Reviewer targets: "
                f"{uncovered_targets}"
            )
        retained_supplements, validation_notes = self._partition_valid_cases(
            retained_supplements, state, source="reviewer_added"
        )
        supplement_notes.extend(validation_notes)
        return self._update(
            state,
            supplemental_cases=retained_supplements,
            supplement_notes=supplement_notes,
            status="REVIEWING",
            node="supplement_designer_agent",
            message=(
                f"Designer produced {len(retained_supplements)} bounded supplemental cases; "
                f"{len(supplement_notes)} validation notes were recorded."
                f"{self._metric_suffix(self.designer_agent)}"
            ),
        )

    def _route_after_supplement(self, state: WorkflowState) -> str:
        # The repair budget is one supplement pass. Any remaining uncertainty is
        # preserved as deterministic gaps instead of starting a second Reviewer
        # model call.
        return "local_finish"

    def _local_final_validator_node(self, state: WorkflowState) -> dict[str, Any]:
        review = state["reviewer_output"]
        supplemental_cases = state.get("supplemental_cases", [])
        all_cases = [*state["draft_cases"].cases, *supplemental_cases]
        covered_points = {
            point_id for case in all_cases for point_id in case.test_point_ids
        }
        unresolved_targets: set[str] = set()
        deterministic_gaps: list[str] = []
        for spec in review.suggested_case_specs:
            spec_gaps = self._supplement_spec_gaps(spec, all_cases)
            if not spec_gaps:
                continue
            unresolved_targets.update(spec.target_test_point_ids)
            deterministic_gaps.append(
                f"Bounded repair could not close {spec.spec_id}: "
                + "; ".join(spec_gaps)
            )
        remaining_gaps = list(review.remaining_gaps)
        remaining_gaps.extend(deterministic_gaps)
        locally_final = review.model_copy(
            update={
                "missing_test_point_ids": list(
                    dict.fromkeys(
                        [
                            *[
                                point_id
                                for point_id in review.missing_test_point_ids
                                if point_id not in covered_points
                            ],
                            *sorted(unresolved_targets),
                        ]
                    )
                ),
                "suggested_case_specs": [],
                "remaining_gaps": list(dict.fromkeys(remaining_gaps)),
            }
        )
        return self._update(
            state,
            reviewer_output=locally_final,
            status="REVIEWING",
            node="local_final_validator",
            message=(
                "Deterministic validation completed the single bounded supplement pass; "
                "remaining gaps were retained without another Reviewer model call."
            ),
        )

    def _final_case_assembler(self, state: WorkflowState) -> dict[str, Any]:
        project = self.project_service.get(state["project_id"])
        requirement = state["requirement"]
        draft = state["draft_cases"]
        review = state["reviewer_output"]
        supplemental_cases = state.get("supplemental_cases", [])
        cases: list[TestCase] = []
        seen_ids: set[str] = set()
        seen_semantics: dict[str, str] = {}
        assembly_errors: list[str] = []
        remaining_gaps = list(review.remaining_gaps)
        remaining_gaps.extend(state.get("designer_notes", []))
        remaining_gaps.extend(state.get("supplement_notes", []))
        retained_added_ids: list[str] = []
        invalid_case_ids = set(review.invalid_case_ids)
        removed_invalid_case_ids: list[str] = []
        retained_auth_case_ids: list[str] = []
        unsupported_assertion_ids = set(review.unsupported_assertion_ids)
        fixture_resolver = DatabaseFixtureResolver()
        known_points = {point.point_id for point in state["test_points"].points}
        known_evidence = {fact.evidence_id for fact in state["evidence"].facts}
        seen_execution_semantics: dict[str, str] = {}
        for case, is_supplemental in [
            *((case, False) for case in draft.cases),
            *((case, True) for case in supplemental_cases),
        ]:
            if case.case_id in invalid_case_ids:
                if self._has_unresolved_authentication(case, project.settings):
                    case = self._strip_authentication_placeholder(case)
                    retained_auth_case_ids.append(case.case_id)
                    remaining_gaps.append(
                        f"Retained {case.case_id}; authentication will be obtained automatically at execution when the target supports local login."
                    )
                else:
                    deterministic_errors = validate_case(
                        case,
                        known_test_points=known_points,
                        known_evidence=known_evidence,
                        operation=state["operation"],
                    )
                    if deterministic_errors:
                        removed_invalid_case_ids.append(case.case_id)
                        remaining_gaps.append(
                            f"Removed Reviewer-invalid case before final assembly: {case.case_id}"
                        )
                        continue
                    # A Reviewer semantic concern (for example, an assertion
                    # that is too weak) is not a structural invalidity. Keep the
                    # executable Case and expose the concern as a warning.
                    remaining_gaps.append(
                        f"Reviewer marked {case.case_id} for review, but deterministic validation passed; Case retained."
                    )
            unsupported_in_case = sorted(
                assertion.assertion_id
                for assertion in case.assertions
                if assertion.assertion_id in unsupported_assertion_ids
            )
            if unsupported_in_case:
                supported_assertions = [
                    assertion
                    for assertion in case.assertions
                    if assertion.assertion_id not in unsupported_assertion_ids
                ]
                # Reviewer findings are scoped to the offending assertions. Keep
                # the Case when another executable assertion remains; only discard
                # a Case whose entire assertion set is unusable.
                remaining_gaps.append(
                    "Removed Reviewer-unsupported assertions from "
                    f"{case.case_id}: {unsupported_in_case}"
                )
                if not supported_assertions:
                    remaining_gaps.append(
                        f"Removed Case with no executable assertions after Reviewer review: {case.case_id}"
                    )
                    continue
                case = case.model_copy(update={"assertions": supported_assertions})
            if case.case_id in seen_ids:
                remaining_gaps.append(f"Removed duplicate case ID: {case.case_id}")
                continue
            case = fixture_resolver.bind_case_fixtures(
                case,
                operation=state["operation"],
                points=state["test_points"].points,
                evidence=state["evidence"],
            )
            try:
                case = fixture_resolver.resolve_case(case, project.settings)
            except (ValueError, SecretReferenceError) as exc:
                remaining_gaps.append(
                    f"Removed case with unresolved local database fixture: {case.case_id} -> {exc}"
                )
                continue
            semantic_key = self._case_semantic_key(case)
            if semantic_key in seen_semantics:
                remaining_gaps.append(
                    "Removed semantic duplicate case: "
                    f"{case.case_id} duplicates {seen_semantics[semantic_key]}"
                )
                continue
            execution_key = self._case_execution_key(case)
            existing_execution_case_id = seen_execution_semantics.get(execution_key)
            if existing_execution_case_id is not None:
                existing_index = next(
                    index
                    for index, retained_case in enumerate(cases)
                    if retained_case.case_id == existing_execution_case_id
                )
                existing_case = cases[existing_index]
                merged_point_ids = list(
                    dict.fromkeys(
                        [*existing_case.test_point_ids, *case.test_point_ids]
                    )
                )
                merged_preconditions = list(
                    dict.fromkeys(
                        [*existing_case.preconditions, *case.preconditions]
                    )
                )
                cases[existing_index] = existing_case.model_copy(
                    update={
                        "test_point_ids": merged_point_ids,
                        "preconditions": merged_preconditions,
                        "evidence_refs": list(
                            dict.fromkeys(
                                [*existing_case.evidence_refs, *case.evidence_refs]
                            )
                        ),
                    }
                )
                if merged_point_ids == existing_case.test_point_ids:
                    remaining_gaps.append(
                        "Removed semantic duplicate case: "
                        f"{case.case_id} duplicates {existing_execution_case_id}"
                    )
                else:
                    remaining_gaps.append(
                        "Merged duplicate execution case: "
                        f"{case.case_id} into {existing_execution_case_id}; "
                        "test-point coverage was preserved."
                    )
                continue
            seen_ids.add(case.case_id)
            seen_semantics[semantic_key] = case.case_id
            seen_execution_semantics[execution_key] = case.case_id
            cases.append(case)
            if is_supplemental:
                retained_added_ids.append(case.case_id)

        covered_points = {point_id for case in cases for point_id in case.test_point_ids}
        expected_points = {point.point_id for point in state["test_points"].points}
        missing_points = sorted(expected_points - covered_points)
        if not expected_points:
            assembly_errors.append("no test points were generated")
        if not cases:
            assembly_errors.append("no test cases were generated")
        if missing_points:
            message = f"Test points still uncovered: {', '.join(missing_points)}"
            remaining_gaps.append(message)
        if review.missing_test_point_ids:
            remaining_gaps.append(
                "Reviewer reported semantically uncovered test points: "
                f"{review.missing_test_point_ids}"
            )
        if review.semantic_gaps:
            remaining_gaps.extend(
                f"Reviewer semantic gap: {gap}" for gap in review.semantic_gaps
            )
        if removed_invalid_case_ids:
            remaining_gaps.append(
                f"Reviewer-invalid cases were removed: {removed_invalid_case_ids}"
            )
        if retained_auth_case_ids:
            remaining_gaps.append(
                "Authentication will be resolved automatically for retained cases when possible; "
                "an explicit auth_ref is used as fallback: "
                f"{retained_auth_case_ids}"
            )
        if review.duplicate_case_ids:
            remaining_gaps.append(
                f"Reviewer reported duplicate cases; deterministic deduplication was applied: "
                f"{review.duplicate_case_ids}"
            )
        if review.unsupported_assertion_ids:
            remaining_gaps.append(
                "Reviewer-unsupported assertions were removed or isolated at assertion level: "
                f"{review.unsupported_assertion_ids}"
            )
        if review.suggested_case_specs:
            remaining_gaps.append(
                "Bounded repair limit reached; unresolved case specifications require manual "
                f"follow-up: {[spec.spec_id for spec in review.suggested_case_specs]}"
            )

        unresolved_questions = list(
            dict.fromkeys(
                [*requirement.unresolved_questions, *review.unresolved_questions]
            )
        )
        # Requirement Approval is the human decision for unresolved business
        # questions. Keep questions and reviewer gaps visible on Final Cases,
        # then let the second Human Gate decide which generated Cases to execute.
        # A partial review finding must not hide otherwise executable Cases;
        # only an empty generated Case set is a hard failure.
        status = "READY" if cases else "NEEDS_CLARIFICATION"
        final_cases = FinalCaseSet(
            final_case_set_id=f"final-{uuid4().hex}",
            requirement_id=requirement.requirement_id,
            requirement_fingerprint=requirement_fingerprint(requirement),
            source_document_id=state.get("input_document_id"),
            api_operation_id=state["operation"].operation_id,
            cases=cases,
            added_case_ids=retained_added_ids,
            remaining_gaps=list(dict.fromkeys(remaining_gaps)),
            unresolved_questions=unresolved_questions,
            status=status,
            assembly_errors=assembly_errors,
        )
        return self._update(
            state,
            final_cases=final_cases,
            status="FINAL_CASES_READY" if status == "READY" else "NEEDS_CLARIFICATION",
            node="final_case_assembler",
            message=f"Final Cases assembled with status {status}.",
        )
