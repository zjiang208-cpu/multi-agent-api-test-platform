from __future__ import annotations

import re
from pathlib import Path

from app.models.requirements import RequirementDocument
from app.models.testpoints import TestPoint, TestPointCollection
from app.projects.service import ProjectService
from app.requirements.requirement_store import RequirementStore
from app.testpoints.store import TestPointStore


class TestPointGenerator:
    def __init__(self, project_service: ProjectService, data_dir: Path) -> None:
        self.project_service = project_service
        self.data_dir = data_dir

    def generate(self, project_id: str, requirement_id: str) -> TestPointCollection:
        self.project_service.get(project_id)
        requirement = RequirementStore(self.data_dir, project_id).get(requirement_id)
        points = self._generate_points(requirement)
        collection = TestPointCollection(
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.version,
            points=points,
        )
        TestPointStore(self.data_dir, project_id).save(collection)
        return collection

    def get(self, project_id: str, requirement_id: str) -> TestPointCollection:
        self.project_service.get(project_id)
        return TestPointStore(self.data_dir, project_id).get(requirement_id)

    @classmethod
    def _generate_points(cls, requirement: RequirementDocument) -> list[TestPoint]:
        refs = [item.evidence_id for item in requirement.evidence_refs]
        operation = requirement.api
        values: list[TestPoint] = [
            cls._point(
                requirement,
                title=f"{operation.method} {operation.path} accepts a valid request",
                category="positive",
                priority="high",
                action=f"Send {operation.method} {operation.path} with all required parameters and a valid request body when applicable.",
                expected="The response uses a status declared by the operation contract and matches the documented response shape.",
                refs=refs,
                params=[item.name for item in operation.parameters if item.required],
            )
        ]
        for parameter in operation.parameters:
            if parameter.required:
                values.append(
                    cls._point(
                        requirement,
                        title=f"Reject a request missing required {parameter.location} parameter '{parameter.name}'",
                        category="negative",
                        priority="high",
                        action=f"Send {operation.method} {operation.path} without required {parameter.location} parameter '{parameter.name}'.",
                        expected="The request is rejected with a documented or contract-compatible client error.",
                        refs=refs,
                        params=[parameter.name],
                    )
                )
            for key, value in cls._constraint_entries(parameter.constraints):
                values.append(
                    cls._point(
                        requirement,
                        title=f"Verify {parameter.name} constraint {key}={value}",
                        category="boundary",
                        priority="medium",
                        action=f"Send {operation.method} {operation.path} with '{parameter.name}' at the {key} boundary ({value}).",
                        expected=f"The service handles the {key} boundary according to the operation contract without violating the declared constraint.",
                        refs=refs,
                        params=[parameter.name],
                    )
                )
        if operation.request_body is not None:
            values.append(
                cls._point(
                    requirement,
                    title="Validate the request body contract",
                    category="contract",
                    priority="high",
                    action=f"Send {operation.method} {operation.path} with a request body matching the declared schema.",
                    expected="The request is accepted or rejected according to the declared request-body contract.",
                    refs=refs,
                )
            )
        for response in operation.responses:
            values.append(
                cls._point(
                    requirement,
                    title=f"Verify documented response status {response.status_code}",
                    category="contract",
                    priority="high" if 200 <= response.status_code < 300 else "medium",
                    action=f"Exercise the {operation.method} {operation.path} response scenario that produces HTTP {response.status_code}.",
                    expected=f"HTTP {response.status_code} is returned with the documented content contract when one is declared.",
                    refs=refs,
                )
            )
        return cls._deduplicate(values)

    @staticmethod
    def _constraint_entries(constraints):
        special = {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"}
        if "exclusiveMinimum" in constraints and constraints["exclusiveMinimum"] is not False:
            value = constraints["exclusiveMinimum"]
            if value is True:
                value = constraints.get("minimum")
            if value is not None:
                yield "exclusiveMinimum", value
        elif "minimum" in constraints:
            yield "minimum", constraints["minimum"]

        if "exclusiveMaximum" in constraints and constraints["exclusiveMaximum"] is not False:
            value = constraints["exclusiveMaximum"]
            if value is True:
                value = constraints.get("maximum")
            if value is not None:
                yield "exclusiveMaximum", value
        elif "maximum" in constraints:
            yield "maximum", constraints["maximum"]

        for key, value in constraints.items():
            if key not in special:
                yield key, value

    @staticmethod
    def _point(requirement, *, title, category, priority, action, expected, refs, params=None):
        return TestPoint(
            point_id="TP-" + re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").upper(),
            requirement_id=requirement.requirement_id,
            title=title,
            category=category,
            priority=priority,
            action=action,
            expected_result=expected,
            evidence_refs=refs,
            parameter_refs=params or [],
        )

    @staticmethod
    def _deduplicate(points: list[TestPoint]) -> list[TestPoint]:
        result: list[TestPoint] = []
        seen: set[str] = set()
        for point in points:
            if point.point_id in seen:
                continue
            seen.add(point.point_id)
            result.append(point)
        return result
