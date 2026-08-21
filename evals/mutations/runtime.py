from __future__ import annotations

from typing import Any

from app.models.cases import CaseSet
from app.workflow.models import ReviewerAgentOutput
from evals.models import GeneratedReviewerOutput


def mutate_runtime_cases(cases: CaseSet, entry: dict[str, Any]) -> CaseSet:
    """对生产 CaseSet 注入一个 Reviewer 缺陷，不修改原始快照。"""

    kind = str(entry.get("kind") or "")
    case_id = str(entry.get("target_case_id") or "")
    target = next((case for case in cases.cases if case.case_id == case_id), None)
    if target is None:
        raise ValueError(f"case not found in workflow snapshot: {case_id}")

    if kind == "delete_case":
        mutated_cases = [case for case in cases.cases if case.case_id != case_id]
    elif kind == "remove_required_path_param":
        parameter_name = str(entry.get("target_parameter_name") or "")
        if parameter_name not in target.request.path_params:
            raise ValueError(f"path parameter {parameter_name} not found in {case_id}")
        mutated_cases = [
            case.model_copy(
                update={
                    "request": case.request.model_copy(
                        update={
                            "path_params": {
                                key: value
                                for key, value in case.request.path_params.items()
                                if key != parameter_name
                            }
                        }
                    )
                }
            )
            if case.case_id == case_id
            else case
            for case in cases.cases
        ]
    elif kind == "duplicate_case":
        duplicate_id = f"{case_id}__duplicate"
        if any(case.case_id == duplicate_id for case in cases.cases):
            raise ValueError(f"duplicate mutation already exists: {duplicate_id}")
        mutated_cases = [*cases.cases, target.model_copy(update={"case_id": duplicate_id})]
    elif kind == "unsupported_assertion_path":
        assertion_id = str(entry.get("target_assertion_id") or "")
        if assertion_id not in {assertion.assertion_id for assertion in target.assertions}:
            raise ValueError(f"assertion not found in workflow snapshot: {assertion_id}")
        unsupported_path = str(entry.get("path") or "$.data[*].id")
        mutated_cases = [
            case.model_copy(
                update={
                    "assertions": [
                        assertion.model_copy(update={"path": unsupported_path})
                        if assertion.assertion_id == assertion_id
                        else assertion
                        for assertion in case.assertions
                    ]
                }
            )
            if case.case_id == case_id
            else case
            for case in cases.cases
        ]
    else:
        raise ValueError(f"unsupported mutation kind: {kind}")
    return cases.model_copy(deep=True, update={"cases": mutated_cases})


def reviewer_result(output: ReviewerAgentOutput) -> GeneratedReviewerOutput:
    """只保留评测所需的结构化结论，不落盘原始模型响应。"""

    return GeneratedReviewerOutput(
        missing_test_point_ids=output.missing_test_point_ids,
        invalid_case_ids=output.invalid_case_ids,
        duplicate_case_ids=output.duplicate_case_ids,
        unsupported_assertion_ids=output.unsupported_assertion_ids,
        semantic_gaps=output.semantic_gaps,
        remaining_gaps=output.remaining_gaps,
    )
