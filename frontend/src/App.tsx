import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import type {
  BatchExecutionResponse,
  BatchExecutionApproval,
  ApiProcessingQueue,
  ExecutionApproval,
  ExecutionResult,
  FinalCaseSet,
  OperationContract,
  ParsedRequirementDocument,
  ProjectSettings,
  TestProject,
  WorkflowRunSnapshot,
} from "./types/api";
import "./styles.css";

type PageKey = "overview" | "documents" | "operations" | "requirements" | "cases" | "execution" | "reports" | "settings";
type ParseSuccessNotice = { filename: string; documentId: string; charCount: number; lineCount: number; operationCount?: number };
type ProjectEditor = {
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

const navItems: Array<{ key: PageKey; label: string; shortLabel: string }> = [
  { key: "overview", label: "项目概览", shortLabel: "概" },
  { key: "documents", label: "需求文档", shortLabel: "文" },
  { key: "operations", label: "接口目录", shortLabel: "接" },
  { key: "requirements", label: "需求分析", shortLabel: "需" },
  { key: "cases", label: "测试用例", shortLabel: "例" },
  { key: "execution", label: "执行中心", shortLabel: "执" },
  { key: "reports", label: "报告中心", shortLabel: "报" },
  { key: "settings", label: "项目设置", shortLabel: "设" },
];

const workflowSteps = ["需求文档", "接口选择", "需求确认", "用例设计", "执行确认", "测试执行", "测试报告"];

function splitLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function projectEditorFrom(project: TestProject): ProjectEditor {
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

function statusText(status: string): string {
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
    BLOCKED: "需要人工处理",
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

function methodClass(method: string): string {
  return `method method-${method.toLowerCase()}`;
}

function formatDate(value?: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function formatDetailValue(value: unknown): string {
  if (value === undefined) return "未记录";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function escapeHtml(value: unknown): string {
  return formatDetailValue(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function requestPath(value: string): string {
  try {
    const url = new URL(value);
    return `${url.pathname}${url.search}`;
  } catch {
    return value;
  }
}

function assertionTarget(type?: string | null, path?: string | null): string {
  if (path) return path;
  if (type === "status_code") return "HTTP 状态码";
  if (type === "response_time_ms") return "响应时间（ms）";
  if (type === "response_schema") return "响应 Body Schema";
  return "旧报告未记录字段路径";
}

function sortRequirementDocuments(documents: ParsedRequirementDocument[]): ParsedRequirementDocument[] {
  return [...documents].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at ?? left.created_at ?? "") || 0;
    const rightTime = Date.parse(right.updated_at ?? right.created_at ?? "") || 0;
    return rightTime - leftTime;
  });
}

function operationsForDocument(operations: OperationContract[], documentId: string): OperationContract[] {
  return operations.filter((operation) =>
    operation.source_document_id === documentId
    || operation.source_refs?.some((source) => source.source_document_id === documentId),
  );
}

export default function App() {
  const [projects, setProjects] = useState<TestProject[]>([]);
  const [operations, setOperations] = useState<OperationContract[]>([]);
  const [selectedProject, setSelectedProject] = useState<TestProject | null>(null);
  const [selectedOperation, setSelectedOperation] = useState<OperationContract | null>(null);
  const [selectedOperationIds, setSelectedOperationIds] = useState<string[]>([]);
  const [parsedDocument, setParsedDocument] = useState<ParsedRequirementDocument | null>(null);
  const [requirementDocuments, setRequirementDocuments] = useState<ParsedRequirementDocument[]>([]);
  const [documentText, setDocumentText] = useState("");
  const [documentName, setDocumentName] = useState("pasted-requirement.md");
  const [documentError, setDocumentError] = useState("");
  const [workflow, setWorkflow] = useState<WorkflowRunSnapshot | null>(null);
  const [approval, setApproval] = useState<ExecutionApproval | null>(null);
  const [batchApproval, setBatchApproval] = useState<BatchExecutionApproval | null>(null);
  const [queue, setQueue] = useState<ApiProcessingQueue | null>(null);
  const [finalCaseSets, setFinalCaseSets] = useState<FinalCaseSet[]>([]);
  const [execution, setExecution] = useState<BatchExecutionResponse | null>(null);
  const [selectedResult, setSelectedResult] = useState<ExecutionResult | null>(null);
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const [targetEnvironment, setTargetEnvironment] = useState("local");
  const [baseUrl, setBaseUrl] = useState("");
  const [sideEffectsConfirmed, setSideEffectsConfirmed] = useState(false);
  const [page, setPage] = useState<PageKey>(() => {
    const rememberedPage = window.sessionStorage.getItem("api-test-platform.page");
    return navItems.some((item) => item.key === rememberedPage) ? rememberedPage as PageKey : "overview";
  });
  const [busy, setBusy] = useState(false);
  const [startingWorkflow, setStartingWorkflow] = useState(false);
  const [message, setMessage] = useState("正在加载工作区…");
  const [parseSuccess, setParseSuccess] = useState<ParseSuccessNotice | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<{ name: string; authSuccess: boolean; authMessage: string } | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newProjectName, setNewProjectName] = useState("基于Multi-Agent的接口自动化测试平台");
  const [newProjectDescription, setNewProjectDescription] = useState("基于Multi-Agent的接口自动化测试平台");
  const [newBaseUrl, setNewBaseUrl] = useState("http://127.0.0.1:8081");
  const [newOpenapiSource, setNewOpenapiSource] = useState("");
  const [newWorkspace, setNewWorkspace] = useState("");
  const [newDbEnabled, setNewDbEnabled] = useState(false);
  const [newDbDialect, setNewDbDialect] = useState("mysql");
  const [newDbRef, setNewDbRef] = useState("");
  const [newDbSchema, setNewDbSchema] = useState("");
  const [newDbTables, setNewDbTables] = useState("");
  const [projectEditor, setProjectEditor] = useState<ProjectEditor | null>(null);

  const finalCases = workflow?.final_cases;
  const allFinalCases = finalCaseSets.flatMap((item) => item.cases);
  const completedOperationIds = useMemo(
    () => new Set(finalCaseSets.map((item) => item.api_operation_id).filter((item): item is string => Boolean(item))),
    [finalCaseSets],
  );
  const activeFlowOperationId = queue && !["READY_FOR_EXECUTION", "CANCELLED"].includes(queue.status)
    ? queue.items[0]?.api_operation_id ?? null
    : null;
  const sideEffectCaseIds = useMemo(
    () => allFinalCases.filter((item) => selectedCaseIds.includes(item.case_id) && item.side_effect).map((item) => item.case_id),
    [allFinalCases, selectedCaseIds],
  );
  const activeNav = navItems.find((item) => item.key === page) ?? navItems[0];
  const currentStep = execution ? 6 : batchApproval ? 5 : queue?.status === "READY_FOR_EXECUTION" ? 4 : startingWorkflow || workflow?.status === "WAITING_REQUIREMENT_APPROVAL" ? 2 : workflow ? 3 : parsedDocument ? 1 : 0;

  useEffect(() => {
    api.projects()
      .then((nextProjects) => {
        setProjects(nextProjects);
        const rememberedProjectId = window.sessionStorage.getItem("api-test-platform.project-id");
        setSelectedProject(nextProjects.find((project) => project.project_id === rememberedProjectId) ?? nextProjects[0] ?? null);
        setMessage(nextProjects.length ? "请先解析需求文档，再选择要测试的接口。" : "需求文档可以独立解析；开始测试分析前，请先创建测试项目。");
      })
      .catch((error: Error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    window.sessionStorage.setItem("api-test-platform.page", page);
  }, [page]);

  useEffect(() => {
    if (!selectedProject) {
      setOperations([]);
      setRequirementDocuments([]);
      setParsedDocument(null);
      return;
    }
    let cancelled = false;
    const projectId = selectedProject.project_id;
    window.sessionStorage.setItem("api-test-platform.project-id", projectId);
    setBaseUrl(selectedProject.settings.sut_target.base_url);
    setSelectedOperationIds([]);
    setSelectedOperation(null);
    setQueue(null);
    setFinalCaseSets([]);
    setWorkflow(null);
    setApproval(null);
    setBatchApproval(null);
    setExecution(null);
    setStartingWorkflow(false);
    setOperations([]);
    setRequirementDocuments([]);
    setParsedDocument(null);
    void Promise.all([api.operations(projectId), api.processingQueues(projectId), api.requirementDocuments(projectId), api.projectFinalCases(projectId)])
      .then(async ([savedOperations, queues, savedDocuments, savedFinalCases]) => {
        if (cancelled) return;
        const documents = sortRequirementDocuments(savedDocuments);
        let restoredOperations = savedOperations;
        if (documents.length > 1 && savedOperations.length > 0) {
          const missingIndexes = documents.filter(
            (document) => operationsForDocument(restoredOperations, document.document_id).length === 0,
          );
          for (const document of missingIndexes) {
            const recovered = await api.ingestAndDiscoverRequirement(projectId, document.filename, document.content).catch(() => null);
            if (recovered) restoredOperations = recovered.operations;
          }
        }
        if (cancelled) return;
        setOperations(restoredOperations);
        setRequirementDocuments(documents);
        setFinalCaseSets(savedFinalCases);
        const latestQueue = queues.find((candidate) => candidate.status !== "CANCELLED");
        if (!latestQueue) {
          const rememberedDocumentId = window.sessionStorage.getItem(`api-test-platform.document-id.${projectId}`);
          const activeDocument = documents.find((document) => document.document_id === rememberedDocumentId) ?? documents[0] ?? null;
          setParsedDocument(activeDocument);
          if (activeDocument) {
            setDocumentText("");
            setDocumentName(activeDocument.filename);
          }
          setMessage(activeDocument
            ? `已恢复需求文档“${activeDocument.filename}”，也可以继续上传其他文档。`
            : "当前项目还没有需求文档，请先上传 Markdown 文档。");
          return;
        }
        const currentItem = latestQueue.items[Math.min(latestQueue.current_index, latestQueue.items.length - 1)];
        const [document, restoredWorkflow] = await Promise.all([
          api.requirementDocument(projectId, latestQueue.source_document_id).catch(() => null),
          currentItem?.workflow_id ? api.workflowRun(projectId, currentItem.workflow_id).catch(() => null) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const queueOperations = restoredOperations.filter((operation) => latestQueue.selected_api_ids.includes(operation.operation_id));
        setSelectedOperationIds(latestQueue.status === "READY_FOR_EXECUTION" ? [] : latestQueue.selected_api_ids.slice(0, 1));
        setSelectedOperation(queueOperations.find((operation) => operation.operation_id === currentItem?.api_operation_id) ?? queueOperations[0] ?? null);
        setQueue(latestQueue);
        setWorkflow(restoredWorkflow);
        if (document) {
          setParsedDocument(document);
          setDocumentText("");
          setDocumentName(document.filename);
          window.sessionStorage.setItem(`api-test-platform.document-id.${projectId}`, document.document_id);
        }
        setMessage(latestQueue.status === "WAITING_REQUIREMENT_APPROVAL"
          ? "已恢复刷新前的任务，请继续确认需求。"
          : "已恢复当前项目尚未完成的测试任务。");
      })
      .catch((error: Error) => {
        if (!cancelled) setMessage("当前任务恢复失败：" + error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProject?.project_id]);

  useEffect(() => {
    setProjectEditor(selectedProject ? projectEditorFrom(selectedProject) : null);
  }, [selectedProject]);

  useEffect(() => {
    setSelectedCaseIds(allFinalCases.map((item) => item.case_id));
    setApproval(null);
    setBatchApproval(null);
    setExecution(null);
    setSideEffectsConfirmed(false);
  }, [workflow?.workflow_id, finalCases?.final_case_set_id, finalCaseSets.length]);

  useEffect(() => {
    if (!selectedProject || queue?.status !== "READY_FOR_EXECUTION") return;
    let cancelled = false;
    const projectId = selectedProject.project_id;
    void api.reports(projectId)
      .then((reports) => reports
        .filter((report) => report.queue_run_id === queue.run_id)
        .sort((left, right) => Date.parse(right.generated_at) - Date.parse(left.generated_at))[0] ?? null)
      .then(async (report) => report ? { report, run: await api.run(projectId, report.run_id) } : null)
      .then((restored) => {
        if (cancelled || !restored) return;
        setExecution(restored);
        setMessage("已恢复刷新前的执行结果。");
      })
      .catch(() => {
        if (!cancelled) setExecution(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProject?.project_id, queue?.run_id, queue?.status]);

  useEffect(() => {
    setSelectedResult(null);
  }, [execution?.run.run_id]);

  function resetWorkflowContext(preserveOperations = false, preserveProjectCases = false) {
    if (!preserveOperations) setOperations([]);
    setSelectedOperation(null);
    setSelectedOperationIds([]);
    setWorkflow(null);
    setQueue(null);
    setApproval(null);
    setBatchApproval(null);
    if (!preserveProjectCases) setFinalCaseSets([]);
    setExecution(null);
    setSelectedCaseIds([]);
    setStartingWorkflow(false);
  }

  function resetRequirementContext() {
    resetWorkflowContext(true, true);
    setParsedDocument(null);
    setDocumentError("");
  }

  function rememberRequirementDocument(document: ParsedRequirementDocument) {
    setParsedDocument(document);
    setRequirementDocuments((current) => sortRequirementDocuments([
      document,
      ...current.filter((item) => item.document_id !== document.document_id),
    ]));
    if (selectedProject) {
      window.sessionStorage.setItem(`api-test-platform.document-id.${selectedProject.project_id}`, document.document_id);
    }
  }

  function selectRequirementDocument(document: ParsedRequirementDocument) {
    if (activeFlowOperationId) {
      setMessage("请先完成当前接口的用例生成，再切换需求文档。");
      return;
    }
    resetWorkflowContext(true, true);
    setParsedDocument(document);
    setDocumentText("");
    setDocumentName(document.filename);
    setDocumentError("");
    if (selectedProject) {
      window.sessionStorage.setItem(`api-test-platform.document-id.${selectedProject.project_id}`, document.document_id);
    }
    setMessage(`已切换到需求文档“${document.filename}”。`);
  }

  function operationReferencesDocument(operation: OperationContract, filename: string): boolean {
    return operation.source_refs?.some((source) => {
      const reference = source.reference ?? "";
      return reference === filename || reference.endsWith(`\\${filename}`) || reference.endsWith(`/${filename}`);
    }) ?? false;
  }

  function mapImportedOperations(document: ParsedRequirementDocument, imported: OperationContract[]): OperationContract[] {
    const candidates = imported.filter((operation) => operationReferencesDocument(operation, document.filename));
    const sourceOperations = candidates.length ? candidates : imported;
    const deduped = new Map<string, OperationContract>();
    sourceOperations.forEach((operation) => {
      const source = operation.source_refs?.[0];
      deduped.set(`${operation.method} ${operation.path}`, {
        ...operation,
        source_document_id: document.document_id,
        source_refs: [{
          source_document_id: document.document_id,
          section: operation.summary || document.filename,
          start_line: 1,
          end_line: document.line_count,
          heading: operation.summary || document.filename,
          source_text: document.content.slice(0, 20_000),
          reference: source?.reference ?? document.filename,
        }],
      });
    });
    return [...deduped.values()];
  }

  async function attachOperationContractDocument(document: ParsedRequirementDocument) {
    if (!selectedProject) {
      setParsedDocument(document);
      setDocumentText("");
      setPage("documents");
      setMessage("接口契约已解析；请选择项目后重新解析，平台会自动建立接口目录映射。");
      setParseSuccess({ filename: document.filename, documentId: document.document_id, charCount: document.char_count, lineCount: document.line_count });
      return;
    }
    setMessage(`需求文档解析完成，正在自动识别“${document.filename}”中的接口…`);
    const discovered = await api.ingestAndDiscoverRequirement(selectedProject.project_id, document.filename, document.content);
    const storedDocument = discovered.document;
    const documentOperations = operationsForDocument(discovered.operations, storedDocument.document_id);
    rememberRequirementDocument(storedDocument);
    setDocumentText("");
    setOperations(discovered.operations);
    setSelectedOperation(null);
    setSelectedOperationIds([]);
    setPage("operations");
    setMessage(`需求文档解析完成，已自动识别 ${documentOperations.length} 个可测试接口。`);
    setParseSuccess({ filename: storedDocument.filename, documentId: storedDocument.document_id, charCount: storedDocument.char_count, lineCount: storedDocument.line_count, operationCount: documentOperations.length });
  }

  async function parseTextDocument() {
    if (activeFlowOperationId) {
      setMessage("请先完成当前接口的用例生成，再上传新的需求文档。");
      return;
    }
    if (!documentText.trim()) {
      setDocumentError("请先粘贴需求文档内容。");
      return;
    }
    resetRequirementContext();
    setBusy(true);
    setDocumentError("");
    setParseSuccess(null);
    setMessage("正在解析需求文档…");
    try {
      const result = await api.parseRequirementText("pasted-requirement.md", documentText);
      if (result.detected_kind === "operation_contract") {
        await attachOperationContractDocument(result);
        return;
      }
      if (selectedProject) {
        setMessage("需求文档解析完成，正在从需求原文建立接口来源映射…");
        const discovered = await api.ingestAndDiscoverRequirement(selectedProject.project_id, result.filename, result.content);
        const documentOperations = operationsForDocument(discovered.operations, discovered.document.document_id);
        rememberRequirementDocument(discovered.document);
        setDocumentText("");
        setOperations(discovered.operations);
        setSelectedOperation(null);
        setSelectedOperationIds([]);
        setPage("operations");
        setMessage(`已从需求文档识别 ${documentOperations.length} 个可测试接口。`);
        setParseSuccess({ filename: discovered.document.filename, documentId: discovered.document.document_id, charCount: discovered.document.char_count, lineCount: discovered.document.line_count, operationCount: documentOperations.length });
        return;
      }
      setParsedDocument(result);
      setDocumentText("");
      setPage("documents");
      setMessage(`已解析“${result.filename}”，识别 ${result.sections.length} 个文档章节。`);
      setParseSuccess({ filename: result.filename, documentId: result.document_id, charCount: result.char_count, lineCount: result.line_count });
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "需求文档解析失败");
      setMessage("需求文档解析失败，请检查格式和内容。");
    } finally {
      setBusy(false);
    }
  }

  async function parseFileDocument(file: File) {
    if (activeFlowOperationId) {
      setMessage("请先完成当前接口的用例生成，再上传新的需求文档。");
      return;
    }
    resetRequirementContext();
    setBusy(true);
    setDocumentError("");
    setParseSuccess(null);
    setMessage(`正在解析文件“${file.name}”…`);
    try {
      const result = await api.parseRequirementFile(file);
      if (result.detected_kind === "operation_contract") {
        await attachOperationContractDocument(result);
        return;
      }
      if (selectedProject) {
        setMessage("需求文档解析完成，正在从需求原文建立接口来源映射…");
        const discovered = await api.ingestAndDiscoverRequirement(selectedProject.project_id, result.filename, result.content);
        const documentOperations = operationsForDocument(discovered.operations, discovered.document.document_id);
        rememberRequirementDocument(discovered.document);
        setDocumentText("");
        setOperations(discovered.operations);
        setSelectedOperation(null);
        setSelectedOperationIds([]);
        setPage("operations");
        setMessage(`已从需求文档识别 ${documentOperations.length} 个可测试接口。`);
        setParseSuccess({ filename: discovered.document.filename, documentId: discovered.document.document_id, charCount: discovered.document.char_count, lineCount: discovered.document.line_count, operationCount: documentOperations.length });
        return;
      }
      setParsedDocument(result);
      setDocumentText("");
      setPage("documents");
      setMessage(`已解析“${result.filename}”，共 ${result.char_count.toLocaleString()} 个字符。`);
      setParseSuccess({ filename: result.filename, documentId: result.document_id, charCount: result.char_count, lineCount: result.line_count });
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "需求文档解析失败");
      setMessage("需求文档解析失败，请检查文件格式。");
    } finally {
      setBusy(false);
    }
  }

  async function importOperationContract() {
    if (!selectedProject || !parsedDocument || parsedDocument.detected_kind !== "operation_contract") {
      setMessage("请先选择项目并解析接口契约。");
      return;
    }
    setBusy(true);
    try {
      await attachOperationContractDocument(parsedDocument);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "接口契约导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    if (!newProjectName.trim() || !newBaseUrl.trim()) return;
    if (newDbEnabled && (!newDbRef.trim() || splitLines(newDbTables).length === 0)) {
      setMessage("启用数据库证据时，必须填写数据库连接引用和允许读取的表名。");
      return;
    }
    setBusy(true);
    setMessage("正在创建测试项目…");
    const settings: ProjectSettings = {
      openapi_sources: splitLines(newOpenapiSource),
      source_workspace: newWorkspace.trim() || null,
      sut_target: { base_url: newBaseUrl.trim(), timeout_seconds: 10, allow_redirects: false, verify_tls: newBaseUrl.startsWith("https://"), auth_ref: null },
      auth_provider: { enabled: false, kind: "http", token_ttl_seconds: 1800, login: null, extract: { source: "json", path: "$.data" }, inject: { location: "header", name: "Authorization", prefix: "Bearer" } },
      database: { enabled: newDbEnabled, dialect: newDbEnabled ? newDbDialect : null, dsn_ref: newDbEnabled && newDbRef.trim() ? newDbRef.trim() : null, readonly: true, schema: newDbEnabled && newDbSchema.trim() ? newDbSchema.trim() : null, allowed_tables: newDbEnabled ? splitLines(newDbTables) : [] },
      llm: { enabled: true, provider: "openai_compatible", model: "deepseek-v4-flash", api_key_ref: "env:DEEPSEEK_API_KEY", base_url: "https://api.deepseek.com/v1", call_budget: 20 },
    };
    try {
      const project = await api.createProject({ name: newProjectName.trim(), description: newProjectDescription.trim(), settings });
      setProjects((current) => [...current, project]);
      setSelectedProject(project);
      setShowCreateForm(false);
      setPage("overview");
      setMessage("项目已创建。需求文档仍需在独立的“需求文档”页面解析。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setBusy(false);
    }
  }

  function startCreateProject() {
    setShowCreateForm(true);
    setPage("settings");
    setMessage("请填写新项目配置。现有项目不会被修改。");
  }

  async function saveProjectSettings() {
    if (!selectedProject || !projectEditor) return;
    setSaveSuccess(null);
    const timeoutSeconds = Number(projectEditor.timeoutSeconds);
    const tokenTtlSeconds = projectEditor.authTtlSeconds.trim() ? Number(projectEditor.authTtlSeconds) : null;
    const smsRedisPort = Number(projectEditor.authSmsRedisPort);
    if (!projectEditor.name.trim() || !projectEditor.baseUrl.trim()) {
      setMessage("项目名称和被测服务 Base URL 不能为空。");
      return;
    }
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0 || timeoutSeconds > 300) {
      setMessage("请求超时必须是 0 到 300 之间的数字。");
      return;
    }
    if (tokenTtlSeconds !== null && (!Number.isInteger(tokenTtlSeconds) || tokenTtlSeconds <= 0 || tokenTtlSeconds > 604800)) {
      setMessage("Token TTL 必须是 1 到 604800 秒之间的整数，留空可关闭自动刷新");
      return;
    }
    if (projectEditor.authKind === "sms" && (!projectEditor.authSmsPhoneRef.trim() || !projectEditor.authSmsCodePath.trim() || !Number.isInteger(smsRedisPort) || smsRedisPort < 1 || smsRedisPort > 65535)) {
      setMessage("短信验证需要手机号环境变量、验证码路径和有效的 Redis 端口");
      return;
    }
    let authQueryParams: Record<string, unknown> = {};
    let authHeaders: Record<string, string> = {};
    let authCredentialRefs: Record<string, string> = {};
    let authBody: unknown = null;
    let authSmsCodeQueryParams: Record<string, unknown> = {};
    let authSmsCodeHeaders: Record<string, string> = {};
    let authSmsCodeBody: unknown = null;
    try {
      authQueryParams = projectEditor.authQueryParams.trim() ? JSON.parse(projectEditor.authQueryParams) : {};
      authHeaders = projectEditor.authHeaders.trim() ? JSON.parse(projectEditor.authHeaders) : {};
      authCredentialRefs = projectEditor.authCredentialRefs.trim() ? JSON.parse(projectEditor.authCredentialRefs) : {};
      authBody = projectEditor.authBody.trim() ? JSON.parse(projectEditor.authBody) : null;
      authSmsCodeQueryParams = projectEditor.authSmsCodeQueryParams.trim() ? JSON.parse(projectEditor.authSmsCodeQueryParams) : {};
      authSmsCodeHeaders = projectEditor.authSmsCodeHeaders.trim() ? JSON.parse(projectEditor.authSmsCodeHeaders) : {};
      authSmsCodeBody = projectEditor.authSmsCodeBody.trim() ? JSON.parse(projectEditor.authSmsCodeBody) : null;
      if (!authQueryParams || Array.isArray(authQueryParams) || typeof authQueryParams !== "object") throw new Error("登录查询参数必须是 JSON 对象");
      if (!authHeaders || Array.isArray(authHeaders) || typeof authHeaders !== "object") throw new Error("登录请求头必须是 JSON 对象");
      if (!authCredentialRefs || Array.isArray(authCredentialRefs) || typeof authCredentialRefs !== "object") throw new Error("凭证引用必须是 JSON 对象");
      if (!authSmsCodeQueryParams || Array.isArray(authSmsCodeQueryParams) || typeof authSmsCodeQueryParams !== "object") throw new Error("短信验证码查询参数必须是 JSON 对象");
      if (!authSmsCodeHeaders || Array.isArray(authSmsCodeHeaders) || typeof authSmsCodeHeaders !== "object") throw new Error("短信验证码请求头必须是 JSON 对象");
    } catch (error) {
      setMessage(error instanceof Error ? `认证配置 JSON 无效：${error.message}` : "认证配置 JSON 无效");
      return;
    }
    if (projectEditor.databaseEnabled && (!projectEditor.databaseRef.trim() || splitLines(projectEditor.allowedTables).length === 0)) {
      setMessage("启用数据库证据时，必须填写数据库连接引用和允许读取的表名。");
      return;
    }
    const settings: ProjectSettings = {
      ...selectedProject.settings,
      openapi_sources: splitLines(projectEditor.openapiSources),
      source_workspace: projectEditor.sourceWorkspace.trim() || null,
      sut_target: {
        ...selectedProject.settings.sut_target,
        base_url: projectEditor.baseUrl.trim(),
        timeout_seconds: timeoutSeconds,
        verify_tls: projectEditor.verifyTls,
      },
      auth_provider: {
        enabled: projectEditor.authEnabled,
        kind: projectEditor.authKind,
        token_ttl_seconds: tokenTtlSeconds,
        login: projectEditor.authKind === "http" ? {
          method: projectEditor.authLoginMethod.trim() || "POST",
          path: projectEditor.authLoginPath.trim(),
          body_type: projectEditor.authBodyType,
          query_params: authQueryParams,
          headers: authHeaders,
          body: authBody,
          credential_refs: authCredentialRefs,
        } : null,
        extract: { source: projectEditor.authExtractSource, path: projectEditor.authExtractPath.trim() || "$.data" },
        inject: { location: projectEditor.authInjectLocation, name: projectEditor.authInjectName.trim() || "Authorization", prefix: projectEditor.authInjectPrefix.trim() || null },
        sms: {
          phone_ref: projectEditor.authSmsPhoneRef.trim(),
          code_request: {
            method: projectEditor.authSmsCodeMethod.trim() || "POST",
            path: projectEditor.authSmsCodePath.trim(),
            body_type: projectEditor.authSmsCodeBodyType,
            query_params: authSmsCodeQueryParams,
            headers: authSmsCodeHeaders,
            body: authSmsCodeBody,
            credential_refs: {},
          },
          code_source: projectEditor.authSmsCodeSource,
          code_path: (projectEditor.authSmsCodeSource === "redis" ? projectEditor.authSmsRedisKey : projectEditor.authSmsCodeExtractPath).trim(),
          redis_host: projectEditor.authSmsRedisHost.trim() || "127.0.0.1",
          redis_port: smsRedisPort,
          redis_password_ref: projectEditor.authSmsRedisPasswordRef.trim() || null,
          login: {
            method: projectEditor.authLoginMethod.trim() || "POST",
            path: projectEditor.authLoginPath.trim(),
            body_type: projectEditor.authBodyType,
            query_params: authQueryParams,
            headers: authHeaders,
            body: authBody,
            credential_refs: authCredentialRefs,
          },
        },
      },
      database: {
        enabled: projectEditor.databaseEnabled,
        dialect: projectEditor.databaseEnabled ? projectEditor.databaseDialect : null,
        dsn_ref: projectEditor.databaseEnabled ? projectEditor.databaseRef.trim() : null,
        readonly: true,
        schema: projectEditor.databaseEnabled && projectEditor.databaseSchema.trim() ? projectEditor.databaseSchema.trim() : null,
        allowed_tables: projectEditor.databaseEnabled ? splitLines(projectEditor.allowedTables) : [],
      },
    };
    setBusy(true);
    setMessage("正在保存当前项目设置…");
    try {
      const updated = await api.updateProject(selectedProject.project_id, {
        name: projectEditor.name.trim(),
        description: projectEditor.description.trim(),
        settings,
      });
      setProjects((current) => current.map((project) => project.project_id === updated.project_id ? updated : project));
      setSelectedProject(updated);
      setBaseUrl(updated.settings.sut_target.base_url);
      let authSuccess = true;
      let authMessage = projectEditor.authEnabled
        ? "正在执行鉴权预检"
        : "项目未启用可配置鉴权，未执行 Token 预检";
      if (projectEditor.authEnabled) {
        try {
          const authResult = await api.refreshProjectAuth(updated.project_id);
          authSuccess = authResult.success;
          authMessage = authResult.message;
        } catch (error) {
          authSuccess = false;
          authMessage = error instanceof Error ? error.message : "Token 预检请求失败";
        }
      }
      setMessage(authSuccess
        ? `项目“${updated.name}”设置已保存，鉴权预检成功。`
        : `项目“${updated.name}”设置已保存，但 Token 获取失败：${authMessage}`);
      setSaveSuccess({ name: updated.name, authSuccess, authMessage });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存项目设置失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedProject() {
    if (!selectedProject) return;
    const projectToDelete = selectedProject;
    if (!window.confirm(`确定从项目列表删除“${projectToDelete.name}”吗？删除后平台将不再加载该项目。`)) return;
    setBusy(true);
    setMessage(`正在删除项目“${projectToDelete.name}”…`);
    try {
      await api.deleteProject(projectToDelete.project_id);
      const remaining = projects.filter((project) => project.project_id !== projectToDelete.project_id);
      setProjects(remaining);
      setSelectedProject(remaining[0] ?? null);
      setShowCreateForm(remaining.length === 0);
      setPage(remaining.length === 0 ? "settings" : "overview");
      setMessage(remaining.length ? "项目已删除，已切换到其他项目。" : "项目已删除，可以创建新的测试项目。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除项目失败");
    } finally {
      setBusy(false);
    }
  }

  async function discoverOperations() {
    if (!selectedProject) return;
    setBusy(true);
    setMessage("正在读取 OpenAPI 与接口契约…");
    try {
      const result = await api.discoverOperations(selectedProject.project_id);
      setOperations(result.operations);
      setPage("operations");
      setMessage(`已发现 ${result.operations.length} 个可测试接口。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "接口发现失败");
    } finally {
      setBusy(false);
    }
  }

  async function waitForQueueSettled(projectId: string, runId: string, maxAttempts = 90): Promise<ApiProcessingQueue | null> {
    let latest: ApiProcessingQueue | null = null;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      latest = await api.processingQueue(projectId, runId);
      if (!["PENDING", "RUNNING"].includes(latest.status)) return latest;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    return latest;
  }

  function selectOperation(operation: OperationContract) {
    if (!activeFlowOperationId && selectedOperationIds.includes(operation.operation_id)) {
      setSelectedOperation(null);
      setSelectedOperationIds([]);
      setMessage(`已取消选择 ${operation.method} ${operation.path}。`);
      return;
    }
    if (activeFlowOperationId && activeFlowOperationId !== operation.operation_id) {
      setMessage("请先完成当前接口的用例生成，再选择下一个接口。");
      return;
    }
    if (completedOperationIds.has(operation.operation_id)) {
      setMessage("该接口已经生成测试用例，可以在“测试用例”页面查看。");
      return;
    }
    // Keep accumulated cases, but clear the previous API's transient queue,
    // approval and report state before starting another API.
    setQueue(null);
    setWorkflow(null);
    setApproval(null);
    setBatchApproval(null);
    setExecution(null);
    setStartingWorkflow(false);
    const sourceDocumentId = operation.source_document_id
      ?? operation.source_refs?.find((source) => source.source_document_id)?.source_document_id;
    const sourceDocument = requirementDocuments.find(
      (document) => document.document_id === sourceDocumentId,
    ) ?? null;
    if (sourceDocument) {
      setParsedDocument(sourceDocument);
      setDocumentName(sourceDocument.filename);
      setDocumentText("");
      if (selectedProject) {
        window.sessionStorage.setItem(
          `api-test-platform.document-id.${selectedProject.project_id}`,
          sourceDocument.document_id,
        );
      }
    }
    setSelectedOperation(operation);
    setSelectedOperationIds([operation.operation_id]);
    setPage(sourceDocument || parsedDocument ? "operations" : "documents");
    setMessage(sourceDocument || parsedDocument ? `已选择 ${operation.method} ${operation.path}。` : "已选择接口，请先解析原始需求文档。");
  }

  async function runWorkflow() {
    const operationIds = selectedOperationIds.length ? selectedOperationIds : selectedOperation ? [selectedOperation.operation_id] : [];
    if (!selectedProject) {
      setMessage("请先选择项目，再启动顺序分析。");
      return;
    }
    if (!parsedDocument) {
      setMessage("请先在“需求文档”页面完成解析，当前页面不会自动跳转。");
      return;
    }
    if (operationIds.length !== 1) {
      setMessage("每次请选择 1 个尚未生成用例的接口。");
      return;
    }
    if (completedOperationIds.has(operationIds[0])) {
      setSelectedOperationIds([]);
      setMessage("该接口已经生成测试用例，请选择其他接口。");
      return;
    }
    setBusy(true);
    setStartingWorkflow(true);
    setWorkflow(null);
    setApproval(null);
    setBatchApproval(null);
    setExecution(null);
    setQueue(null);
    setPage("requirements");
    setMessage("正在为当前接口创建分析任务…");
    let createdQueue: ApiProcessingQueue | null = null;
    try {
      let activeDocument = parsedDocument;
      let activeOperations = operations;
      const selectedOperations = operationIds.map((operationId) => operations.find((operation) => operation.operation_id === operationId));
      const needsDocumentDiscovery = activeDocument.detected_kind !== "operation_contract" && (activeDocument.project_id !== selectedProject.project_id || selectedOperations.some((operation) => operation?.source_document_id !== activeDocument.document_id));
      if (needsDocumentDiscovery) {
        setMessage("正在保存需求文档并重新建立接口索引…");
        const discovered = await api.ingestAndDiscoverRequirement(selectedProject.project_id, activeDocument.filename, activeDocument.content);
        activeDocument = discovered.document;
        activeOperations = discovered.operations;
        rememberRequirementDocument(discovered.document);
        setDocumentText("");
        setOperations(discovered.operations);
      }
      const validOperationIds = operationIds.filter((operationId) => activeOperations.some((operation) => operation.operation_id === operationId));
      if (!validOperationIds.length) {
        setPage("operations");
        setMessage("当前需求文档中没有找到已选择的接口，请在接口目录重新选择原始需求文档中的 API。");
        return;
      }
      createdQueue = await api.createProcessingQueue(selectedProject.project_id, activeDocument.document_id, validOperationIds);
      setQueue(createdQueue);
      setMessage(`分析任务已创建，正在提取第 1 / ${validOperationIds.length} 个接口的需求与测试点…`);
      const started = await api.startProcessingQueue(selectedProject.project_id, createdQueue.run_id);
      setQueue(started.queue);
      setWorkflow(started.workflow);
      setSelectedOperation(activeOperations.find((item) => item.operation_id === started.queue.items[started.queue.current_index]?.api_operation_id) ?? selectedOperation);
      setSelectedOperationIds(validOperationIds);
      setPage("requirements");
      setMessage(`已启动顺序处理：第 1 / ${validOperationIds.length} 个接口等待需求确认。`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "分析任务执行失败";
      if (createdQueue) {
        setMessage("页面等待超时，正在同步后台分析状态…");
        const settledQueue = await waitForQueueSettled(selectedProject.project_id, createdQueue.run_id).catch(() => null);
        if (settledQueue) {
          setQueue(settledQueue);
          const currentItem = settledQueue.items[settledQueue.current_index];
          if (settledQueue.status === "WAITING_REQUIREMENT_APPROVAL" && currentItem?.workflow_id) {
            const settledWorkflow = await api.workflowRun(selectedProject.project_id, currentItem.workflow_id).catch(() => null);
            if (settledWorkflow) {
              setWorkflow(settledWorkflow);
              setSelectedOperation(operations.find((item) => item.operation_id === currentItem.api_operation_id) ?? selectedOperation);
              setPage("requirements");
              setMessage("需求与测试点已生成，请确认后继续。");
              return;
            }
          }
          if (settledQueue.status === "FAILED") {
            setPage("requirements");
            setMessage(`顺序分析失败：${settledQueue.items[settledQueue.current_index]?.error_message ?? detail}。`);
            return;
          }
          setPage("requirements");
          setMessage("后端仍在处理当前队列，页面已保留在当前节点，请稍后刷新查看结果。");
          return;
        }
        setPage("requirements");
        setMessage(`暂时无法同步队列状态：${detail}。队列已保留在当前节点，请稍后刷新。`);
      } else {
        setMessage(detail);
        setPage("operations");
      }
    } finally {
      setBusy(false);
      setStartingWorkflow(false);
    }
  }

  async function retryWorkflowQueue() {
    if (!selectedProject || !queue) return;
    setBusy(true);
    setStartingWorkflow(true);
    setMessage("正在重新分析当前接口的需求…");
    try {
      const started = await api.startProcessingQueue(selectedProject.project_id, queue.run_id);
      setQueue(started.queue);
      setWorkflow(started.workflow);
      setPage("requirements");
      setMessage("当前接口已重新生成需求，请确认后继续。");
    } catch (error) {
      setMessage(`重试失败：${error instanceof Error ? error.message : "分析任务执行失败"}`);
    } finally {
      setBusy(false);
      setStartingWorkflow(false);
    }
  }

  function selectProject(project: TestProject) {
    setSelectedProject(project);
    setSelectedOperation(null);
    setSelectedOperationIds([]);
    setQueue(null);
    setFinalCaseSets([]);
    setWorkflow(null);
    setApproval(null);
    setExecution(null);
    setStartingWorkflow(false);
    setPage((current) => current === "settings" ? "settings" : "overview");
    setMessage(`已切换到项目“${project.name}”。`);
  }

  function toggleCase(caseId: string) {
    setSelectedCaseIds((current) => current.includes(caseId) ? current.filter((id) => id !== caseId) : [...current, caseId]);
  }

  function toggleAllCases() {
    const ids = allFinalCases.map((item) => item.case_id);
    setSelectedCaseIds((current) => current.length === ids.length ? [] : ids);
  }

  function toggleOperation(operationId: string) {
    const operation = operations.find((item) => item.operation_id === operationId);
    if (operation) selectOperation(operation);
  }

  async function approveCurrentRequirement() {
    if (!selectedProject || !queue || !workflow?.requirement) return;
    setBusy(true);
    setMessage("正在确认当前接口的需求与测试点，随后自动设计并检查用例…");
    try {
      const accepted = await api.approveCurrentRequirement(selectedProject.project_id, queue.run_id, {
        requirement_id: workflow.requirement.requirement_id,
        requirement_version: workflow.requirement.version,
      });
      setQueue(accepted.queue);
      setWorkflow(accepted.workflow);
      setMessage("需求已确认，正在后台设计并检查用例；页面仍可正常响应…");
      const settledQueue = await waitForQueueSettled(
        selectedProject.project_id,
        accepted.queue.run_id,
        600,
      );
      if (!settledQueue || ["PENDING", "RUNNING"].includes(settledQueue.status)) {
        setPage("requirements");
        setMessage("后台仍在设计用例，任务已保留；稍后刷新即可查看结果。");
        return;
      }
      setQueue(settledQueue);
      const currentItem = settledQueue.items[settledQueue.current_index];
      const currentOperationId = currentItem?.api_operation_id;
      setSelectedOperation(operations.find((item) => item.operation_id === currentOperationId) ?? selectedOperation);
      if (settledQueue.status === "READY_FOR_EXECUTION") {
        const cases = await api.projectFinalCases(selectedProject.project_id);
        setFinalCaseSets(cases);
        setSelectedCaseIds(cases.flatMap((item) => item.cases).map((item) => item.case_id));
        setSelectedOperationIds([]);
        setSelectedOperation(null);
        setPage("cases");
        setMessage("当前接口的测试用例已生成并加入项目用例库，可以继续选择下一个接口。");
      } else if (settledQueue.status === "WAITING_REQUIREMENT_APPROVAL" && currentItem?.workflow_id) {
        const nextWorkflow = await api.workflowRun(selectedProject.project_id, currentItem.workflow_id);
        setWorkflow(nextWorkflow);
        setPage("requirements");
        setMessage(`当前接口已完成，下一接口等待需求确认（${settledQueue.current_index + 1} / ${settledQueue.items.length}）。`);
      } else if (settledQueue.status === "BLOCKED" && currentItem?.workflow_id) {
        const blockedWorkflow = await api.workflowRun(selectedProject.project_id, currentItem.workflow_id);
        setWorkflow(blockedWorkflow);
        setPage("requirements");
        setMessage(`用例已保留，但存在需要人工处理的缺口：${currentItem.error_message ?? "请查看下方详情"}`);
      } else if (settledQueue.status === "FAILED") {
        setPage("requirements");
        setMessage(`用例设计与检查失败：${currentItem?.error_message ?? "后台任务失败"}`);
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : "需求确认失败";
      const latestQueue = await api.processingQueue(selectedProject.project_id, queue.run_id).catch(() => null);
      if (latestQueue) setQueue(latestQueue);
      setPage("requirements");
      setMessage(
        latestQueue?.status === "FAILED"
          ? `用例设计与检查失败：${latestQueue.items[latestQueue.current_index]?.error_message ?? detail}`
          : detail,
      );
    } finally {
      setBusy(false);
    }
  }

  async function approveForExecution() {
    if (!selectedProject || !selectedCaseIds.length) return;
    setBusy(true);
    try {
      const result = await api.approveProjectExecution(selectedProject.project_id, {
        target_environment: targetEnvironment,
        base_url: baseUrl,
        case_ids: selectedCaseIds,
        case_count: selectedCaseIds.length,
        side_effect_case_ids: sideEffectCaseIds,
        side_effects_confirmed: sideEffectsConfirmed,
        auto_regression_allowed: true,
      });
      setBatchApproval(result);
      setPage("execution");
      setMessage(`已确认 ${result.selected_case_count} 条用例，可以开始批量执行。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "人工确认失败");
    } finally {
      setBusy(false);
    }
  }

  async function executeApproved(autoRegression = false) {
    if (!selectedProject || !batchApproval) return;
    setBusy(true);
    setMessage(autoRegression ? "正在执行已批准且 需求未变化的自动回归…" : "正在一次性批量执行已确认用例…");
    try {
      const result = autoRegression ? await api.autoRegressBatch(selectedProject.project_id, batchApproval.approval_id) : await api.executeBatch(selectedProject.project_id, batchApproval.approval_id);
      setExecution(result);
      setPage("reports");
      setMessage(`执行完成：${result.run.passed_count} 条 PASS，${result.run.failed_count} 条 FAIL，${result.run.error_count} 条错误。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "执行失败");
    } finally {
      setBusy(false);
    }
  }

  function exportReportHtml() {
    if (!execution) return;
    const caseTitles = new Map(allFinalCases.map((item) => [item.case_id, item.title]));
    const resultSections = execution.run.results.map((result) => {
      const passedAssertions = result.assertion_results.filter((assertion) => assertion.passed).length;
      const assertionRows = result.assertion_results.length
        ? result.assertion_results.map((assertion) => `<tr>
            <td><span class="state ${assertion.passed ? "pass" : "fail"}">${assertion.passed ? "PASS" : "FAIL"}</span></td>
            <td><code>${escapeHtml(assertionTarget(assertion.type, assertion.path))}</code></td>
            <td><code>${escapeHtml(assertion.operator || "默认相等")}</code></td>
            <td><pre>${escapeHtml(assertion.expected)}</pre></td>
            <td><pre>${escapeHtml(assertion.actual)}</pre></td>
            <td>${escapeHtml(assertion.message)}</td>
          </tr>`).join("")
        : `<tr><td colspan="6" class="empty">该用例没有断言结果</td></tr>`;
      return `<section class="case-card">
        <div class="case-heading">
          <div><h2>${escapeHtml(result.case_title ?? caseTitles.get(result.case_id) ?? result.case_id)}</h2><code>${escapeHtml(result.case_id)}</code></div>
          <span class="state ${result.status === "passed" ? "pass" : "fail"}">${escapeHtml(statusText(result.status))}</span>
        </div>
        <div class="case-meta">
          <div><span>请求</span><strong>${escapeHtml(result.method)} ${escapeHtml(requestPath(result.url))}</strong></div>
          <div><span>HTTP 状态</span><strong>${escapeHtml(result.status_code ?? "—")}</strong></div>
          <div><span>耗时</span><strong>${result.duration_ms == null ? "—" : `${result.duration_ms.toFixed(1)} ms`}</strong></div>
          <div><span>断言</span><strong>${passedAssertions} / ${result.assertion_results.length} 通过</strong></div>
        </div>
        ${result.error_message ? `<div class="error"><strong>${escapeHtml(result.error_category ?? "执行错误")}</strong><p>${escapeHtml(result.error_message)}</p></div>` : ""}
        <table><thead><tr><th>结果</th><th>断言字段</th><th>运算符</th><th>期望值</th><th>实际值</th><th>说明</th></tr></thead><tbody>${assertionRows}</tbody></table>
        <details><summary>响应 Body</summary><pre>${escapeHtml(result.response_body)}</pre></details>
      </section>`;
    }).join("");
    const title = `${selectedProject?.name ?? "API 自动化测试"} · 测试报告`;
    const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
*{box-sizing:border-box}body{margin:0;color:#142b49;background:#f3f6fa;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}.page{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}.hero,.case-card{background:#fff;border:1px solid #dce4ef;border-radius:14px}.hero{padding:28px}.hero h1{margin:5px 0 6px;font-size:28px}.muted,.hero p{color:#718198}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:22px}.metric{padding:16px;border:1px solid #e2e8f0;border-radius:10px}.metric span{display:block;color:#8190a4;font-size:12px}.metric strong{display:block;margin-top:6px;font-size:25px}.pass-text{color:#14805e}.fail-text{color:#cf4141}.case-card{padding:22px;margin-top:16px;overflow:hidden}.case-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.case-heading h2{margin:0 0 5px;font-size:18px}.case-heading code,.case-meta code{color:#64748b}.state{display:inline-block;padding:4px 9px;border-radius:999px;font-weight:800;font-size:12px}.state.pass{color:#14805e;background:#e9f8f2}.state.fail{color:#c83d3d;background:#fff0f0}.case-meta{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:10px;margin:18px 0}.case-meta div{padding:11px;background:#f8fafc;border:1px solid #e7ecf2;border-radius:8px}.case-meta span,.case-meta strong{display:block}.case-meta span{color:#8190a4;font-size:11px}.case-meta strong{margin-top:4px;overflow-wrap:anywhere}.error{margin:14px 0;padding:12px;color:#a93434;background:#fff5f5;border-left:3px solid #d94b4b}.error p{margin:4px 0 0}table{width:100%;border-collapse:collapse;margin-top:12px;font-size:12px}th,td{padding:10px;text-align:left;vertical-align:top;border:1px solid #e2e8f0}th{color:#66758a;background:#f7f9fc}td pre,details pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12px/1.55 Consolas,"Microsoft YaHei",monospace}.empty{text-align:center;color:#8190a4}details{margin-top:14px;padding-top:12px;border-top:1px solid #e2e8f0}summary{cursor:pointer;font-weight:700}details>pre{max-height:360px;overflow:auto;margin-top:10px;padding:12px;background:#f8fafc;border-radius:8px}@media(max-width:760px){.summary,.case-meta{grid-template-columns:1fr 1fr}.page{width:min(100% - 20px,1180px)}.hero,.case-card{padding:16px}table{display:block;overflow-x:auto}}@media print{body{background:#fff}.page{width:100%;margin:0}.hero,.case-card{break-inside:avoid;border-color:#bbb}.case-card{margin-top:12px}details>pre{max-height:none}}
</style></head><body><main class="page">
<section class="hero"><span class="muted">基于 Multi-Agent 的接口自动化测试平台</span><h1>${escapeHtml(title)}</h1><p>生成时间：${escapeHtml(formatDate(execution.report.generated_at))}　·　Run ID：${escapeHtml(execution.run.run_id)}　·　环境：${escapeHtml(execution.run.target_environment ?? "local")}</p>
<div class="summary"><div class="metric"><span>总用例</span><strong>${execution.report.total_cases}</strong></div><div class="metric"><span>PASS</span><strong class="pass-text">${execution.report.passed_cases}</strong></div><div class="metric"><span>FAIL</span><strong class="fail-text">${execution.report.failed_cases}</strong></div><div class="metric"><span>断言失败</span><strong class="fail-text">${execution.report.assertion_failures} / ${execution.report.assertion_total}</strong></div></div></section>
${resultSections}</main></body></html>`;
    const blobUrl = window.URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a");
    const projectName = (selectedProject?.name ?? "api-test").replace(/[\\/:*?"<>|]+/g, "-").trim() || "api-test";
    const timestamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
    link.href = blobUrl;
    link.download = `${projectName}-测试报告-${timestamp}.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(blobUrl);
    setMessage("测试报告已导出为 HTML 文件。");
  }

  function renderProjectEmpty() {
    return <section className="empty-card empty-card-large"><div className="empty-mark">项目</div><h3>还没有测试项目</h3><p>需求文档可以先独立解析；如需读取源码、数据库和接口契约，再创建一个测试项目作为辅助证据上下文。</p><button className="button button-primary" onClick={() => setShowCreateForm(true)}>创建测试项目</button></section>;
  }

  function renderCreateForm() {
    return <section className="card form-card">
      <div className="card-heading">
        <div><span className="kicker">项目配置</span><h3>创建测试项目</h3><p className="form-subtitle">配置被测服务和可选证据来源，需求文档仍在独立页面上传。</p></div>
        <button className="button button-ghost" onClick={() => setShowCreateForm(false)}>取消</button>
      </div>
      <div className="form-grid">
        <label>项目名称<input value={newProjectName} onChange={(event) => setNewProjectName(event.target.value)} placeholder="例如：订单服务 API 测试" /></label>
        <label>被测服务 Base URL<input value={newBaseUrl} onChange={(event) => setNewBaseUrl(event.target.value)} placeholder="http://127.0.0.1:8081" /></label>
        <label className="field-wide">项目说明<textarea value={newProjectDescription} onChange={(event) => setNewProjectDescription(event.target.value)} rows={2} /></label>
        <label>接口描述来源（可选）<textarea value={newOpenapiSource} onChange={(event) => setNewOpenapiSource(event.target.value)} placeholder="每行一个本地文件或 URL" rows={3} /></label>
        <label>源码工作区路径（可选）<input value={newWorkspace} onChange={(event) => setNewWorkspace(event.target.value)} placeholder="例如：D:\\workspace\\your-service" /></label>
        <label>数据库连接引用<input value={newDbRef} onChange={(event) => setNewDbRef(event.target.value)} placeholder="例如：env:TEST_DB_DSN" disabled={!newDbEnabled} /></label>
        <label>数据库类型<select value={newDbDialect} onChange={(event) => setNewDbDialect(event.target.value)} disabled={!newDbEnabled}><option value="mysql">MySQL</option><option value="postgresql">PostgreSQL</option><option value="sqlite">SQLite</option></select></label>
        <label>数据库 Schema（可选）<input value={newDbSchema} onChange={(event) => setNewDbSchema(event.target.value)} placeholder="例如：public" disabled={!newDbEnabled} /></label>
        <label>允许读取的表<textarea value={newDbTables} onChange={(event) => setNewDbTables(event.target.value)} placeholder="每行一个表名，例如：example_table" rows={3} disabled={!newDbEnabled} /></label>
      </div>
      <label className="switch-row"><input type="checkbox" checked={newDbEnabled} onChange={(event) => setNewDbEnabled(event.target.checked)} /><span><strong>启用数据库真实夹具</strong><small>模型选择夹具令牌，真实 ID 由后端只读查询并在本地替换，不发送给模型。</small></span></label>
      <div className="form-note">连接信息必须使用环境变量引用（如 env:TEST_DB_DSN）；平台只读取白名单表的标识字段，不展示数据库连接串。</div>
      <div className="form-actions"><button className="button button-primary" onClick={createProject} disabled={busy || !newProjectName.trim() || !newBaseUrl.trim()}>保存项目</button></div>
    </section>;
  }

  function renderDocumentsLegacy() {
    return <><div className="page-heading"><div><span className="kicker">开始测试</span><h2>需求文档解析</h2><p>上传面向接口的需求文档，平台会提取业务规则、接口行为和异常场景。源码与数据库仅作为可选辅助证据。</p></div><span className="status-badge status-ready">独立入口</span></div><div className="document-layout"><section className="card document-input-card"><div className="card-heading"><div><span className="kicker">输入文档</span><h3>上传文件或粘贴内容</h3></div><span className="help-text">单文件最大 10 MB</span></div><label className="document-drop"><input type="file" accept=".pdf,.docx,.md,.markdown,.txt,.rst,.html,.htm,.json,.yaml,.yml" onChange={(event) => { const file = event.target.files?.[0]; if (file) void parseFileDocument(file); }} /><span className="drop-title">选择需求文档文件</span><span className="drop-copy">PDF · DOCX · Markdown · TXT · HTML · JSON · YAML</span></label><div className="document-divider"><span>或直接粘贴</span></div><label className="document-name">文档名称<input value={documentName} onChange={(event) => setDocumentName(event.target.value)} placeholder="例如：店铺详情接口需求.md" /></label><textarea className="document-textarea" value={documentText} onChange={(event) => { setDocumentText(event.target.value); if (parsedDocument) { resetRequirementContext(); setMessage("需求文档已修改，请重新解析；旧接口和旧分析结果已清空。"); } }} placeholder="粘贴需求背景、业务规则、接口行为、异常场景等内容…" maxLength={500000} /><div className="document-footer"><span>{documentText.length.toLocaleString()} / 500,000 字符</span><button className="button button-primary" onClick={parseTextDocument} disabled={busy || !documentText.trim()}>{busy ? "解析中…" : "解析需求文档"}</button></div>{documentError && <div className="callout callout-danger">{documentError}</div>}</section><section className="document-side"><section className="card"><div className="card-heading"><div><span className="kicker">解析能力</span><h3>支持的文档格式</h3></div></div><div className="format-list"><span>PDF</span><span>DOCX</span><span>Markdown</span><span>TXT</span><span>HTML</span><span>JSON</span><span>YAML</span></div><p className="card-copy">解析服务会统一提取可读文本、章节标题、行号和文档摘要，后续步骤使用规范化内容，不直接依赖原始文件扩展名。若检测到接口契约，会引导你导入接口目录。</p></section><section className="card"><div className="card-heading"><div><span className="kicker">后续流程</span><h3>解析完成后继续</h3></div></div><div className="document-context"><div><span>当前项目</span><strong>{selectedProject?.name ?? "尚未选择项目"}</strong></div><div><span>当前接口</span><strong>{selectedOperation ? `${selectedOperation.method} ${selectedOperation.path}` : "尚未选择接口"}</strong></div></div>{!selectedProject && <p className="context-hint">需求文档解析不依赖项目；开始测试分析前，请先创建或选择项目。</p>}{!selectedOperationIds.length && <button className="button button-secondary full-button" onClick={() => setPage("operations")}>去接口目录选择接口</button>}{parsedDocument?.detected_kind === "operation_contract" && selectedProject && <button className="button button-primary full-button" onClick={() => void importOperationContract()} disabled={busy}>{busy ? "导入中…" : "导入到当前项目接口目录"}</button>}{parsedDocument?.detected_kind !== "operation_contract" && parsedDocument && selectedProject && selectedOperationIds.length > 0 && <button className="button button-primary full-button" onClick={() => void runWorkflow()} disabled={busy}>{busy ? "分析中…" : `开始顺序分析（${selectedOperationIds.length} 个接口）`}</button>}</section></section></div>{parsedDocument && <section className="card parsed-document-card"><div className="card-heading"><div><span className="kicker">解析结果</span><h3>{parsedDocument.filename}</h3></div><span className={`status-badge ${parsedDocument.detected_kind === "operation_contract" ? "status-warning" : "status-ready"}`}>{parsedDocument.detected_kind === "operation_contract" ? "接口契约" : "解析成功"}</span></div>{parsedDocument.detected_kind === "operation_contract" && <div className="callout callout-info"><strong>输入类型已识别</strong><p>这个文件描述 API 接口（请求方法、路径、请求和响应），不是业务需求文档。选择项目后可直接导入接口目录；业务需求请另行上传。</p>{selectedProject && <button className="button button-small button-secondary" onClick={() => void importOperationContract()} disabled={busy}>导入当前项目</button>}</div>}<div className="parsed-meta"><div><span>格式</span><strong>{parsedDocument.format.toUpperCase()}</strong></div><div><span>字符数</span><strong>{parsedDocument.char_count.toLocaleString()}</strong></div><div><span>行数</span><strong>{parsedDocument.line_count.toLocaleString()}</strong></div><div><span>章节</span><strong>{parsedDocument.sections.length}</strong></div><div><span>文档编号</span><code>{parsedDocument.document_id}</code></div></div>{parsedDocument.warnings.filter((warning) => !warning.includes("检测到这是 API 接口契约")).map((warning) => <div className="callout callout-warning" key={warning}>{warning}</div>)}<details className="parsed-preview"><summary>查看规范化文本</summary><pre>{parsedDocument.content.slice(0, 12000)}{parsedDocument.content.length > 12000 ? "\n…（预览已截断）" : ""}</pre></details></section>}</>;
  }

  function renderDocuments() {
    return <>
      <div className="page-heading">
        <div><span className="kicker">开始测试</span><h2>需求文档解析</h2><p>上传面向接口的需求文档，平台会提取业务规则、接口行为和异常场景。源码与数据库仅作为可选辅助证据。</p></div>
        <span className="status-badge status-ready">独立入口</span>
      </div>
      <div className="document-layout">
        <section className="card document-input-card">
          <div className="card-heading"><div><span className="kicker">输入文档</span><h3>上传文件或粘贴内容</h3></div><span className="help-text">单文件最大 10 MB</span></div>
          <label className="document-drop"><input type="file" accept=".md,.markdown" disabled={Boolean(activeFlowOperationId)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void parseFileDocument(file); }} /><span className="drop-title">选择需求文档文件</span><span className="drop-copy">Markdown</span></label>
          <div className="document-divider"><span>或直接粘贴</span></div>
          <textarea className="document-textarea" value={documentText} disabled={Boolean(activeFlowOperationId)} onChange={(event) => { setDocumentText(event.target.value); if (parsedDocument) { resetRequirementContext(); setMessage("正在输入新的需求内容；已上传的文档仍会保留。"); } }} placeholder="粘贴需求背景、业务规则、接口行为、异常场景等内容…" maxLength={500000} />
          <div className="document-footer"><span>{documentText.length.toLocaleString()} / 500,000 字符</span><button className="button button-primary" onClick={parseTextDocument} disabled={busy || Boolean(activeFlowOperationId) || !documentText.trim()}>{busy ? "解析中…" : "解析需求文档"}</button></div>
          {documentError && <div className="callout callout-danger">{documentError}</div>}
        </section>
        <section className="document-side">
          <section className="card"><div className="card-heading"><div><span className="kicker">解析能力</span><h3>支持的文档格式</h3></div></div><div className="format-list"><span>Markdown</span></div><p className="card-copy">解析服务会提取 Markdown 原文、章节标题、行号和文档摘要。解析完成后，平台会自动识别接口并映射到接口目录。</p></section>
        </section>
      </div>
      {selectedProject && requirementDocuments.length > 0 && <section className="card document-library">
        <div className="card-heading">
          <div><span className="kicker">项目文档</span><h3>已上传需求文档</h3></div>
          <span className="status-badge status-neutral">共 {requirementDocuments.length} 份</span>
        </div>
        <div className="document-library-list">
          {requirementDocuments.map((document) => {
            const active = document.document_id === parsedDocument?.document_id;
            const operationCount = operationsForDocument(operations, document.document_id).length;
            return <button
              type="button"
              className={`document-library-item ${active ? "is-active" : ""}`}
              key={document.document_id}
              onClick={() => selectRequirementDocument(document)}
            >
              <span className="document-library-main">
                <strong title={document.filename}>{document.filename}</strong>
                <small>{document.format.toUpperCase()} · {document.line_count.toLocaleString()} 行 · {operationCount} 个接口</small>
              </span>
              <span className="document-library-side">
                <small>{formatDate(document.updated_at ?? document.created_at)}</small>
                <span className={`status-badge ${active ? "status-ready" : "status-neutral"}`}>{active ? "当前文档" : "选择"}</span>
              </span>
            </button>;
          })}
        </div>
      </section>}
    </>;
  }

  function renderOverview() {
    if (showCreateForm) return renderCreateForm();
    if (!selectedProject) return renderProjectEmpty();
    return <><div className="page-heading"><div><span className="kicker">工作台</span><h2>项目概览</h2><p>需求文档是主输入，项目配置只为后续证据检索和确定性执行提供上下文。</p></div><button className="button button-primary" onClick={() => setPage("documents")}>解析需求文档</button></div><div className="stats-grid stats-grid-three"><div className="metric-card"><span>可测试接口</span><strong>{operations.length}</strong><small>从需求文档识别</small></div><div className="metric-card"><span>当前需求文档</span><strong>{parsedDocument ? "已解析" : "—"}</strong><small>{parsedDocument?.filename ?? "尚未导入文档"}</small></div><div className="metric-card"><span>项目用例</span><strong>{allFinalCases.length}</strong><small>{finalCaseSets.length ? `已完成 ${finalCaseSets.length} 个接口` : "尚未设计"}</small></div></div><div className="overview-grid"><section className="card workflow-card"><div className="card-heading"><div><span className="kicker">当前流程</span><h3>{selectedOperation ? `${selectedOperation.method} ${selectedOperation.path}` : "还未选择接口"}</h3></div><span className={`status-badge ${finalCases ? "status-ready" : "status-neutral"}`}>{finalCases ? statusText(finalCases.status) : parsedDocument ? "文档已解析" : "待开始"}</span></div><div className="mini-flow">{workflowSteps.slice(0, 5).map((step, index) => <span className={index <= currentStep ? "done" : ""} key={step}>{step}</span>)}</div><p className="card-copy">按“文档解析 → 接口选择 → 需求确认 → 用例设计 → 执行确认 → 测试报告”完成一次测试。</p><button className="button button-secondary" onClick={() => setPage(parsedDocument ? (selectedOperation ? "requirements" : "operations") : "documents")}>{parsedDocument ? (selectedOperation ? "查看当前进度" : "选择接口") : "开始解析需求文档"}</button></section><section className="card quick-card"><div className="card-heading"><div><span className="kicker">快速操作</span><h3>下一步做什么</h3></div></div><button className="quick-action" onClick={() => setPage("documents")}><span>解析需求文档</span><small>上传或粘贴多格式需求</small></button><button className="quick-action" onClick={() => setPage("operations")}><span>选择待测接口</span><small>关联接口契约与辅助证据</small></button><button className="quick-action" onClick={() => setPage("execution")} disabled={!finalCaseSets.length}><span>进入执行中心</span><small>确认环境、数量和副作用</small></button></section></div></>;
  }

  function renderOperations() {
    if (!selectedProject) return showCreateForm ? renderCreateForm() : renderProjectEmpty();
    const documentLoaded = requirementDocuments.length > 0;
    const visibleOperations = operations;
    const documentStatus = !parsedDocument
      ? "尚未加载需求文档"
      : parsedDocument.project_id === selectedProject.project_id
        ? "已加载到当前项目"
        : "已解析，开始分析时会保存到当前项目";
    const documentStatusClass = documentLoaded && parsedDocument?.project_id === selectedProject.project_id ? "status-ready" : "status-warning";
    const selectedRequirementContent = parsedDocument && selectedOperation ? parsedDocument.content : "";
    const selectedContentLabel = parsedDocument ? `完整原文 · ${parsedDocument.line_count} 行` : "暂无原文";

    return <>
      <div className="page-heading">
        <div><span className="kicker">接口识别</span><h2>接口目录</h2><p>这里汇总本次上传的全部需求文档接口。每次选择 1 个接口，完成用例设计后再继续选择下一个。</p></div>
        <span className={`status-badge ${documentLoaded ? "status-ready" : "status-warning"}`}>{documentLoaded ? `来自 ${requirementDocuments.length} 份需求文档` : "请先解析需求文档"}</span>
      </div>
      <section className="card catalog-card">
        <div className="toolbar"><div><strong>{visibleOperations.length} 个接口</strong><span>{documentLoaded ? `已解析 ${requirementDocuments.length} 份需求文档` : "暂无需求文档输入"}</span></div><span className="status-badge status-neutral">每次最多选择 1 个</span></div>
        {visibleOperations.length ? <div className="table-wrap"><table><thead><tr><th className="check-col">选择</th><th>方法</th><th>接口路径</th><th>接口说明</th><th>需求来源</th><th>状态</th></tr></thead><tbody>{visibleOperations.map((operation) => {
          const completed = completedOperationIds.has(operation.operation_id);
          const inProgress = activeFlowOperationId === operation.operation_id;
          const locked = Boolean(activeFlowOperationId && activeFlowOperationId !== operation.operation_id);
          const selected = selectedOperationIds.includes(operation.operation_id);
          return <tr className={`${selected ? "row-selected" : ""} ${completed || locked ? "row-completed" : ""}`} key={operation.operation_id} onClick={() => { if (!activeFlowOperationId) selectOperation(operation); }}>
            <td className="check-col"><button type="button" className={`operation-selector ${selected ? "is-selected" : ""}`} aria-label={inProgress ? "当前接口流程进行中" : selected ? "取消选择接口" : "选择接口"} aria-pressed={selected} disabled={completed || Boolean(activeFlowOperationId)} onClick={(event) => { event.stopPropagation(); selectOperation(operation); }} /></td>
            <td><span className={methodClass(operation.method)}>{operation.method}</span></td>
            <td><code>{operation.path}</code></td>
            <td><strong>{operation.summary || "未提供说明"}</strong><small className="table-subtext">{operation.operation_id}</small></td>
            <td><span className="source-text">{operation.source_refs?.[0]?.section ?? operation.source_refs?.[0]?.reference ?? "接口契约"}</span>{operation.source_refs?.[0]?.start_line && <small className="table-subtext">Lines {operation.source_refs[0].start_line}–{operation.source_refs[0].end_line}</small>}</td>
            <td><span className={`status-badge ${completed ? "status-ready" : inProgress ? "status-warning" : "status-neutral"}`}>{completed ? "用例已生成" : inProgress ? "流程进行中" : locked ? "等待当前接口" : "可选择"}</span></td>
          </tr>;
        })}</tbody></table></div> : <div className="empty-table"><div className="empty-mark">API</div><h3>{documentLoaded ? "已上传的需求文档还没有识别出接口" : "还没有加载需求文档"}</h3><p>请先在“需求文档”上传或粘贴业务需求，接口目录不会自动加载项目历史接口。</p><button className="button button-primary" onClick={() => setPage("documents")}>去上传需求文档</button></div>}
        <div className="queue-launch"><div><strong>当前接口分析</strong><span>{selectedOperationIds.length ? "已选择 1 个接口" : "每次选择 1 个尚未生成用例的接口"} · {documentStatus}</span></div><button className="button button-primary" onClick={() => void runWorkflow()} disabled={busy || !documentLoaded || selectedOperationIds.length !== 1}>{busy ? "正在进入下一节点…" : "开始分析当前接口"}</button></div>
        {selectedOperationIds.length > 0 && <div className="queue-preview">{selectedOperationIds.map((operationId, index) => { const operation = visibleOperations.find((item) => item.operation_id === operationId); return <div key={operationId}><span>{index + 1}</span><strong>{operation ? `${operation.method} ${operation.path}` : operationId}</strong><button className="button button-small button-ghost" onClick={() => toggleOperation(operationId)} disabled={busy || Boolean(activeFlowOperationId)}>移除</button></div>; })}</div>}
      </section>
      {selectedOperation && <section className="card requirement-detail-card">
        <div className="card-heading"><div><span className="kicker">需求文档</span><h3>需求详情 · {selectedOperation.method} {selectedOperation.path}</h3></div><span className={`status-badge ${documentStatusClass}`}>{documentStatus}</span></div>
        {parsedDocument ? <><div className="parsed-meta"><div><span>文件名</span><strong title={parsedDocument.filename}>{parsedDocument.filename}</strong></div><div><span>接口</span><strong>{selectedOperation.operation_id}</strong></div><div><span>字符数</span><strong>{parsedDocument.char_count.toLocaleString()}</strong></div><div><span>接口原文</span><strong>{selectedContentLabel}</strong></div><div><span>文档编号</span><code title={parsedDocument.document_id}>{parsedDocument.document_id}</code></div></div><div className="requirement-source-content"><div className="source-content-heading"><strong>当前接口对应的需求原文</strong><span>{selectedContentLabel}</span></div><pre>{selectedRequirementContent || "（当前接口没有可展示的需求原文）"}</pre></div></> : <div className="empty-inline requirement-detail-empty"><p>当前接口尚未关联需求文档，请先完成需求文档解析。</p></div>}
      </section>}
    </>;
  }

  function renderWorkflowFailure() {
    if (!queue) return null;
    const item = queue.items[queue.current_index];
    return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>顺序分析失败</h2><p>后台分析任务已返回失败状态，当前队列和失败原因已保留，没有自动跳回接口目录。</p></div><span className="status-badge status-danger">失败</span></div><section className="card workflow-failure-card"><div className="workflow-loading-mark">!</div><h3>当前接口未进入下一节点</h3><p>{item?.error_message ?? message}</p><div className="workflow-start-facts"><div><span>处理队列</span><strong>{queue.items.length} 个接口</strong></div><div><span>当前接口</span><strong>第 {queue.current_index + 1} 个</strong></div><div><span>队列状态</span><strong>{statusText(queue.status)}</strong></div></div><div className="gate-actions"><button className="button button-primary" onClick={() => void retryWorkflowQueue()} disabled={busy}>重试当前接口</button><button className="button button-secondary" onClick={() => setPage("operations")} disabled={busy}>返回接口目录</button></div></section></>;
  }

  function renderRequirements() {
    if (startingWorkflow) return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>正在进入需求分析</h2><p>顺序处理已经启动，需求提取完成后会自动展示需求、测试点和辅助证据。</p></div><span className="status-badge status-warning">处理中</span></div><section className="card workflow-start-card"><div className="workflow-loading-mark">分析</div><h3>正在分析当前接口需求</h3><p>{message}</p>{queue && <div className="workflow-start-facts"><div><span>处理队列</span><strong>{queue.items.length} 个接口</strong></div><div><span>当前接口</span><strong>第 {queue.current_index + 1} 个</strong></div><div><span>队列状态</span><strong>{statusText(queue.status)}</strong></div></div>}<div className="workflow-loading-line"><span className="loading-dot" /><span>页面已切换到下一节点，等待后台返回分析结果…</span></div></section></>;
    if (!workflow) return <div className="empty-card"><div className="empty-mark">需</div><h3>还没有需求分析结果</h3><p>请先解析需求文档，再选择待测接口开始分析。</p><button className="button button-primary" onClick={() => setPage("documents")}>去需求文档</button></div>;
    const requirement = workflow.requirement;
    return <><div className="page-heading"><div><span className="kicker">需求分析 · 人工确认</span><h2>需求确认</h2><p>当前接口从需求文档中提取需求和测试点；确认后系统会自动设计并检查用例。</p></div>{selectedOperation && <span className="operation-pill"><span className={methodClass(selectedOperation.method)}>{selectedOperation.method}</span><code>{selectedOperation.path}</code></span>}</div>{queue && <section className="card queue-card"><div className="card-heading"><div><span className="kicker">接口处理顺序</span><h3>严格顺序处理</h3></div><span className={`status-badge ${queue.status === "READY_FOR_EXECUTION" ? "status-ready" : "status-warning"}`}>{statusText(queue.status)}</span></div><div className="queue-items">{queue.items.map((item) => { const operation = operations.find((candidate) => candidate.operation_id === item.api_operation_id); return <div className={`queue-item ${item.status === "COMPLETED" ? "is-complete" : ["WAITING_REQUIREMENT_APPROVAL", "BLOCKED"].includes(item.status) ? "is-current" : ""}`} key={item.api_operation_id}><span className="queue-order">{item.order}</span><div><strong>{operation ? `${operation.method} ${operation.path}` : item.api_operation_id}</strong><small>{item.status === "WAITING_REQUIREMENT_APPROVAL" ? "等待需求确认" : item.status === "COMPLETED" ? "已完成：测试用例已确认" : statusText(item.status)}</small></div><span className="status-badge status-neutral">{statusText(item.current_stage)}</span></div>; })}</div></section>}{queue?.status === "BLOCKED" && <div className="callout callout-warning"><strong>用例需要人工处理</strong><p>{queue.items[queue.current_index]?.error_message ?? "存在无法自动解决的覆盖或执行问题，请查看最终用例详情。"}</p>{workflow.final_cases?.remaining_gaps.map((gap) => <p key={gap}>{gap}</p>)}</div>}<div className="requirement-grid"><section className="card"><div className="card-heading"><div><span className="kicker">需求快照</span><h3>{requirement?.requirement_id ?? workflow.workflow_id}</h3></div><span className={`status-badge ${workflow.status === "WAITING_REQUIREMENT_APPROVAL" ? "status-warning" : workflow.status === "FINAL_CASES_READY" ? "status-ready" : "status-neutral"}`}>{statusText(workflow.status)}</span></div>{requirement ? <><div className="facts-grid"><div><span>版本</span><strong>v{requirement.version}</strong></div><div><span>辅助证据</span><strong>{requirement.evidence_refs.length}</strong></div><div><span>置信度</span><strong>{requirement.confidence}</strong></div></div><div className="list-section"><h4>业务规则</h4>{requirement.business_rules.length ? <ul>{requirement.business_rules.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">暂无已提取业务规则</p>}</div><div className="list-section"><h4>预期行为</h4>{requirement.expected_behaviors.length ? <ul>{requirement.expected_behaviors.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">暂无已提取预期行为</p>}</div>{requirement.conflicts.length > 0 && <div className="callout callout-warning"><strong>文档冲突</strong>{requirement.conflicts.map((item) => <p key={item}>{item}</p>)}</div>}{requirement.unresolved_questions.length > 0 && <div className="callout callout-warning"><strong>待确认问题</strong>{requirement.unresolved_questions.map((item) => <p key={item}>{item}</p>)}</div>}{workflow.status === "WAITING_REQUIREMENT_APPROVAL" && <div className="gate-submit"><button className="button button-primary" onClick={() => void approveCurrentRequirement()} disabled={busy}>{busy ? "确认中…" : "确认需求并生成用例"}</button><span>确认后将锁定当前版本，并基于该版本生成测试用例。</span></div>}</> : <div className="empty-inline"><p>需求尚未生成。</p></div>}</section><section className="card"><div className="card-heading"><div><span className="kicker">测试点</span><h3>本接口需要验证什么</h3></div><span className="status-badge status-neutral">自动提取</span></div>{workflow.test_points?.points.length ? <div className="evidence-list">{workflow.test_points.points.map((point) => <div className="evidence-item" key={point.point_id}><div><span className="evidence-type">{point.category}</span><strong>{point.title}</strong></div><p>{point.expected_result}</p><small>{point.point_id}</small></div>)}</div> : <p className="muted">当前没有生成测试点。</p>}<div className="card-heading evidence-heading"><div><span className="kicker">证据来源</span><h3>辅助证据</h3></div></div>{workflow.evidence?.facts.length ? <div className="evidence-list auxiliary-evidence-list">{workflow.evidence.facts.map((fact) => <div className="evidence-item" key={fact.evidence_id}><div><span className="evidence-type">{fact.source_type}</span><strong>{fact.evidence_id}</strong></div><p>{fact.fact}</p><small>{fact.reference}</small></div>)}</div> : <p className="muted">当前没有可用的辅助证据。</p>}</section></div></>;
  }

  function renderCases() {
    if (!finalCaseSets.length) return <div className="empty-card"><div className="empty-mark">例</div><h3>还没有测试用例</h3><p>请先选择一个接口，完成需求确认和用例设计。</p><button className="button button-primary" onClick={() => setPage("operations")}>选择接口</button></div>;
    const caseCount = allFinalCases.length;
    const reviewerAdded = finalCaseSets.reduce((sum, item) => sum + item.added_case_ids.length, 0);
    const unresolved = finalCaseSets.reduce((sum, item) => sum + item.unresolved_questions.length + item.remaining_gaps.length, 0);
    return <>
      <div className="page-heading">
        <div><span className="kicker">测试设计结果</span><h2>测试用例</h2><p>每个接口独立生成用例，并持续累计到当前项目；展开接口即可查看和选择用例。</p></div>
        <span className="status-badge status-ready">已完成 {finalCaseSets.length} 个接口</span>
      </div>
      <div className="stats-grid"><div className="metric-card"><span>测试用例</span><strong>{caseCount}</strong><small>项目累计用例</small></div><div className="metric-card"><span>自动补充</span><strong>{reviewerAdded}</strong><small>发现覆盖缺口时补充</small></div><div className="metric-card"><span>副作用用例</span><strong>{allFinalCases.filter((item) => item.side_effect).length}</strong><small>执行前需要确认</small></div><div className="metric-card"><span>待解决问题</span><strong>{unresolved}</strong><small>{unresolved ? "进入执行前需人工确认" : "已完成冻结"}</small></div></div>
      <section className="card case-library-card">
        <div className="toolbar"><div><strong>批次用例选择</strong><span>{selectedCaseIds.length} / {caseCount} 条已选择</span></div><div className="toolbar-actions"><button className="button button-small button-ghost" onClick={toggleAllCases} disabled={!!batchApproval}>{selectedCaseIds.length === caseCount ? "取消全选" : "全选用例"}</button><button className="button button-small button-secondary" onClick={() => setPage("operations")}>继续选择接口</button><button className="button button-small button-primary" onClick={() => setPage("execution")} disabled={!selectedCaseIds.length}>进入统一执行确认</button></div></div>
        <div className="case-accordion-list">{finalCaseSets.map((set) => {
          const operation = operations.find((item) => item.operation_id === set.api_operation_id);
          const selectedCount = set.cases.filter((item) => selectedCaseIds.includes(item.case_id)).length;
          return <details className="case-accordion" key={set.final_case_set_id}>
            <summary><span><strong>{operation ? `${operation.method} ${operation.path}` : set.api_operation_id ?? set.requirement_id}</strong><small>{set.cases.length} 条用例 · 已选择 {selectedCount} 条</small></span><span className="status-badge status-ready">用例已生成</span></summary>
            <div className="table-wrap"><table><thead><tr><th className="check-col">选择</th><th>用例</th><th>分类</th><th>预期行为</th><th>副作用</th></tr></thead><tbody>{set.cases.map((testCase) => <tr key={testCase.case_id}><td className="check-col"><input type="checkbox" checked={selectedCaseIds.includes(testCase.case_id)} onChange={() => toggleCase(testCase.case_id)} disabled={!!batchApproval} /></td><td><strong>{testCase.title}</strong><small className="table-subtext">{testCase.case_id}</small></td><td>{testCase.category}</td><td className="expected-cell">{testCase.expected_behavior}</td><td>{testCase.side_effect ? <span className="status-badge status-warning">需确认</span> : <span className="status-badge status-neutral">无</span>}</td></tr>)}</tbody></table></div>
          </details>;
        })}</div>
      </section>
    </>;
  }

  function renderExecution() {
    if (!allFinalCases.length) return <div className="empty-card empty-warning"><div className="empty-mark">!</div><h3>还没有可执行用例</h3><p>请先选择一个接口并完成需求确认与用例设计。</p><button className="button button-secondary" onClick={() => setPage("operations")}>选择接口</button></div>;
    return <><div className="page-heading"><div><span className="kicker">执行前确认</span><h2>统一执行确认</h2><p>确认目标环境、服务地址、用例数量和可能产生副作用的用例，然后批量执行。</p></div><span className="status-badge status-warning">执行前人工确认</span></div><section className="card gate-card"><div className="gate-title"><div><span className="kicker">批次执行范围</span><h3>{finalCaseSets.length} 个接口 · {allFinalCases.length} 条测试用例</h3></div>{batchApproval && <span className="status-badge status-ready">已批准</span>}</div>{batchApproval ? <><div className="approval-banner"><strong>已批准执行 {batchApproval.selected_case_count} 条用例</strong><span>{batchApproval.target_environment}</span></div><div className="approval-details"><div><span>接口数量</span><strong>{finalCaseSets.length}</strong></div><div><span>副作用用例</span><strong>{batchApproval.side_effect_case_ids.length || "无"}</strong></div><div><span>自动回归</span><strong>{batchApproval.auto_regression_allowed ? "允许" : "不允许"}</strong></div></div><div className="gate-actions"><button className="button button-primary" onClick={() => void executeApproved(false)} disabled={busy}>{busy ? "执行中…" : "批量执行"}</button>{batchApproval.auto_regression_allowed && <button className="button button-secondary" onClick={() => void executeApproved(true)} disabled={busy}>自动回归未变化用例</button>}</div></> : <><div className="form-grid gate-form"><label>目标环境<input value={targetEnvironment} onChange={(event) => setTargetEnvironment(event.target.value)} placeholder="local / test / staging" /></label><label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label><label>确认用例数量<input value={selectedCaseIds.length} readOnly /></label></div><div className="selected-case-box"><div><strong>本次批量执行范围</strong><span>已选择 {selectedCaseIds.length} / {allFinalCases.length} 条用例</span></div><button className="button button-small button-ghost" onClick={() => setPage("cases")}>调整用例</button></div>{sideEffectCaseIds.length > 0 && <label className="danger-confirm"><input type="checkbox" checked={sideEffectsConfirmed} onChange={(event) => setSideEffectsConfirmed(event.target.checked)} /><span><strong>我确认以下用例可能产生副作用</strong><small>{sideEffectCaseIds.join("、")}</small></span></label>}<div className="gate-submit"><button className="button button-primary" onClick={() => void approveForExecution()} disabled={busy || !selectedCaseIds.length || !baseUrl.trim() || (sideEffectCaseIds.length > 0 && !sideEffectsConfirmed)}>确认并生成批量执行许可</button><span>批准后仍不会自动执行，需再次点击“批量执行”。</span></div></>}</section></>;
  }

  function renderReports() {
    if (!execution) return <div className="empty-card"><div className="empty-mark">报</div><h3>还没有执行报告</h3><p>确认执行范围并运行用例后，报告会在这里展示。</p><button className="button button-primary" onClick={() => setPage("execution")}>去执行中心</button></div>;
    const resultTitle = new Map(allFinalCases.map((item) => [item.case_id, item.title]));
    const resultsByOperation = [...execution.run.results.reduce((grouped, result) => {
      const operationId = result.api_operation_id ?? result.requirement_id;
      grouped.set(operationId, [...(grouped.get(operationId) ?? []), result]);
      return grouped;
    }, new Map<string, ExecutionResult[]>()).entries()];
    return <>
      <div className="page-heading">
        <div><span className="kicker">执行结果</span><h2>报告中心</h2><p>查看批量执行结果、HTTP 状态和每条断言的字段、期望值与实际值。</p></div>
        <div className="page-heading-actions">
          <span className={"status-badge " + (execution.report.status === "passed" ? "status-ready" : "status-danger")}>{statusText(execution.report.status)}</span>
          <button className="button button-secondary" onClick={exportReportHtml}>导出 HTML 报告</button>
        </div>
      </div>
      <div className="stats-grid">
        <div className="metric-card"><span>总用例</span><strong>{execution.report.total_cases}</strong><small>本次批量执行</small></div>
        <div className="metric-card"><span>PASS</span><strong className="metric-success">{execution.report.passed_cases}</strong><small>通过用例</small></div>
        <div className="metric-card"><span>FAIL</span><strong className="metric-danger">{execution.report.failed_cases}</strong><small>断言或业务结果不符合预期</small></div>
        <div className="metric-card"><span>断言失败</span><strong className="metric-danger">{execution.report.assertion_failures}</strong><small>共 {execution.report.assertion_total} 条断言</small></div>
      </div>
      <section className="card report-library-card">
        <div className="toolbar">
          <div><strong>执行明细</strong><span>Run ID：{execution.run.run_id}</span></div>
          <span className="source-text">{execution.run.target_environment ?? "local"}</span>
        </div>
        <div className="report-accordion-list">{resultsByOperation.map(([operationId, results]) => {
          const operation = operations.find((item) => item.operation_id === operationId);
          const passed = results.filter((item) => item.status === "passed").length;
          return <details className="report-accordion" key={operationId}>
            <summary><span><strong>{operation ? `${operation.method} ${operation.path}` : operationId}</strong><small>{results.length} 条结果 · {passed} 条通过</small></span><span className={`status-badge ${passed === results.length ? "status-ready" : "status-danger"}`}>{passed === results.length ? "全部通过" : "存在失败"}</span></summary>
            <div className="table-wrap"><table>
              <thead><tr><th>用例编号</th><th>用例名称</th><th>结果</th><th>HTTP 状态</th><th>断言</th><th>操作</th></tr></thead>
              <tbody>{results.map((result) => {
              const passedAssertions = result.assertion_results.filter((assertion) => assertion.passed).length;
              return <tr key={result.case_id}>
                <td><code>{result.case_id}</code></td>
                <td>{result.case_title ?? resultTitle.get(result.case_id) ?? "—"}</td>
                <td><span className={"status-badge status-" + (result.status === "passed" ? "ready" : result.status === "failed" ? "danger" : "warning")}>{statusText(result.status)}</span></td>
                <td>{result.status_code ?? "—"}</td>
                <td><span className="assertion-summary">{passedAssertions} / {result.assertion_results.length} 通过</span></td>
                <td><button className="button button-small button-ghost" onClick={() => setSelectedResult(result)}>查看详情</button></td>
              </tr>;
              })}</tbody>
            </table></div>
          </details>;
        })}</div>
      </section>
      {selectedResult && <div className="modal-backdrop" role="presentation" onClick={() => setSelectedResult(null)}>
        <section className="result-modal" role="dialog" aria-modal="true" aria-labelledby="result-detail-title" onClick={(event) => event.stopPropagation()}>
          <button className="modal-close" aria-label="关闭断言详情" onClick={() => setSelectedResult(null)}>×</button>
          <div className="result-modal-heading">
            <div>
              <span className="kicker">执行详情</span>
              <h2 id="result-detail-title">断言详情</h2>
              <p>{selectedResult.case_title ?? resultTitle.get(selectedResult.case_id) ?? selectedResult.case_id}</p>
            </div>
            <span className={"status-badge status-" + (selectedResult.status === "passed" ? "ready" : selectedResult.status === "failed" ? "danger" : "warning")}>{statusText(selectedResult.status)}</span>
          </div>
          <div className="result-meta-grid">
            <div><span>请求方法</span><strong>{selectedResult.method}</strong></div>
            <div><span>HTTP 状态</span><strong>{selectedResult.status_code ?? "—"}</strong></div>
            <div><span>耗时</span><strong>{selectedResult.duration_ms == null ? "—" : selectedResult.duration_ms.toFixed(1) + " ms"}</strong></div>
            <div className="result-meta-wide"><span>请求 URL</span><code>{selectedResult.url}</code></div>
          </div>
          {selectedResult.error_message && <div className="callout callout-danger"><strong>{selectedResult.error_category ?? "执行错误"}</strong><p>{selectedResult.error_message}</p></div>}
          <div className="assertion-detail-heading">
            <strong>断言列表</strong>
            <span>{selectedResult.assertion_results.filter((item) => item.passed).length} / {selectedResult.assertion_results.length} 通过</span>
          </div>
          {selectedResult.assertion_results.length ? <div className="assertion-detail-list">
            {selectedResult.assertion_results.map((assertion) => <article className={"assertion-detail-item " + (assertion.passed ? "is-passed" : "is-failed")} key={assertion.assertion_id}>
              <div className="assertion-detail-title">
                <div><span className={"assertion-state " + (assertion.passed ? "passed" : "failed")}>{assertion.passed ? "PASS" : "FAIL"}</span><code>{assertion.assertion_id}</code></div>
                <span>{assertion.type ?? "类型未记录"}</span>
              </div>
              <dl className="assertion-detail-grid">
                <div><dt>断言字段</dt><dd><code>{assertionTarget(assertion.type, assertion.path)}</code></dd></div>
                <div><dt>运算符</dt><dd><code>{assertion.operator || "默认相等"}</code></dd></div>
                <div><dt>期望值</dt><dd><pre>{formatDetailValue(assertion.expected)}</pre></dd></div>
                <div><dt>实际值</dt><dd><pre>{formatDetailValue(assertion.actual)}</pre></dd></div>
              </dl>
              <p className="assertion-message">{assertion.message}</p>
              {!!assertion.evidence_refs?.length && <p className="assertion-evidence">辅助证据：{assertion.evidence_refs.join("、")}</p>}
            </article>)}
          </div> : <div className="empty-inline"><p>该用例没有生成断言结果；请查看执行错误信息。</p></div>}
          <details className="response-detail">
            <summary>查看响应 Body</summary>
            <pre>{formatDetailValue(selectedResult.response_body)}</pre>
          </details>
          <div className="modal-actions"><button className="button button-primary" onClick={() => setSelectedResult(null)}>关闭</button></div>
        </section>
      </div>}
    </>;
  }

  function renderSettings() {
    if (showCreateForm) return renderCreateForm();
    if (!selectedProject || !projectEditor) return renderProjectEmpty();
    const updateEditor = (patch: Partial<ProjectEditor>) => setProjectEditor((current) => current ? { ...current, ...patch } : current);
    return <>
      <div className="page-heading">
        <div><span className="kicker">配置与安全</span><h2>项目设置</h2><p>当前正在编辑“{selectedProject.name}”。切换左侧项目后，这里的内容会同步切换。</p></div>
        <div className="page-heading-actions"><button className="button button-secondary" onClick={startCreateProject}>+ 新建项目</button><button className="button button-danger" onClick={() => void deleteSelectedProject()} disabled={busy}>删除当前项目</button></div>
      </div>
      <section className="card settings-editor">
        <div className="settings-section-heading"><span className="kicker">认证提供器</span><h3>登录、凭证提取与请求注入</h3></div>
        <label className="switch-row"><input type="checkbox" checked={projectEditor.authEnabled} onChange={(event) => updateEditor({ authEnabled: event.target.checked })} /><span><strong>启用可配置认证</strong><small>认证请求只在执行前由后端确定性发送；凭证引用只保存 env:NAME，不会发送给模型。</small></span></label>
        <div className="form-grid database-fields auth-fields">
          <label>认证方式<select value={projectEditor.authKind} onChange={(event) => updateEditor({ authKind: event.target.value as "http" | "sms" })} disabled={!projectEditor.authEnabled}><option value="http">HTTP 登录请求</option><option value="sms">短信验证码登录</option></select></label>
          <label>登录方法<input value={projectEditor.authLoginMethod} onChange={(event) => updateEditor({ authLoginMethod: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="POST" /></label>
          <label>请求体类型<select value={projectEditor.authBodyType} onChange={(event) => updateEditor({ authBodyType: event.target.value as "json" | "form" | "none" })} disabled={!projectEditor.authEnabled}><option value="json">JSON</option><option value="form">表单</option><option value="none">无请求体</option></select></label>
          <label>登录路径<input value={projectEditor.authLoginPath} onChange={(event) => updateEditor({ authLoginPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="/auth/login" /></label>
          <label>提取来源<select value={projectEditor.authExtractSource} onChange={(event) => updateEditor({ authExtractSource: event.target.value as "json" | "header" | "cookie" })} disabled={!projectEditor.authEnabled}><option value="json">JSON 响应</option><option value="header">响应头</option><option value="cookie">响应 Cookie</option></select></label>
          <label>提取路径或名称<input value={projectEditor.authExtractPath} onChange={(event) => updateEditor({ authExtractPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="$.data.token 或 Set-Cookie 名称" /></label>
          <label>注入位置<select value={projectEditor.authInjectLocation} onChange={(event) => updateEditor({ authInjectLocation: event.target.value as "header" | "cookie" })} disabled={!projectEditor.authEnabled}><option value="header">请求头</option><option value="cookie">请求 Cookie</option></select></label>
          <label>注入名称<input value={projectEditor.authInjectName} onChange={(event) => updateEditor({ authInjectName: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="Authorization 或 session" /></label>
          <label>前缀<input value={projectEditor.authInjectPrefix} onChange={(event) => updateEditor({ authInjectPrefix: event.target.value })} disabled={!projectEditor.authEnabled || projectEditor.authInjectLocation === "cookie"} placeholder="Bearer；Cookie 留空" /></label>
          <label>Token TTL（秒）<input type="number" min="1" max="604800" step="1" value={projectEditor.authTtlSeconds} onChange={(event) => updateEditor({ authTtlSeconds: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="1800" /><small className="help-text">后端启动后按此周期自动刷新；留空仅在需要时获取。</small></label>
          {projectEditor.authKind === "sms" && <>
            <label>手机号环境变量引用<input value={projectEditor.authSmsPhoneRef} onChange={(event) => updateEditor({ authSmsPhoneRef: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="env:TEST_LOGIN_PHONE" /></label>
            <label>验证码请求方法<input value={projectEditor.authSmsCodeMethod} onChange={(event) => updateEditor({ authSmsCodeMethod: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="POST" /></label>
            <label>验证码请求路径<input value={projectEditor.authSmsCodePath} onChange={(event) => updateEditor({ authSmsCodePath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="/auth/sms/code" /></label>
            <label>验证码来源<select value={projectEditor.authSmsCodeSource} onChange={(event) => updateEditor({ authSmsCodeSource: event.target.value as "redis" | "json" })} disabled={!projectEditor.authEnabled}><option value="redis">Redis</option><option value="json">JSON 响应</option></select></label>
            <label>验证码提取路径或 Redis Key<input value={projectEditor.authSmsCodeSource === "redis" ? projectEditor.authSmsRedisKey : projectEditor.authSmsCodeExtractPath} onChange={(event) => updateEditor(projectEditor.authSmsCodeSource === "redis" ? { authSmsRedisKey: event.target.value } : { authSmsCodeExtractPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder={projectEditor.authSmsCodeSource === "redis" ? "login:code:{{phone}}" : "$.data.code"} /></label>
            {projectEditor.authSmsCodeSource === "redis" && <>
              <label>Redis 地址<input value={projectEditor.authSmsRedisHost} onChange={(event) => updateEditor({ authSmsRedisHost: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="127.0.0.1" /></label>
              <label>Redis 端口<input type="number" min="1" max="65535" value={projectEditor.authSmsRedisPort} onChange={(event) => updateEditor({ authSmsRedisPort: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="6379" /></label>
              <label>Redis 密码引用<input value={projectEditor.authSmsRedisPasswordRef} onChange={(event) => updateEditor({ authSmsRedisPasswordRef: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="env:REDIS_PASSWORD" /></label>
            </>}
            <label className="field-wide">验证码请求参数（JSON）<textarea value={projectEditor.authSmsCodeQueryParams} onChange={(event) => updateEditor({ authSmsCodeQueryParams: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"phone":"{{phone}}"}' /></label>
            <label className="field-wide">验证码请求头（JSON）<textarea value={projectEditor.authSmsCodeHeaders} onChange={(event) => updateEditor({ authSmsCodeHeaders: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"Content-Type":"application/json"}' /></label>
            <label className="field-wide">验证码请求体（JSON）<textarea value={projectEditor.authSmsCodeBody} onChange={(event) => updateEditor({ authSmsCodeBody: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"phone":"{{phone}}"}' /></label>
          </>}
          <label className="field-wide">登录查询参数（JSON）<textarea value={projectEditor.authQueryParams} onChange={(event) => updateEditor({ authQueryParams: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder="{}" /></label>
          <label className="field-wide">登录请求头（JSON）<textarea value={projectEditor.authHeaders} onChange={(event) => updateEditor({ authHeaders: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"Content-Type":"application/json"}' /></label>
          <label className="field-wide">登录请求体（JSON）<textarea value={projectEditor.authBody} onChange={(event) => updateEditor({ authBody: event.target.value })} disabled={!projectEditor.authEnabled} rows={3} placeholder='{"username":"{{username}}","password":"{{password}}"}' /></label>
          <label className="field-wide">凭证引用（JSON）<textarea value={projectEditor.authCredentialRefs} onChange={(event) => updateEditor({ authCredentialRefs: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"username":"env:TEST_LOGIN_USER","password":"env:TEST_LOGIN_PASSWORD"}' /></label>
        </div>
        <div className="card-heading"><div><span className="kicker">基本信息</span><h3>{selectedProject.name}</h3><p className="form-subtitle">项目编号 {selectedProject.project_id} · 更新于 {formatDate(selectedProject.updated_at)}</p></div><span className="status-badge status-ready">可编辑</span></div>
        <div className="form-grid">
          <label>项目名称<input value={projectEditor.name} onChange={(event) => updateEditor({ name: event.target.value })} /></label>
          <label>被测服务 Base URL<input value={projectEditor.baseUrl} onChange={(event) => updateEditor({ baseUrl: event.target.value })} placeholder="http://127.0.0.1:8081" /></label>
          <label className="field-wide">项目说明<textarea value={projectEditor.description} onChange={(event) => updateEditor({ description: event.target.value })} rows={2} /></label>
          <label>请求超时（秒）<input type="number" min="0.1" max="300" step="0.1" value={projectEditor.timeoutSeconds} onChange={(event) => updateEditor({ timeoutSeconds: event.target.value })} /></label>
          <label>源码工作区路径（可选）<input value={projectEditor.sourceWorkspace} onChange={(event) => updateEditor({ sourceWorkspace: event.target.value })} placeholder="例如：D:\\workspace\\your-service" /></label>
          <label className="field-wide">接口描述来源（可选）<textarea value={projectEditor.openapiSources} onChange={(event) => updateEditor({ openapiSources: event.target.value })} placeholder="每行一个本地文件或 URL" rows={3} /></label>
        </div>
        <label className="switch-row"><input type="checkbox" checked={projectEditor.verifyTls} onChange={(event) => updateEditor({ verifyTls: event.target.checked })} /><span><strong>校验 HTTPS 证书</strong><small>本地 HTTP 服务不受影响；HTTPS 环境建议保持开启。</small></span></label>

        <div className="settings-section-heading"><span className="kicker">数据库真实夹具</span><h3>本地只读解析请求参数</h3></div>
        <label className="switch-row"><input type="checkbox" checked={projectEditor.databaseEnabled} onChange={(event) => updateEditor({ databaseEnabled: event.target.checked })} /><span><strong>启用数据库真实夹具</strong><small>模型只选择无真实值的夹具令牌，后端在模型审查完成后从白名单表读取 ID 并本地替换。</small></span></label>
        <div className="form-grid database-fields">
          <label>数据库类型<select value={projectEditor.databaseDialect} onChange={(event) => updateEditor({ databaseDialect: event.target.value })} disabled={!projectEditor.databaseEnabled}><option value="mysql">MySQL</option><option value="postgresql">PostgreSQL</option><option value="sqlite">SQLite</option></select></label>
          <label>连接环境变量引用<input value={projectEditor.databaseRef} onChange={(event) => updateEditor({ databaseRef: event.target.value })} placeholder="env:TEST_DB_DSN" disabled={!projectEditor.databaseEnabled} /></label>
          <label>数据库 Schema（可选）<input value={projectEditor.databaseSchema} onChange={(event) => updateEditor({ databaseSchema: event.target.value })} placeholder="例如：public" disabled={!projectEditor.databaseEnabled} /></label>
          <label>允许读取的表<textarea value={projectEditor.allowedTables} onChange={(event) => updateEditor({ allowedTables: event.target.value })} placeholder="每行一个表名，例如：example_table" rows={3} disabled={!projectEditor.databaseEnabled} /></label>
        </div>
        <div className="form-note">真实数据库值不会发送给 DeepSeek。连接串必须放在本机环境变量中；设置页只保存 env:NAME 引用和表白名单。</div>
        <div className="form-actions"><button className="button button-primary" onClick={() => void saveProjectSettings()} disabled={busy}>保存当前项目设置</button></div>
      </section>
    </>;
  }

  function renderPage() {
    const content = (() => {
      switch (page) {
        case "overview": return renderOverview();
        case "documents": return renderDocuments();
        case "operations": return renderOperations();
        case "requirements": return ["FAILED", "BLOCKED"].includes(queue?.status ?? "") && !startingWorkflow ? renderWorkflowFailure() : renderRequirements();
        case "cases": return renderCases();
        case "execution": return renderExecution();
        case "reports": return renderReports();
        case "settings": return renderSettings();
        default: return null;
      }
    })();
    return <>{content}{parseSuccess && <div className="modal-backdrop" role="presentation" onClick={() => setParseSuccess(null)}><section className="success-modal" role="dialog" aria-modal="true" aria-labelledby="parse-success-title" onClick={(event) => event.stopPropagation()}><button className="modal-close" aria-label="关闭" onClick={() => setParseSuccess(null)}>×</button><div className="success-icon">✓</div><span className="kicker">文档解析</span><h2 id="parse-success-title">需求文档解析成功</h2><p className="success-modal-copy">“{parseSuccess.filename}”已完成解析，后续流程将使用这份规范化需求文档。</p><div className="success-modal-facts"><div><span>字符数</span><strong>{parseSuccess.charCount.toLocaleString()}</strong></div><div><span>行数</span><strong>{parseSuccess.lineCount.toLocaleString()}</strong></div><div><span>文档编号</span><code title={parseSuccess.documentId}>{parseSuccess.documentId}</code></div></div>{parseSuccess.operationCount !== undefined && <p className="success-modal-hint">已从需求原文识别 {parseSuccess.operationCount} 个可测试接口，请在接口目录选择需要分析的接口。</p>}<div className="modal-actions"><button className="button button-primary" onClick={() => setParseSuccess(null)}>继续查看</button>{parseSuccess.operationCount !== undefined && <button className="button button-secondary" onClick={() => { setParseSuccess(null); setPage("operations"); }}>查看接口目录</button>}</div></section></div>}{saveSuccess && <div className="modal-backdrop" role="presentation" onClick={() => setSaveSuccess(null)}><section className="success-modal" role="dialog" aria-modal="true" aria-labelledby="save-success-title" onClick={(event) => event.stopPropagation()}><button className="modal-close" aria-label="关闭" onClick={() => setSaveSuccess(null)}>×</button><div className="success-icon">{saveSuccess.authSuccess ? "✓" : "!"}</div><span className="kicker">项目设置</span><h2 id="save-success-title">{saveSuccess.authSuccess ? "保存成功" : "已保存，但鉴权预检失败"}</h2><p className="success-modal-copy">项目“{saveSuccess.name}”的配置已保存，刷新页面后仍会保留。</p><p className={`success-modal-hint ${saveSuccess.authSuccess ? "" : "save-auth-failed"}`}>{saveSuccess.authMessage}</p><div className="modal-actions"><button className="button button-primary" onClick={() => setSaveSuccess(null)}>知道了</button></div></section></div>}</>;
  }

  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">MA</div><div><strong>Multi-Agent</strong><span>接口自动化测试平台</span></div></div><div className="sidebar-section project-section"><span className="sidebar-label">当前项目</span>{projects.length ? <select value={selectedProject?.project_id ?? ""} onChange={(event) => { const project = projects.find((item) => item.project_id === event.target.value); if (project) selectProject(project); }}><option value="" disabled>选择项目</option>{projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.name}</option>)}</select> : <button className="sidebar-create" onClick={() => setShowCreateForm(true)}>+ 创建测试项目</button>}</div><nav className="main-nav" aria-label="主导航">{navItems.map((item) => <button key={item.key} className={`nav-item ${page === item.key ? "active" : ""}`} onClick={() => setPage(item.key)}><span className="nav-index">{item.shortLabel}</span><span>{item.label}</span></button>)}</nav></aside><div className="main-area"><header className="topbar"><div><span className="breadcrumb">测试平台 / {activeNav.label}</span><h1>{activeNav.label}</h1></div></header><main className="content"><div className="workflow-progress"><div className="progress-caption"><div><span className="kicker">测试任务进度</span><strong>需求文档 → 接口选择 → 需求确认 → 用例设计 → 执行 → 报告</strong></div><span>第 {Math.min(currentStep + 1, workflowSteps.length)} / {workflowSteps.length} 阶段</span></div><div className="stepper">{workflowSteps.map((step, index) => <div className={`step ${index < currentStep ? "complete" : ""} ${index === currentStep ? "current" : ""}`} key={step}><span className="step-number">{index < currentStep ? "✓" : index + 1}</span><span>{step}</span></div>)}</div></div><div className={`global-notice ${busy ? "is-busy" : ""}`}><span className="notice-indicator" />{message}</div>{renderPage()}</main></div></div>;
}
