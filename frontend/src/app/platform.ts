import type { OperationContract, ParsedRequirementDocument, TestProject } from "../types/api";

export type PageKey = "overview" | "documents" | "operations" | "requirements" | "cases" | "execution" | "reports" | "settings";
export type ParseSuccessNotice = { filename: string; documentId: string; charCount: number; lineCount: number; operationCount?: number };
export type ProjectEditor = {
  name: string;
  description: string;
  baseUrl: string;
  timeoutSeconds: string;
  verifyTls: boolean;
  openapiSources: string;
  sourceWorkspace: string;
  databaseEnabled: boolean;
  databaseDialect: string;
  databaseRef: string;
  databaseSchema: string;
  allowedTables: string;
  authEnabled: boolean;
  authKind: "http" | "sms";
  authTtlSeconds: string;
  authSmsPhoneRef: string;
  authSmsCodeMethod: string;
  authSmsCodePath: string;
  authSmsCodeBodyType: "json" | "form" | "none";
  authSmsCodeQueryParams: string;
  authSmsCodeHeaders: string;
  authSmsCodeBody: string;
  authSmsCodeSource: "redis" | "json";
  authSmsCodeExtractPath: string;
  authSmsRedisHost: string;
  authSmsRedisPort: string;
  authSmsRedisPasswordRef: string;
  authSmsRedisKey: string;
  authLoginMethod: string;
  authLoginPath: string;
  authBodyType: "json" | "form" | "none";
  authQueryParams: string;
  authHeaders: string;
  authBody: string;
  authCredentialRefs: string;
  authExtractSource: "json" | "header" | "cookie";
  authExtractPath: string;
  authInjectLocation: "header" | "cookie";
  authInjectName: string;
  authInjectPrefix: string;
};

export type NavIconName = "overview" | "documents" | "operations" | "requirements" | "cases" | "execution" | "reports" | "settings";
export type NavItem = { key: PageKey; label: string; icon: NavIconName };

export const navGroups: Array<{ label: string; items: NavItem[] }> = [
  { label: "工作台", items: [{ key: "overview", label: "项目概览", icon: "overview" }] },
  {
    label: "测试流程",
    items: [
      { key: "documents", label: "需求文档", icon: "documents" },
      { key: "operations", label: "接口目录", icon: "operations" },
      { key: "requirements", label: "需求分析", icon: "requirements" },
      { key: "cases", label: "测试用例", icon: "cases" },
      { key: "execution", label: "执行中心", icon: "execution" },
      { key: "reports", label: "报告中心", icon: "reports" },
    ],
  },
  { label: "管理", items: [{ key: "settings", label: "项目设置", icon: "settings" }] },
];

export const navItems = navGroups.flatMap((group) => group.items);

export const workflowSteps = ["需求文档", "接口选择", "需求确认", "用例设计", "执行确认", "测试执行", "测试报告"];

export const overviewActions: Array<{ page: PageKey; label: string; description: string }> = [
  { page: "documents", label: "上传需求文档", description: "上传或粘贴 Markdown 需求，识别其中的接口与业务规则。" },
  { page: "operations", label: "选择待测接口", description: "从已识别的接口中选择一个，进入顺序分析流程。" },
  { page: "requirements", label: "确认接口需求", description: "检查提取的业务规则、测试点与辅助证据。" },
  { page: "cases", label: "查看用例设计", description: "查看当前接口生成并经过语义审查的测试用例。" },
  { page: "execution", label: "确认执行范围", description: "确认目标环境、用例数量以及可能产生的副作用。" },
  { page: "execution", label: "查看测试执行", description: "查看已批准批次的执行状态与 HTTP 响应。" },
  { page: "reports", label: "查看测试报告", description: "查看执行结果、断言详情并导出 HTML 报告。" },
];

export function splitLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function projectEditorFrom(project: TestProject): ProjectEditor {
  const authProvider = project.settings.auth_provider;
  const authInject = authProvider?.inject;
  const authLogin = authProvider?.kind === "sms"
    ? authProvider.sms?.login
    : authProvider?.login;
  return {
    name: project.name,
    description: project.description,
    baseUrl: project.settings.sut_target.base_url,
    timeoutSeconds: String(project.settings.sut_target.timeout_seconds),
    verifyTls: project.settings.sut_target.verify_tls,
    openapiSources: project.settings.openapi_sources.join("\n"),
    sourceWorkspace: project.settings.source_workspace ?? "",
    databaseEnabled: project.settings.database.enabled,
    databaseDialect: project.settings.database.dialect ?? "mysql",
    databaseRef: project.settings.database.dsn_ref ?? "",
    databaseSchema: project.settings.database.schema ?? "",
    allowedTables: (project.settings.database.allowed_tables ?? []).join("\n"),
    authEnabled: authProvider?.enabled ?? false,
    authKind: authProvider?.kind ?? "http",
    authTtlSeconds: String(authProvider?.token_ttl_seconds ?? 1800),
    authSmsPhoneRef: authProvider?.sms?.phone_ref ?? "env:TEST_LOGIN_PHONE",
    authSmsCodeMethod: authProvider?.sms?.code_request?.method ?? "POST",
    authSmsCodePath: authProvider?.sms?.code_request?.path ?? "/auth/sms/code",
    authSmsCodeBodyType: authProvider?.sms?.code_request?.body_type ?? "none",
    authSmsCodeQueryParams: JSON.stringify(authProvider?.sms?.code_request?.query_params ?? { phone: "{{phone}}" }, null, 2),
    authSmsCodeHeaders: JSON.stringify(authProvider?.sms?.code_request?.headers ?? {}, null, 2),
    authSmsCodeBody: authProvider?.sms?.code_request?.body == null ? "" : JSON.stringify(authProvider.sms.code_request.body, null, 2),
    authSmsCodeSource: authProvider?.sms?.code_source ?? "redis",
    authSmsCodeExtractPath: authProvider?.sms?.code_path ?? "login:code:{{phone}}",
    authSmsRedisHost: authProvider?.sms?.redis_host ?? "127.0.0.1",
    authSmsRedisPort: String(authProvider?.sms?.redis_port ?? 6379),
    authSmsRedisPasswordRef: authProvider?.sms?.redis_password_ref ?? "",
    authSmsRedisKey: authProvider?.sms?.code_path ?? "login:code:{{phone}}",
    authLoginMethod: authLogin?.method ?? "POST",
    authLoginPath: authLogin?.path ?? "",
    authBodyType: authLogin?.body_type ?? "json",
    authQueryParams: JSON.stringify(authLogin?.query_params ?? {}, null, 2),
    authHeaders: JSON.stringify(authLogin?.headers ?? {}, null, 2),
    authBody: authLogin?.body == null ? "" : JSON.stringify(authLogin.body, null, 2),
    authCredentialRefs: JSON.stringify(authLogin?.credential_refs ?? {}, null, 2),
    authExtractSource: authProvider?.extract?.source ?? "json",
    authExtractPath: authProvider?.extract?.path ?? "$.data",
    authInjectLocation: authInject?.location ?? "header",
    authInjectName: authInject?.name ?? "Authorization",
    authInjectPrefix: authInject ? (authInject.prefix ?? "") : "Bearer",
  };
}

export function statusText(status: string): string {
  const labels: Record<string, string> = {
    FINAL_CASES_READY: "用例已就绪",
    NEEDS_CLARIFICATION: "需要补充信息",
    REQUIREMENT_READY: "需求已生成",
    WAITING_REQUIREMENT_APPROVAL: "等待需求确认",
    DESIGNING: "用例设计中",
    REVIEWING: "完整性检查中",
    DRAFT_CASES_READY: "草稿已生成",
    EVIDENCE_RETRIEVED: "证据已收集",
    DOCUMENT_PARSED: "文档已解析",
    FAILED: "流程失败",
    PENDING: "等待处理",
    RUNNING: "处理中",
    READY_FOR_EXECUTION: "待执行确认",
    READY_WITH_SKIPS: "部分接口已跳过",
    BLOCKED: "需要人工处理",
    SKIPPED: "已跳过",
    COMPLETED: "已完成",
    NLU: "需求分析",
    DESIGNER: "用例设计",
    REVIEWER: "完整性检查",
    passed: "PASS",
    failed: "FAIL",
    mixed: "部分通过",
    error: "执行错误",
  };
  return labels[status] ?? status;
}

export function isQueueTerminal(status: string): boolean {
  return ["READY_FOR_EXECUTION", "READY_WITH_SKIPS", "SKIPPED", "CANCELLED"].includes(status);
}

export function methodClass(method: string): string {
  return `method method-${method.toLowerCase()}`;
}

export function formatDate(value?: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function formatDetailValue(value: unknown): string {
  if (value === undefined) return "未记录";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function escapeHtml(value: unknown): string {
  return formatDetailValue(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function requestPath(value: string): string {
  try {
    const url = new URL(value);
    return `${url.pathname}${url.search}`;
  } catch {
    return value;
  }
}

export function assertionTarget(type?: string | null, path?: string | null): string {
  if (path) return path;
  if (type === "status_code") return "HTTP 状态码";
  if (type === "response_time_ms") return "响应时间（ms）";
  if (type === "response_schema") return "响应 Body Schema";
  return "旧报告未记录字段路径";
}

export function sortRequirementDocuments(documents: ParsedRequirementDocument[]): ParsedRequirementDocument[] {
  return [...documents].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at ?? left.created_at ?? "") || 0;
    const rightTime = Date.parse(right.updated_at ?? right.created_at ?? "") || 0;
    return rightTime - leftTime;
  });
}

export function operationsForDocument(operations: OperationContract[], documentId: string): OperationContract[] {
  return operations.filter((operation) =>
    operation.source_document_id === documentId
    || operation.source_refs?.some((source) => source.source_document_id === documentId),
  );
}

