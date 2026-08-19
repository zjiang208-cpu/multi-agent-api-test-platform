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
import {
  assertionTarget,
  formatDate,
  formatDetailValue,
  isQueueTerminal,
  methodClass,
  navGroups,
  navItems,
  operationsForDocument,
  overviewActions,
  projectEditorFrom,
  sortRequirementDocuments,
  splitLines,
  statusText,
  workflowSteps,
} from "./app/platform";
import type { PageKey, ParseSuccessNotice, ProjectEditor } from "./app/platform";
import { AppShell } from "./components/AppShell";
import { ProjectSettingsPage } from "./components/ProjectSettingsPage";
import { RequirementDocumentsPage } from "./components/RequirementDocumentsPage";
import { downloadReportHtml } from "./app/report";
import "./styles.css";

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
  const activeFlowOperationId = queue && !isQueueTerminal(queue.status)
    ? queue.items[queue.current_index]?.api_operation_id ?? null
    : null;
  const sideEffectCaseIds = useMemo(
    () => allFinalCases.filter((item) => selectedCaseIds.includes(item.case_id) && item.side_effect).map((item) => item.case_id),
    [allFinalCases, selectedCaseIds],
  );
  const activeNav = navItems.find((item) => item.key === page) ?? navItems[0];
  const currentStep = execution ? 6 : batchApproval ? 5 : ["READY_FOR_EXECUTION", "READY_WITH_SKIPS"].includes(queue?.status ?? "") ? 4 : startingWorkflow || workflow?.status === "WAITING_REQUIREMENT_APPROVAL" ? 2 : workflow ? 3 : parsedDocument ? 1 : 0;
  const overviewAction = overviewActions[Math.min(currentStep, overviewActions.length - 1)];

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
        setSelectedOperationIds(isQueueTerminal(latestQueue.status) ? [] : latestQueue.selected_api_ids.slice(0, 1));
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
    const queueRunId = queue?.run_id;
    if (!selectedProject || !queueRunId || !["READY_FOR_EXECUTION", "READY_WITH_SKIPS"].includes(queue?.status ?? "")) return;
    let cancelled = false;
    const projectId = selectedProject.project_id;
      void api.reports(projectId)
      .then((reports) => reports
        .filter((report) => report.queue_run_id === queueRunId)
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
    const currentItem = queue.items[queue.current_index];
    const canReuseNlu = Boolean(
      currentItem?.workflow_id
      && ["FAILED", "BLOCKED"].includes(currentItem.status)
      && ["DESIGNER", "REVIEWER"].includes(currentItem.current_stage),
    );
    setBusy(true);
    setStartingWorkflow(true);
    setMessage(canReuseNlu ? "正在复用已缓存的需求分析，重试用例设计与检查…" : "正在重新分析当前接口的需求…");
    try {
      if (!canReuseNlu) {
        const started = await api.startProcessingQueue(selectedProject.project_id, queue.run_id);
        setQueue(started.queue);
        setWorkflow(started.workflow);
        setPage("requirements");
        setMessage("当前接口已重新生成需求，请确认后继续。");
        return;
      }

      const retried = await api.retryCachedDesign(selectedProject.project_id, queue.run_id);
      setQueue(retried.queue);
      setWorkflow(retried.workflow);
      const settledQueue = await waitForQueueSettled(
        selectedProject.project_id,
        retried.queue.run_id,
        600,
      ) ?? retried.queue;
      setQueue(settledQueue);
      const settledItem = settledQueue.items[settledQueue.current_index];
      if (["READY_FOR_EXECUTION", "READY_WITH_SKIPS"].includes(settledQueue.status)) {
        const cases = await api.projectFinalCases(selectedProject.project_id);
        setFinalCaseSets(cases);
        setSelectedCaseIds(cases.flatMap((item) => item.cases).map((item) => item.case_id));
        setSelectedOperationIds([]);
        setSelectedOperation(null);
        setPage("cases");
        setMessage("已复用需求分析结果并完成用例设计，可以继续执行确认。");
      } else if (settledItem?.workflow_id) {
        const settledWorkflow = await api.workflowRun(selectedProject.project_id, settledItem.workflow_id);
        setWorkflow(settledWorkflow);
        setSelectedOperation(operations.find((item) => item.operation_id === settledItem.api_operation_id) ?? selectedOperation);
        setPage("requirements");
        setMessage(
          settledQueue.status === "BLOCKED"
            ? `已复用需求分析结果，但仍有待处理缺口：${settledItem.error_message ?? "请查看审查结果"}`
            : settledQueue.status === "FAILED"
              ? `复用需求分析后的用例设计仍失败：${settledItem.error_message ?? "后台任务失败"}`
              : "已复用需求分析结果，当前接口已进入下一节点。",
        );
      } else {
        setPage("requirements");
        setMessage("后台仍在重试用例设计，稍后刷新即可查看结果。");
      }
    } catch (error) {
      setMessage(`重试失败：${error instanceof Error ? error.message : "分析任务执行失败"}`);
    } finally {
      setBusy(false);
      setStartingWorkflow(false);
    }
  }

  async function skipWorkflowQueue() {
    if (!selectedProject || !queue || queue.status !== "BLOCKED") return;
    setBusy(true);
    setMessage("正在跳过当前接口，并保留其审查缺口…");
    try {
      let settledQueue = await api.skipProcessingQueue(
        selectedProject.project_id,
        queue.run_id,
        "用户确认跳过当前需要人工处理的接口",
      );
      setQueue(settledQueue);
      if (settledQueue.status === "RUNNING") {
        settledQueue = await waitForQueueSettled(
          selectedProject.project_id,
          settledQueue.run_id,
          600,
        ) ?? settledQueue;
        setQueue(settledQueue);
      }
      const currentItem = settledQueue.items[settledQueue.current_index];
      if (settledQueue.status === "WAITING_REQUIREMENT_APPROVAL" && currentItem?.workflow_id) {
        const nextWorkflow = await api.workflowRun(selectedProject.project_id, currentItem.workflow_id);
        setWorkflow(nextWorkflow);
        setSelectedOperation(operations.find((item) => item.operation_id === currentItem.api_operation_id) ?? null);
        setSelectedOperationIds([currentItem.api_operation_id]);
        setPage("requirements");
        setMessage(`当前接口已跳过，下一接口等待需求确认（${settledQueue.current_index + 1} / ${settledQueue.items.length}）。`);
        return;
      }
      if (settledQueue.status === "BLOCKED" && currentItem?.workflow_id) {
        const nextWorkflow = await api.workflowRun(selectedProject.project_id, currentItem.workflow_id);
        setWorkflow(nextWorkflow);
        setSelectedOperation(operations.find((item) => item.operation_id === currentItem.api_operation_id) ?? null);
        setSelectedOperationIds([currentItem.api_operation_id]);
        setPage("requirements");
        setMessage(`下一个接口也需要人工处理：${currentItem.error_message ?? "请查看审查缺口"}`);
        return;
      }
      const cases = await api.projectFinalCases(selectedProject.project_id);
      setFinalCaseSets(cases);
      setSelectedCaseIds(cases.flatMap((item) => item.cases).map((item) => item.case_id));
      setSelectedOperationIds([]);
      setSelectedOperation(null);
      if (cases.length) {
        setPage("cases");
        setMessage(settledQueue.status === "READY_WITH_SKIPS" ? "当前接口已跳过，已生成接口仍可进入批量执行。" : "当前接口已跳过，可继续选择下一个接口。");
      } else {
        setPage("operations");
        setMessage("当前接口已跳过，可继续选择下一个接口；原审查结果仍已保留。");
      }
    } catch (error) {
      setMessage(`跳过失败：${error instanceof Error ? error.message : "无法跳过当前接口"}`);
    } finally {
      setBusy(false);
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

  function prepareNewCaseSelection() {
    setBatchApproval(null);
    setExecution(null);
    setSelectedResult(null);
    setSideEffectsConfirmed(false);
  }

  function toggleCase(caseId: string) {
    prepareNewCaseSelection();
    setSelectedCaseIds((current) => current.includes(caseId) ? current.filter((id) => id !== caseId) : [...current, caseId]);
  }

  function toggleCaseSet(caseSet: FinalCaseSet) {
    const ids = caseSet.cases.map((item) => item.case_id);
    prepareNewCaseSelection();
    setSelectedCaseIds((current) => {
      const allSelected = ids.every((id) => current.includes(id));
      return allSelected
        ? current.filter((id) => !ids.includes(id))
        : [...current, ...ids.filter((id) => !current.includes(id))];
    });
  }

  function toggleAllCases() {
    const ids = allFinalCases.map((item) => item.case_id);
    prepareNewCaseSelection();
    setSelectedCaseIds((current) => ids.every((id) => current.includes(id)) ? [] : ids);
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
      if (["READY_FOR_EXECUTION", "READY_WITH_SKIPS"].includes(settledQueue.status)) {
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
      setBatchApproval(null);
      setExecution(result);
      setPage("reports");
      setMessage(`执行完成：${result.run.passed_count} 条 PASS，${result.run.failed_count} 条 FAIL，${result.run.error_count} 条错误。`);
    } catch (error) {
      setBatchApproval(null);
      setMessage(error instanceof Error ? error.message : "执行失败");
    } finally {
      setBusy(false);
    }
  }

  function exportReportHtml() {
    if (!execution) return;
    downloadReportHtml(execution, selectedProject, allFinalCases);
    setMessage("测试报告已导出为 HTML 文件。");
  }

  function renderProjectEmpty() {
    return <section className="empty-card empty-card-large"><div className="empty-mark">项目</div><h3>还没有测试项目</h3><p>需求文档可以先独立解析；如需读取源码、数据库和接口契约，再创建一个测试项目作为辅助证据上下文。</p><button className="button button-primary" onClick={() => setShowCreateForm(true)}>创建测试项目</button></section>;
  }

  function updateProjectEditor(patch: Partial<ProjectEditor>) {
    setProjectEditor((current) => current ? { ...current, ...patch } : current);
  }

  function renderProjectSettingsPage() {
    return <ProjectSettingsPage
      selectedProject={selectedProject}
      projectEditor={projectEditor}
      showCreateForm={showCreateForm}
      busy={busy}
      newProjectName={newProjectName}
      newProjectDescription={newProjectDescription}
      newBaseUrl={newBaseUrl}
      newOpenapiSource={newOpenapiSource}
      newWorkspace={newWorkspace}
      newDbEnabled={newDbEnabled}
      newDbDialect={newDbDialect}
      newDbRef={newDbRef}
      newDbSchema={newDbSchema}
      newDbTables={newDbTables}
      onNewProjectNameChange={setNewProjectName}
      onNewProjectDescriptionChange={setNewProjectDescription}
      onNewBaseUrlChange={setNewBaseUrl}
      onNewOpenapiSourceChange={setNewOpenapiSource}
      onNewWorkspaceChange={setNewWorkspace}
      onNewDbEnabledChange={setNewDbEnabled}
      onNewDbDialectChange={setNewDbDialect}
      onNewDbRefChange={setNewDbRef}
      onNewDbSchemaChange={setNewDbSchema}
      onNewDbTablesChange={setNewDbTables}
      onCreateProject={() => void createProject()}
      onCancelCreate={() => setShowCreateForm(false)}
      onStartCreate={startCreateProject}
      onDeleteSelectedProject={() => void deleteSelectedProject()}
      onSaveProjectSettings={() => void saveProjectSettings()}
      onUpdateEditor={updateProjectEditor}
      onCreateEmptyProject={() => setShowCreateForm(true)}
    />;
  }

  function renderCreateForm() {
    return renderProjectSettingsPage();
  }

  function renderDocuments() {
    return <RequirementDocumentsPage
      hasProject={Boolean(selectedProject)}
      activeFlowOperationId={activeFlowOperationId}
      documentText={documentText}
      documentError={documentError}
      busy={busy}
      parsedDocument={parsedDocument}
      requirementDocuments={requirementDocuments}
      operations={operations}
      onFileDocument={(file) => void parseFileDocument(file)}
      onDocumentTextChange={(value) => {
        setDocumentText(value);
        if (parsedDocument) {
          resetRequirementContext();
          setMessage("正在输入新的需求内容；已上传的文档仍会保留。");
        }
      }}
      onParseText={() => void parseTextDocument()}
      onSelectDocument={selectRequirementDocument}
    />;
  }

  function renderOverview() {
    if (showCreateForm) return renderCreateForm();
    if (!selectedProject) return renderProjectEmpty();
    return <>
      <div className="page-heading overview-heading">
        <div>
          <span className="kicker">当前项目</span>
          <h2>{selectedProject.name}</h2>
          <p>从 Markdown 需求到批量执行与测试报告，当前任务按接口顺序推进。</p>
        </div>
        <button className="button button-primary" onClick={() => setPage(overviewAction.page)}>{overviewAction.label}</button>
      </div>
      <div className="stats-grid stats-grid-three">
        <div className="metric-card"><span>可测试接口</span><strong>{operations.length}</strong><small>从需求文档识别</small></div>
        <div className="metric-card"><span>当前需求文档</span><strong>{parsedDocument ? "已解析" : "—"}</strong><small>{parsedDocument?.filename ?? "尚未上传文档"}</small></div>
        <div className="metric-card"><span>项目用例</span><strong>{allFinalCases.length}</strong><small>{finalCaseSets.length ? `已完成 ${finalCaseSets.length} 个接口` : "尚未生成用例"}</small></div>
      </div>
      <section className="card workflow-card">
        <div className="card-heading">
          <div>
            <span className="kicker">当前任务</span>
            <h3>{selectedOperation ? `${selectedOperation.method} ${selectedOperation.path}` : parsedDocument?.filename ?? "等待上传需求文档"}</h3>
          </div>
          <span className={`status-badge ${currentStep >= 4 ? "status-ready" : currentStep > 0 ? "status-warning" : "status-neutral"}`}>{workflowSteps[currentStep]}</span>
        </div>
        <div className="next-step-panel">
          <div>
            <span>下一步</span>
            <strong>{overviewAction.label}</strong>
          </div>
          <p>{overviewAction.description}</p>
        </div>
      </section>
    </>;
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
    const canReuseNlu = Boolean(
      item?.workflow_id
      && ["FAILED", "BLOCKED"].includes(item.status)
      && ["DESIGNER", "REVIEWER"].includes(item.current_stage),
    );
    return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>{canReuseNlu ? "用例设计失败" : "顺序分析失败"}</h2><p>{canReuseNlu ? "NLU 需求、证据和测试点已保存；重试将直接复用这些结果，不再重复调用需求分析。" : "后台分析任务已返回失败状态，当前队列和失败原因已保留。你可以重试当前接口，也可以跳过它继续处理后续接口。"}</p></div><span className="status-badge status-danger">失败</span></div><section className="card workflow-failure-card"><div className="workflow-loading-mark">!</div><h3>当前接口未进入下一节点</h3><p>{item?.error_message ?? message}</p><div className="workflow-start-facts"><div><span>处理队列</span><strong>{queue.items.length} 个接口</strong></div><div><span>当前接口</span><strong>第 {queue.current_index + 1} 个接口</strong></div><div><span>队列状态</span><strong>{statusText(queue.status)}</strong></div></div><div className="gate-actions"><button className="button button-primary" onClick={() => void retryWorkflowQueue()} disabled={busy}>{canReuseNlu ? "复用需求结果重试" : "重新分析当前接口"}</button>{queue.status === "BLOCKED" && <button className="button button-secondary" onClick={() => void skipWorkflowQueue()} disabled={busy}>跳过并继续</button>}<button className="button button-ghost" onClick={() => setPage("operations")} disabled={busy}>返回接口目录</button></div></section></>;
  }

  function renderWorkflowSkipped() {
    return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>接口已跳过</h2><p>当前接口的审查缺口已保留，未冻结为可执行用例；你可以继续选择其他接口。</p></div><span className="status-badge status-warning">已跳过</span></div><section className="card workflow-failure-card"><div className="workflow-loading-mark">↷</div><h3>当前接口未进入执行用例库</h3><p>跳过只会解除队列阻塞，不会改变 Reviewer 的审查结论。</p><div className="gate-actions"><button className="button button-primary" onClick={() => setPage("operations")}>继续选择接口</button><button className="button button-secondary" onClick={() => setPage("cases")} disabled={!finalCaseSets.length}>查看已生成用例</button></div></section></>;
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
    const allCasesSelected = caseCount > 0 && allFinalCases.every((item) => selectedCaseIds.includes(item.case_id));
    const someCasesSelected = allFinalCases.some((item) => selectedCaseIds.includes(item.case_id));
    const caseSelectionLocked = Boolean(batchApproval);
    return <>
      <div className="page-heading">
        <div><span className="kicker">测试设计结果</span><h2>测试用例</h2><p>每个接口独立生成用例，并持续累计到当前项目；展开接口即可查看和选择用例。</p></div>
        <span className="status-badge status-ready">已完成 {finalCaseSets.length} 个接口</span>
      </div>
      <div className="stats-grid"><div className="metric-card"><span>测试用例</span><strong>{caseCount}</strong><small>项目累计用例</small></div><div className="metric-card"><span>自动补充</span><strong>{reviewerAdded}</strong><small>发现覆盖缺口时补充</small></div><div className="metric-card"><span>副作用用例</span><strong>{allFinalCases.filter((item) => item.side_effect).length}</strong><small>执行前需要确认</small></div><div className="metric-card"><span>待解决问题</span><strong>{unresolved}</strong><small>{unresolved ? "进入执行前需人工确认" : "已完成冻结"}</small></div></div>
      <section className="card case-library-card">
        <div className="toolbar"><div><strong>批次用例选择</strong><span>{selectedCaseIds.length} / {caseCount} 条已选择</span></div><div className="toolbar-actions"><label className="case-select-all"><input type="checkbox" checked={allCasesSelected} ref={(node) => { if (node) node.indeterminate = someCasesSelected && !allCasesSelected; }} onChange={toggleAllCases} disabled={caseSelectionLocked} /><span>全部接口用例</span></label><button className="button button-small button-secondary" onClick={() => setPage("operations")}>继续选择接口</button><button className="button button-small button-primary" onClick={() => setPage("execution")} disabled={!selectedCaseIds.length}>进入统一执行确认</button></div></div>
        <div className="case-accordion-list">{finalCaseSets.map((set) => {
          const operation = operations.find((item) => item.operation_id === set.api_operation_id);
          const operationLabel = operation ? `${operation.method} ${operation.path}` : set.api_operation_id ?? set.requirement_id;
          const selectedCount = set.cases.filter((item) => selectedCaseIds.includes(item.case_id)).length;
          const allSetCasesSelected = set.cases.length > 0 && selectedCount === set.cases.length;
          const someSetCasesSelected = selectedCount > 0 && !allSetCasesSelected;
          return <details className="case-accordion" key={set.final_case_set_id}>
            <summary><input className="case-set-checkbox" type="checkbox" aria-label={`选择 ${operationLabel} 的全部用例`} checked={allSetCasesSelected} ref={(node) => { if (node) node.indeterminate = someSetCasesSelected; }} onClick={(event) => event.stopPropagation()} onChange={() => toggleCaseSet(set)} disabled={caseSelectionLocked} /><span className="case-summary-copy"><strong>{operationLabel}</strong><small>{set.cases.length} 条用例 · 已选择 {selectedCount} 条</small></span><span className="status-badge status-ready">用例已生成</span></summary>
            <div className="table-wrap"><table><thead><tr><th className="check-col">选择</th><th>用例</th><th>分类</th><th>预期行为</th><th>副作用</th></tr></thead><tbody>{set.cases.map((testCase) => <tr key={testCase.case_id}><td className="check-col"><input type="checkbox" aria-label={`选择用例 ${testCase.title}`} checked={selectedCaseIds.includes(testCase.case_id)} onChange={() => toggleCase(testCase.case_id)} disabled={caseSelectionLocked} /></td><td><strong>{testCase.title}</strong><small className="table-subtext">{testCase.case_id}</small></td><td>{testCase.category}</td><td className="expected-cell">{testCase.expected_behavior}</td><td>{testCase.side_effect ? <span className="status-badge status-warning">需确认</span> : <span className="status-badge status-neutral">无</span>}</td></tr>)}</tbody></table></div>
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
    return renderProjectSettingsPage();
  }
  function renderPage() {
    const content = (() => {
      switch (page) {
        case "overview": return renderOverview();
        case "documents": return renderDocuments();
        case "operations": return renderOperations();
        case "requirements": return queue?.status === "SKIPPED" && !startingWorkflow ? renderWorkflowSkipped() : ["FAILED", "BLOCKED"].includes(queue?.status ?? "") && !startingWorkflow ? renderWorkflowFailure() : renderRequirements();
        case "cases": return renderCases();
        case "execution": return renderExecution();
        case "reports": return renderReports();
        case "settings": return renderSettings();
        default: return null;
      }
    })();
    return <>{content}{parseSuccess && <div className="modal-backdrop" role="presentation" onClick={() => setParseSuccess(null)}><section className="success-modal" role="dialog" aria-modal="true" aria-labelledby="parse-success-title" onClick={(event) => event.stopPropagation()}><button className="modal-close" aria-label="关闭" onClick={() => setParseSuccess(null)}>×</button><div className="success-icon">✓</div><span className="kicker">文档解析</span><h2 id="parse-success-title">需求文档解析成功</h2><p className="success-modal-copy">“{parseSuccess.filename}”已完成解析，后续流程将使用这份规范化需求文档。</p><div className="success-modal-facts"><div><span>字符数</span><strong>{parseSuccess.charCount.toLocaleString()}</strong></div><div><span>行数</span><strong>{parseSuccess.lineCount.toLocaleString()}</strong></div><div><span>文档编号</span><code title={parseSuccess.documentId}>{parseSuccess.documentId}</code></div></div>{parseSuccess.operationCount !== undefined && <p className="success-modal-hint">已从需求原文识别 {parseSuccess.operationCount} 个可测试接口，请在接口目录选择需要分析的接口。</p>}<div className="modal-actions"><button className="button button-primary" onClick={() => setParseSuccess(null)}>继续查看</button>{parseSuccess.operationCount !== undefined && <button className="button button-secondary" onClick={() => { setParseSuccess(null); setPage("operations"); }}>查看接口目录</button>}</div></section></div>}{saveSuccess && <div className="modal-backdrop" role="presentation" onClick={() => setSaveSuccess(null)}><section className="success-modal" role="dialog" aria-modal="true" aria-labelledby="save-success-title" onClick={(event) => event.stopPropagation()}><button className="modal-close" aria-label="关闭" onClick={() => setSaveSuccess(null)}>×</button><div className="success-icon">{saveSuccess.authSuccess ? "✓" : "!"}</div><span className="kicker">项目设置</span><h2 id="save-success-title">{saveSuccess.authSuccess ? "保存成功" : "已保存，但鉴权预检失败"}</h2><p className="success-modal-copy">项目“{saveSuccess.name}”的配置已保存，刷新页面后仍会保留。</p><p className={`success-modal-hint ${saveSuccess.authSuccess ? "" : "save-auth-failed"}`}>{saveSuccess.authMessage}</p><div className="modal-actions"><button className="button button-primary" onClick={() => setSaveSuccess(null)}>知道了</button></div></section></div>}</>;
  }

  return (
    <AppShell
      projects={projects}
      selectedProject={selectedProject}
      page={page}
      activeNav={activeNav}
      currentStep={currentStep}
      message={message}
      busy={busy}
      onSelectProject={selectProject}
      onCreateProject={() => setShowCreateForm(true)}
      onNavigate={setPage}
    >
      {renderPage()}
    </AppShell>
  );
}
