from __future__ import annotations

from evals.models import EvalSample, GeneratedCase, MutationSpec


def delete_case(sample: EvalSample, case_id: str) -> EvalSample:
    case = _case(sample, case_id)
    mutated = sample.model_copy(deep=True)
    mutated.cases = [item for item in mutated.cases if item.case_id != case_id]
    mutated.mutation = MutationSpec(
        mutation_id=f"delete-case:{case_id}",
        kind="delete_case",
        reviewer_field="missing_test_point_ids",
        target_ids=case.test_point_ids,
        description=f"删除 {case_id}，制造测试点覆盖缺口",
    )
    return mutated


def remove_required_path_param(
    sample: EvalSample,
    case_id: str,
    parameter_name: str,
) -> EvalSample:
    case = _case(sample, case_id)
    path_params = dict(case.request.get("path_params") or {})
    if parameter_name not in path_params:
        raise ValueError(f"path parameter {parameter_name} not found in {case_id}")
    mutated = sample.model_copy(deep=True)
    for item in mutated.cases:
        if item.case_id == case_id:
            item.request = {
                **item.request,
                "path_params": {
                    key: value
                    for key, value in path_params.items()
                    if key != parameter_name
                },
            }
    mutated.mutation = MutationSpec(
        mutation_id=f"remove-required-path-param:{case_id}:{parameter_name}",
        kind="remove_required_path_param",
        reviewer_field="invalid_case_ids",
        target_ids=[case_id],
        description=f"删除 {case_id} 的必填 path 参数 {parameter_name}，制造不可执行请求",
    )
    return mutated


def duplicate_case(sample: EvalSample, case_id: str) -> EvalSample:
    case = _case(sample, case_id)
    duplicate_id = f"{case_id}__duplicate"
    if any(item.case_id == duplicate_id for item in sample.cases):
        raise ValueError(f"duplicate mutation already exists: {duplicate_id}")
    duplicate = case.model_copy(deep=True)
    duplicate.case_id = duplicate_id
    mutated = sample.model_copy(deep=True)
    mutated.cases = [*mutated.cases, duplicate]
    mutated.mutation = MutationSpec(
        mutation_id=f"duplicate-case:{case_id}",
        kind="duplicate_case",
        reviewer_field="duplicate_case_ids",
        target_ids=[case_id, duplicate_id],
        target_match="any",
        description=f"复制 {case_id}，制造重复用例",
    )
    return mutated


def make_assertion_path_unsupported(
    sample: EvalSample,
    case_id: str,
    assertion_id: str | None = None,
    *,
    path: str = "$.data[*].id",
) -> EvalSample:
    case = _case(sample, case_id)
    if not case.assertions:
        raise ValueError(f"case {case_id} has no assertions")
    target = assertion_id or case.assertions[0].assertion_id
    if target not in {assertion.assertion_id for assertion in case.assertions}:
        raise ValueError(f"assertion {target} not found in {case_id}")
    mutated = sample.model_copy(deep=True)
    for item in mutated.cases:
        if item.case_id == case_id:
            item.assertions = [
                assertion.model_copy(update={"path": path})
                if assertion.assertion_id == target
                else assertion
                for assertion in item.assertions
            ]
    mutated.mutation = MutationSpec(
        mutation_id=f"unsupported-assertion-path:{case_id}:{target}",
        kind="unsupported_assertion_path",
        reviewer_field="unsupported_assertion_ids",
        target_ids=[target],
        description=f"把 {case_id} 的断言 {target} 改成执行器不支持的通配符路径",
    )
    return mutated


def _case(sample: EvalSample, case_id: str) -> GeneratedCase:
    for case in sample.cases:
        if case.case_id == case_id:
            return case
    raise ValueError(f"case not found: {case_id}")
