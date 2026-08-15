export type ProviderState = "configured" | "not_configured" | "healthy" | "error";

export interface ConfigStatus {
  environment: string;
  optional_providers: Record<string, ProviderState | string>;
  execution_policy: {
    remote_targets_allowed: boolean;
    remote_sources_allowed: boolean;
    credentials_exposed: boolean;
  };
}

export interface TargetSettings {
  base_url: string;
  timeout_seconds: number;
  allow_redirects: boolean;
  verify_tls: boolean;
  auth_ref?: string | null;
}

export interface AuthProviderSettings {
  enabled: boolean;
  kind: "http" | "sms";
  token_ttl_seconds?: number | null;
  login?: {
    method: string;
    path: string;
    body_type: "json" | "form" | "none";
    query_params: Record<string, unknown>;
    headers: Record<string, string>;
    body?: unknown;
    credential_refs: Record<string, string>;
  } | null;
  extract: { source: "json" | "header" | "cookie"; path: string };
  inject: { location: "header" | "cookie"; name: string; prefix?: string | null };
  sms?: {
    phone_ref: string;
    code_request: {
      method: string;
      path: string;
      body_type: "json" | "form" | "none";
      query_params: Record<string, unknown>;
      headers: Record<string, string>;
      body?: unknown;
      credential_refs: Record<string, string>;
    };
    code_source: "redis" | "json";
    code_path: string;
    redis_host: string;
    redis_port: number;
    redis_password_ref?: string | null;
    login: {
      method: string;
      path: string;
      body_type: "json" | "form" | "none";
      query_params: Record<string, unknown>;
      headers: Record<string, string>;
      body?: unknown;
      credential_refs: Record<string, string>;
    };
  };
}

export interface ProjectSettings {
  requirement_sources?: string[];
  openapi_sources: string[];
  source_workspace?: string | null;
  sut_target: TargetSettings;
  auth_provider: AuthProviderSettings;
  database: { enabled: boolean; dialect?: string | null; dsn_ref?: string | null; readonly: true; schema?: string | null; allowed_tables: string[] };
  llm: { enabled: boolean; provider: string; model?: string | null; api_key_ref?: string | null; base_url?: string | null; call_budget: number };
}

export interface ParsedRequirementDocument {
  document_id: string;
  filename: string;
  format: "txt" | "md" | "rst" | "html" | "json" | "yaml" | "yml" | "docx" | "pdf";
  detected_kind: "requirement_document" | "operation_contract" | "unknown";
  media_type: string;
  content: string;
  char_count: number;
  line_count: number;
  sha256: string;
  sections: Array<{ section_id: string; title: string; level: number; content: string; line_start: number }>;
  warnings: string[];
  project_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface SourceReference {
  source_document_id?: string | null;
  section?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  heading?: string | null;
  source_text?: string | null;
  reference?: string | null;
}

export interface TestProject {
  project_id: string;
  name: string;
  description: string;
  settings: ProjectSettings;
  created_at: string;
  updated_at: string;
}

export interface OperationContract {
  operation_id: string;
  method: string;
  path: string;
  summary: string;
  parameters: Array<{ name: string; location: string; required: boolean; type: string; constraints: Record<string, unknown> }>;
  responses: Array<{ status_code: number; description: string; schema?: Record<string, unknown> | null }>;
  source_document_id?: string | null;
  source_refs?: SourceReference[];
  confidence?: string;
  contract_metadata?: Record<string, unknown>;
}

export interface RequirementDocument {
  requirement_id: string;
  version: number;
  api: OperationContract;
  business_rules: string[];
  expected_behaviors: string[];
  conflicts: string[];
  unresolved_questions: string[];
  evidence_refs: Array<{ evidence_id: string; source_type: string; reference: string; confidence: string }>;
  confidence: string;
}

export interface TestPointCollection {
  requirement_id: string;
  requirement_version: number;
  points: Array<{ point_id: string; title: string; category: string; priority: string; expected_result: string; evidence_refs: string[] }>;
}

export interface TestCase {
  case_id: string;
  requirement_id: string;
  test_point_ids: string[];
  title: string;
  category: string;
  priority: string;
  expected_behavior: string;
  side_effect: boolean;
  side_effect_note?: string | null;
}

export interface FinalCaseSet {
  final_case_set_id: string;
  requirement_id: string;
  requirement_fingerprint: string;
  cases: TestCase[];
  added_case_ids: string[];
  remaining_gaps: string[];
  unresolved_questions: string[];
  status: "READY" | "NEEDS_CLARIFICATION";
  assembly_errors: string[];
  source_document_id?: string | null;
  api_operation_id?: string | null;
}

export interface WorkflowRunSnapshot {
  workflow_id: string;
  project_id: string;
  operation_id: string;
  source_document_id?: string | null;
  status: string;
  requirement?: RequirementDocument | null;
  evidence?: { operation_id: string; facts: Array<{ evidence_id: string; source_type: string; reference: string; fact: string }> } | null;
  test_points?: TestPointCollection | null;
  draft_cases?: { cases: TestCase[] } | null;
  reviewer_output?: {
    missing_test_point_ids: string[];
    semantic_gaps: string[];
    invalid_case_ids: string[];
    duplicate_case_ids: string[];
    unsupported_assertion_ids: string[];
    suggested_case_specs: Array<{
      spec_id: string;
      target_test_point_ids: string[];
      title: string;
      reason: string;
      category: TestCase["category"];
      priority: TestCase["priority"];
      required_assertions: string[];
      evidence_refs: string[];
    }>;
    remaining_gaps: string[];
    unresolved_questions: string[];
  } | null;
  requirement_approval?: RequirementApproval | null;
  final_cases?: FinalCaseSet | null;
  errors: string[];
  events: Array<{ node: string; status: string; message: string }>;
  metadata: Record<string, string>;
}

export interface RequirementApproval {
  approval_id: string;
  workflow_id: string;
  project_id: string;
  requirement_id: string;
  requirement_version: number;
  requirement_fingerprint: string;
  test_point_count: number;
  approved_at: string;
  status: "APPROVED";
}

export interface ApiProcessingItem {
  api_operation_id: string;
  order: number;
  status: string;
  current_stage: string;
  workflow_id?: string | null;
  requirement_id?: string | null;
  requirement_version?: number | null;
  final_case_set_id?: string | null;
  error_message?: string | null;
}

export interface ApiProcessingQueue {
  run_id: string;
  project_id: string;
  source_document_id: string;
  selected_api_ids: string[];
  current_index: number;
  status: string;
  items: ApiProcessingItem[];
  created_at: string;
  updated_at: string;
}

export interface BatchExecutionApproval {
  approval_id: string;
  queue_run_id: string;
  project_id: string;
  source_document_id: string;
  queue_run_ids?: string[];
  source_document_ids?: string[];
  final_case_set_ids: string[];
  requirement_fingerprints: Record<string, string>;
  target_environment: string;
  base_url: string;
  selected_case_ids: string[];
  selected_case_count: number;
  side_effect_case_ids: string[];
  side_effects_confirmed: boolean;
  auto_regression_allowed: boolean;
  status: "APPROVED";
  approved_at: string;
}

export interface ExecutionApproval {
  approval_id: string;
  workflow_id: string;
  project_id: string;
  final_case_set_id: string;
  requirement_id: string;
  requirement_fingerprint: string;
  target_environment: string;
  base_url: string;
  selected_case_ids: string[];
  selected_case_count: number;
  side_effect_case_ids: string[];
  side_effects_confirmed: boolean;
  auto_regression_allowed: boolean;
  status: "APPROVED";
  approved_at: string;
}

export interface AssertionResult {
  assertion_id: string;
  type?: string | null;
  path?: string | null;
  operator?: string | null;
  evidence_refs?: string[];
  passed: boolean;
  message: string;
  expected?: unknown;
  actual?: unknown;
}

export interface ExecutionResult {
  result_id: string;
  case_id: string;
  case_title?: string | null;
  requirement_id: string;
  api_operation_id?: string | null;
  status: "passed" | "failed" | "error" | "skipped";
  method: string;
  url: string;
  status_code?: number | null;
  response_headers: Record<string, string>;
  response_body?: unknown;
  duration_ms?: number | null;
  assertion_results: AssertionResult[];
  error_category?: string | null;
  error_message?: string | null;
  started_at: string;
}

export interface RunResult {
  run_id: string;
  project_id: string;
  requirement_id: string;
  approval_id?: string | null;
  target_environment?: string | null;
  base_url?: string | null;
  results: ExecutionResult[];
  passed_count: number;
  failed_count: number;
  error_count: number;
}

export interface ReportSnapshot {
  report_id: string;
  run_id: string;
  project_id: string;
  requirement_id: string;
  status: "passed" | "failed" | "error" | "mixed";
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  assertion_total: number;
  assertion_failures: number;
  queue_run_id?: string | null;
  by_api?: Record<string, { total: number; passed: number; failed: number; error: number }>;
  generated_at: string;
}

export interface BatchExecutionResponse {
  run: RunResult;
  report: ReportSnapshot;
}
