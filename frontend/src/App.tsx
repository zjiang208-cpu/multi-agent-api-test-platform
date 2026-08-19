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
  TestProject,
  WorkflowRunSnapshot,
} from "./types/api";
import {
  isQueueTerminal,
  navGroups,
  navItems,
  operationsForDocument,
  overviewActions,
  projectEditorFrom,
  workflowSteps,
} from "./app/platform";
import type { PageKey, ParseSuccessNotice, ProjectEditor } from "./app/platform";
import { AppShell } from "./components/AppShell";
import { OverviewPage } from "./components/OverviewPage";
import { OperationsPage } from "./components/OperationsPage";
import { ProjectSettingsPage } from "./components/ProjectSettingsPage";
import { RequirementDocumentsPage } from "./components/RequirementDocumentsPage";
import { RequirementReviewPage } from "./components/RequirementReviewPage";
import { TestCasesPage } from "./components/TestCasesPage";
import { ExecutionPage } from "./components/ExecutionPage";
import { ReportsPage } from "./components/ReportsPage";
import { WorkflowStatusPage } from "./components/WorkflowStatusPage";
import { createWorkflowActions } from "./app/workflowActions";
import { createDocumentActions } from "./app/documentActions";
import { createProjectActions } from "./app/projectActions";
import { createExecutionActions } from "./app/executionActions";
import { createCaseSelectionActions } from "./app/caseSelectionActions";
import { createSelectionActions } from "./app/selectionActions";
import { useProjectWorkspace } from "./hooks/useProjectWorkspace";
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
  const projectActions = createProjectActions({
    projects,
    selectedProject,
    projectEditor,
    newProjectName,
    newProjectDescription,
    newBaseUrl,
    newOpenapiSource,
    newWorkspace,
    newDbEnabled,
    newDbDialect,
    newDbRef,
    newDbSchema,
    newDbTables,
    setProjects,
    setSelectedProject,
    setShowCreateForm,
    setPage,
    setMessage,
    setBusy,
    setSaveSuccess,
    setBaseUrl,
    setOperations,
  });
  const {
    createProject,
    startCreateProject,
    saveProjectSettings,
    deleteSelectedProject,
    discoverOperations,
  } = projectActions;

  const documentActions = createDocumentActions({
    activeFlowOperationId,
    selectedProject,
    parsedDocument,
    documentText,
    setParsedDocument,
    setRequirementDocuments,
    setDocumentText,
    setDocumentName,
    setDocumentError,
    setOperations,
    setSelectedOperation,
    setSelectedOperationIds,
    setQueue,
    setWorkflow,
    setApproval,
    setBatchApproval,
    setFinalCaseSets,
    setExecution,
    setSelectedCaseIds,
    setStartingWorkflow,
    setBusy,
    setMessage,
    setPage,
    setParseSuccess,
  });
  const {
    resetRequirementContext,
    rememberRequirementDocument,
    selectRequirementDocument,
    parseTextDocument,
    parseFileDocument,
  } = documentActions;

  const selectionActions = createSelectionActions({
    activeFlowOperationId,
    selectedOperationIds,
    completedOperationIds,
    selectedProject,
    requirementDocuments,
    parsedDocument,
    operations,
    setSelectedOperation,
    setSelectedOperationIds,
    setMessage,
    setQueue,
    setWorkflow,
    setApproval,
    setBatchApproval,
    setExecution,
    setStartingWorkflow,
    setParsedDocument,
    setDocumentName,
    setDocumentText,
    setPage,
    setSelectedProject,
    setFinalCaseSets,
  });
  const {
    selectOperation,
    selectProject,
    toggleOperation,
  } = selectionActions;


  const caseSelectionActions = createCaseSelectionActions({
    allFinalCases,
    setSelectedCaseIds,
    setBatchApproval,
    setExecution,
    setSelectedResult,
    setSideEffectsConfirmed,
  });
  const {
    toggleCase,
    toggleCaseSet,
    toggleAllCases,
  } = caseSelectionActions;


  const executionActions = createExecutionActions({
    selectedProject,
    selectedCaseIds,
    targetEnvironment,
    baseUrl,
    sideEffectCaseIds,
    sideEffectsConfirmed,
    batchApproval,
    execution,
    allFinalCases,
    setBusy,
    setBatchApproval,
    setExecution,
    setPage,
    setMessage,
  });
  const {
    approveForExecution,
    executeApproved,
    exportReportHtml,
  } = executionActions;

  const workflowActions = createWorkflowActions({
    selectedOperationIds,
    selectedOperation,
    selectedProject,
    parsedDocument,
    completedOperationIds,
    operations,
    workflow,
    queue,
    rememberRequirementDocument,
    setBusy,
    setStartingWorkflow,
    setMessage,
    setWorkflow,
    setApproval,
    setBatchApproval,
    setExecution,
    setQueue,
    setPage,
    setSelectedOperation,
    setSelectedOperationIds,
    setDocumentText,
    setOperations,
    setFinalCaseSets,
    setSelectedCaseIds,
  });
  const {
    runWorkflow,
    retryWorkflowQueue,
    skipWorkflowQueue,
    approveCurrentRequirement,
  } = workflowActions;

  useProjectWorkspace({
    selectedProject,
    setProjects,
    setSelectedProject,
    setMessage,
    setOperations,
    setRequirementDocuments,
    setParsedDocument,
    setBaseUrl,
    setSelectedOperationIds,
    setSelectedOperation,
    setQueue,
    setFinalCaseSets,
    setWorkflow,
    setApproval,
    setBatchApproval,
    setExecution,
    setStartingWorkflow,
    setDocumentText,
    setDocumentName,
  });

  useEffect(() => {
    window.sessionStorage.setItem("api-test-platform.page", page);
  }, [page]);

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
    return <OverviewPage
      showCreateForm={showCreateForm}
      createForm={renderCreateForm()}
      emptyState={renderProjectEmpty()}
      selectedProject={selectedProject}
      operations={operations}
      parsedDocument={parsedDocument}
      allFinalCases={allFinalCases}
      finalCaseSets={finalCaseSets}
      selectedOperation={selectedOperation}
      currentStep={currentStep}
      overviewAction={overviewAction}
      workflowSteps={workflowSteps}
      onNavigate={setPage}
    />;
  }

  function renderOperations() {
    return <OperationsPage
      showCreateForm={showCreateForm}
      createForm={renderCreateForm()}
      emptyState={renderProjectEmpty()}
      selectedProject={selectedProject}
      operations={operations}
      requirementDocuments={requirementDocuments}
      parsedDocument={parsedDocument}
      selectedOperation={selectedOperation}
      selectedOperationIds={selectedOperationIds}
      completedOperationIds={completedOperationIds}
      activeFlowOperationId={activeFlowOperationId}
      busy={busy}
      onNavigate={setPage}
      onSelectOperation={selectOperation}
      onRunWorkflow={() => void runWorkflow()}
      onToggleOperation={toggleOperation}
    />;
  }

  function renderWorkflowFailure() {
    return <WorkflowStatusPage
      mode="failure"
      queue={queue}
      message={message}
      finalCaseSets={finalCaseSets}
      busy={busy}
      onRetry={() => void retryWorkflowQueue()}
      onSkip={() => void skipWorkflowQueue()}
      onNavigate={setPage}
    />;
  }

  function renderWorkflowSkipped() {
    return <WorkflowStatusPage
      mode="skipped"
      queue={queue}
      message={message}
      finalCaseSets={finalCaseSets}
      busy={busy}
      onRetry={() => void retryWorkflowQueue()}
      onSkip={() => void skipWorkflowQueue()}
      onNavigate={setPage}
    />;
  }

  function renderRequirements() {
    return <RequirementReviewPage
      startingWorkflow={startingWorkflow}
      message={message}
      queue={queue}
      workflow={workflow}
      selectedOperation={selectedOperation}
      operations={operations}
      busy={busy}
      onApproveCurrentRequirement={() => void approveCurrentRequirement()}
      onNavigate={setPage}
    />;
  }


  function renderCases() {
    return <TestCasesPage
      finalCaseSets={finalCaseSets}
      allFinalCases={allFinalCases}
      operations={operations}
      selectedCaseIds={selectedCaseIds}
      batchApproval={batchApproval}
      onNavigate={setPage}
      onToggleAllCases={toggleAllCases}
      onToggleCase={toggleCase}
      onToggleCaseSet={toggleCaseSet}
    />;
  }


  function renderExecution() {
    return <ExecutionPage
      allFinalCases={allFinalCases}
      finalCaseSets={finalCaseSets}
      batchApproval={batchApproval}
      selectedCaseIds={selectedCaseIds}
      targetEnvironment={targetEnvironment}
      baseUrl={baseUrl}
      sideEffectCaseIds={sideEffectCaseIds}
      sideEffectsConfirmed={sideEffectsConfirmed}
      busy={busy}
      onNavigate={setPage}
      onTargetEnvironmentChange={setTargetEnvironment}
      onBaseUrlChange={setBaseUrl}
      onSideEffectsConfirmedChange={setSideEffectsConfirmed}
      onApproveForExecution={() => void approveForExecution()}
      onExecuteApproved={(autoRegression) => void executeApproved(autoRegression)}
    />;
  }

  function renderReports() {
    return <ReportsPage
      execution={execution}
      allFinalCases={allFinalCases}
      operations={operations}
      selectedResult={selectedResult}
      onSelectResult={setSelectedResult}
      onClearResult={() => setSelectedResult(null)}
      onNavigate={setPage}
      onExportReportHtml={exportReportHtml}
    />;
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
