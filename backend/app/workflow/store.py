from __future__ import annotations

import os
from pathlib import Path

from app.requirements.yaml_store import YamlArtifactStore
from app.workflow.models import BatchExecutionApproval, ExecutionApproval, FinalCaseSet, RequirementApproval, WorkflowRunSnapshot


class WorkflowStore:
    def __init__(self, data_dir: Path, project_id: str) -> None:
        root = Path(data_dir).expanduser().resolve() / "projects" / project_id / "artifacts"
        self.artifacts = YamlArtifactStore(root)

    def save_run(self, snapshot: WorkflowRunSnapshot) -> Path:
        return self.artifacts.save("workflow-runs", snapshot.workflow_id, snapshot)

    def get_run(self, workflow_id: str) -> WorkflowRunSnapshot:
        return self.artifacts.load("workflow-runs", workflow_id, WorkflowRunSnapshot)

    def save_final_cases(self, final_cases: FinalCaseSet) -> Path:
        return self.artifacts.save("final-cases", final_cases.final_case_set_id, final_cases)

    def get_final_cases(self, final_case_set_id: str) -> FinalCaseSet:
        return self.artifacts.load("final-cases", final_case_set_id, FinalCaseSet)

    def save_approval(self, approval: ExecutionApproval) -> Path:
        return self.artifacts.save("execution-approvals", approval.approval_id, approval)

    def get_approval(self, approval_id: str) -> ExecutionApproval:
        return self.artifacts.load("execution-approvals", approval_id, ExecutionApproval)

    def claim_approval_execution(self, approval_id: str) -> bool:
        return self._claim_execution("execution-approvals", approval_id)

    def save_requirement_approval(self, approval: RequirementApproval) -> Path:
        return self.artifacts.save("requirement-approvals", approval.approval_id, approval)

    def get_requirement_approval(self, approval_id: str) -> RequirementApproval:
        return self.artifacts.load("requirement-approvals", approval_id, RequirementApproval)

    def save_batch_approval(self, approval: BatchExecutionApproval) -> Path:
        return self.artifacts.save("batch-execution-approvals", approval.approval_id, approval)

    def get_batch_approval(self, approval_id: str) -> BatchExecutionApproval:
        return self.artifacts.load("batch-execution-approvals", approval_id, BatchExecutionApproval)

    def claim_batch_approval_execution(self, approval_id: str) -> bool:
        return self._claim_execution("batch-execution-approvals", approval_id)

    def _claim_execution(self, kind: str, approval_id: str) -> bool:
        approval_path = self.artifacts.path_for(kind, approval_id)
        claim_path = approval_path.with_suffix(".claim")
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                claim_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("claimed\n")
            stream.flush()
            os.fsync(stream.fileno())
        return True
