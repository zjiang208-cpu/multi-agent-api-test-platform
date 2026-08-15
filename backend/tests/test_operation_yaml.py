from __future__ import annotations

from pathlib import Path

from app.models.projects import ProjectSettings, TestProject, TestProjectCreate
from app.projects.service import ProjectService
from app.projects.store import ProjectStore
from app.requirements.builder import RequirementBuilder
from app.requirements.operation_yaml import OperationYamlLoader
from app.requirements.service import OperationService


def operation_yaml(path: Path) -> Path:
    path.write_text(
        """
operation:
  id: get-item
  method: GET
  path: /items/{id}
  summary: Get an item
  read_only: true
request:
  parameters:
    - name: id
      in: path
      type: integer
      required: true
      example: 1
      constraints: [positive]
response:
  envelope:
    fields:
      success: {type: boolean, required: true}
      data: {type: object_or_null, required: false}
  scenarios:
    - id: success
      condition: item exists
      http_status: 200
    - id: missing
      condition: item is missing
      http_status: 200
preconditions:
  - target service is available
business_rules:
  - lookup is read-only
expected_behavior:
  - id: success
    description: success is true and data is an object
unresolved_questions: []
evidence:
  notes: response business failure uses the envelope
""".strip(),
        encoding="utf-8",
    )
    return path


def test_operation_yaml_is_one_contract_and_preserves_requirement_metadata(tmp_path: Path):
    source = operation_yaml(tmp_path / "operation-get-item.yaml")
    operation = OperationYamlLoader().discover(str(source))[0]

    assert operation.operation_id == "get-item"
    assert operation.parameters[0].schema_type == "integer"
    assert [response.status_code for response in operation.responses] == [200, 200]
    assert operation.contract_metadata["business_rules"] == ["lookup is read-only"]
    assert operation.responses[0].schema_definition["properties"]["success"] == {"type": "boolean"}


def test_operation_service_and_requirement_builder_use_yaml_source(tmp_path: Path):
    source = operation_yaml(tmp_path / "operation-get-item.yaml")
    project = TestProject.new(
        TestProjectCreate(
            name="YAML contract project",
            settings=ProjectSettings(
                requirement_sources=[str(source)],
                sut_target={"base_url": "http://127.0.0.1:8081"},
            ),
        )
    )
    project_store = ProjectStore(tmp_path / "data")
    project_store.save(project)
    projects = ProjectService(project_store, 10)
    operations, statuses = OperationService(projects, tmp_path / "data").discover(project.project_id)

    assert statuses[str(source)].startswith("healthy: 1")
    assert operations[0].operation_id == "get-item"

    result = RequirementBuilder(projects, tmp_path / "data").build(project.project_id, "get-item")
    assert "lookup is read-only" in result.requirement.business_rules
    assert any(ref.source_type == "operation_yaml" for ref in result.requirement.evidence_refs)
