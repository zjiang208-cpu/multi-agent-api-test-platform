import type { ApiProcessingQueue, BatchExecutionApproval, BatchExecutionResponse, ConfigStatus, ExecutionApproval, FinalCaseSet, OperationContract, ParsedRequirementDocument, ProjectSettings, ReportSnapshot, RequirementDocument, RunResult, TestPointCollection, TestProject, WorkflowRunSnapshot } from "../types/api";

const apiPrefix = "/api";

async function request<T>(path: string, init?: RequestInit, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiPrefix}${path}`, {
      ...init,
      signal: controller.signal,
      headers: init?.body instanceof FormData ? { ...(init?.headers ?? {}) } : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
      throw new Error(payload?.error?.message ?? `Request failed (${response.status})`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
  config: () => request<ConfigStatus>("/config/status"),
  projects: () => request<TestProject[]>("/projects"),
  createProject: (payload: { name: string; description: string; settings: ProjectSettings }) =>
    request<TestProject>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (projectId: string, payload: { name?: string; description?: string; settings?: ProjectSettings }) =>
    request<TestProject>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  refreshProjectAuth: (projectId: string) =>
    request<{ success: boolean; status: "refreshed" | "disabled" | "reference" | "failed"; message: string }>(`/projects/${projectId}/auth/refresh`, { method: "POST", body: "{}" }, 60000),
  deleteProject: (projectId: string) =>
    request<void>(`/projects/${projectId}`, { method: "DELETE" }),
  operations: (projectId: string) => request<OperationContract[]>(`/projects/${projectId}/operations`),
  discoverOperations: (projectId: string) =>
    request<{ operations: OperationContract[]; source_status: Record<string, string> }>(`/projects/${projectId}/operations/discover`, { method: "POST", body: "{}" }),
  importOperationText: (projectId: string, filename: string, content: string) =>
    request<{ operations: OperationContract[]; source_status: Record<string, string> }>(`/projects/${projectId}/operations/import-text`, { method: "POST", body: JSON.stringify({ filename, content }) }, 60000),
  ingestAndDiscoverRequirement: (projectId: string, filename: string, content: string) =>
    request<{ document: ParsedRequirementDocument; operations: OperationContract[] }>(`/projects/${projectId}/requirement-documents/ingest-and-discover`, { method: "POST", body: JSON.stringify({ filename, content }) }, 120000),
  requirementDocument: (projectId: string, documentId: string) =>
    request<ParsedRequirementDocument>(`/projects/${projectId}/requirement-documents/${documentId}`),
  requirementDocuments: (projectId: string) =>
    request<ParsedRequirementDocument[]>(`/projects/${projectId}/requirement-documents`),
  parseRequirementText: (filename: string, content: string) =>
    request<ParsedRequirementDocument>("/requirement-documents/parse-text", { method: "POST", body: JSON.stringify({ filename, content }) }, 60000),
  parseRequirementFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ParsedRequirementDocument>("/requirement-documents/parse", { method: "POST", body }, 120000);
  },
  buildRequirement: (projectId: string, operationId: string) =>
    request<{ requirement: RequirementDocument }>(`/projects/${projectId}/requirements/build`, { method: "POST", body: JSON.stringify({ operation_id: operationId }) }),
  generateTestPoints: (projectId: string, requirementId: string) =>
    request<TestPointCollection>(`/projects/${projectId}/test-points/generate`, { method: "POST", body: JSON.stringify({ requirement_id: requirementId }) }),
  designWorkflow: (projectId: string, operationId: string, requirementDocument?: string, requirementDocumentId?: string) =>
    request<WorkflowRunSnapshot>(`/projects/${projectId}/workflows/design`, { method: "POST", body: JSON.stringify({ operation_id: operationId, requirement_document: requirementDocument || null, requirement_document_id: requirementDocumentId || null }) }, 120000),
  workflowRun: (projectId: string, workflowId: string) =>
    request<WorkflowRunSnapshot>(`/projects/${projectId}/workflows/${workflowId}`),
  approveWorkflow: (projectId: string, workflowId: string, payload: { final_case_set_id: string; target_environment: string; base_url: string; case_ids: string[]; case_count: number; side_effect_case_ids: string[]; side_effects_confirmed: boolean; auto_regression_allowed: boolean }) =>
    request<ExecutionApproval>(`/projects/${projectId}/workflows/${workflowId}/approve`, { method: "POST", body: JSON.stringify(payload) }),
  executeApproved: (projectId: string, approvalId: string) =>
    request<BatchExecutionResponse>(`/projects/${projectId}/runs/execute`, { method: "POST", body: JSON.stringify({ approval_id: approvalId }) }, 120000),
  autoRegress: (projectId: string, approvalId: string) =>
    request<BatchExecutionResponse>(`/projects/${projectId}/runs/auto-regress`, { method: "POST", body: JSON.stringify({ approval_id: approvalId }) }, 120000),
  createProcessingQueue: (projectId: string, sourceDocumentId: string, operationIds: string[]) =>
    request<ApiProcessingQueue>(`/projects/${projectId}/processing-queues`, { method: "POST", body: JSON.stringify({ source_document_id: sourceDocumentId, operation_ids: operationIds }) }),
  processingQueues: (projectId: string) =>
    request<ApiProcessingQueue[]>(`/projects/${projectId}/processing-queues`),
  processingQueue: (projectId: string, runId: string) =>
    request<ApiProcessingQueue>(`/projects/${projectId}/processing-queues/${runId}`),
  startProcessingQueue: (projectId: string, runId: string) =>
    request<{ queue: ApiProcessingQueue; workflow: WorkflowRunSnapshot }>(`/projects/${projectId}/processing-queues/${runId}/start`, { method: "POST", body: "{}" }, 300000),
  skipProcessingQueue: (projectId: string, runId: string, reason?: string) =>
    request<ApiProcessingQueue>(`/projects/${projectId}/processing-queues/${runId}/skip-current`, { method: "POST", body: JSON.stringify({ reason: reason || null }) }, 30000),
  approveCurrentRequirement: (projectId: string, runId: string, payload: { requirement_id: string; requirement_version: number }) =>
    request<{ queue: ApiProcessingQueue; workflow: WorkflowRunSnapshot }>(`/projects/${projectId}/processing-queues/${runId}/approve-requirement`, { method: "POST", body: JSON.stringify(payload) }, 300000),
  retryCachedDesign: (projectId: string, runId: string) =>
    request<{ queue: ApiProcessingQueue; workflow: WorkflowRunSnapshot }>(`/projects/${projectId}/processing-queues/${runId}/retry-design`, { method: "POST", body: "{}" }, 30000),
  queueFinalCases: (projectId: string, runId: string) =>
    request<FinalCaseSet[]>(`/projects/${projectId}/processing-queues/${runId}/final-cases`),
  projectFinalCases: (projectId: string) =>
    request<FinalCaseSet[]>(`/projects/${projectId}/cases/final`),
  approveBatchExecution: (projectId: string, runId: string, payload: { target_environment: string; base_url: string; case_ids: string[]; case_count: number; side_effect_case_ids: string[]; side_effects_confirmed: boolean; auto_regression_allowed: boolean }) =>
    request<BatchExecutionApproval>(`/projects/${projectId}/processing-queues/${runId}/approve-execution`, { method: "POST", body: JSON.stringify(payload) }),
  approveProjectExecution: (projectId: string, payload: { target_environment: string; base_url: string; case_ids: string[]; case_count: number; side_effect_case_ids: string[]; side_effects_confirmed: boolean; auto_regression_allowed: boolean }) =>
    request<BatchExecutionApproval>(`/projects/${projectId}/cases/approve-execution`, { method: "POST", body: JSON.stringify(payload) }),
  executeBatch: (projectId: string, approvalId: string) =>
    request<BatchExecutionResponse>(`/projects/${projectId}/runs/execute-batch`, { method: "POST", body: JSON.stringify({ approval_id: approvalId }) }, 120000),
  autoRegressBatch: (projectId: string, approvalId: string) =>
    request<BatchExecutionResponse>(`/projects/${projectId}/runs/auto-regress-batch`, { method: "POST", body: JSON.stringify({ approval_id: approvalId }) }, 120000),
  reports: (projectId: string) =>
    request<ReportSnapshot[]>(`/projects/${projectId}/reports`),
  run: (projectId: string, runId: string) =>
    request<RunResult>(`/projects/${projectId}/runs/${runId}`),
};
