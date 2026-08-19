import type { Dispatch, SetStateAction } from "react";
import { ExecutionPage } from "./ExecutionPage";
import { OperationsPage } from "./OperationsPage";
import { OverviewPage } from "./OverviewPage";
import { ProjectSettingsPage } from "./ProjectSettingsPage";
import { ReportsPage } from "./ReportsPage";
import { RequirementDocumentsPage } from "./RequirementDocumentsPage";
import { RequirementReviewPage } from "./RequirementReviewPage";
import { TestCasesPage } from "./TestCasesPage";
import { WorkflowStatusPage } from "./WorkflowStatusPage";
import type {
  ApiProcessingQueue,
  BatchExecutionApproval,
  BatchExecutionResponse,
  ExecutionResult,
  FinalCaseSet,
  OperationContract,
  ParsedRequirementDocument,
  TestCase,
  TestProject,
  WorkflowRunSnapshot,
} from "../types/api";
import type { PageKey, ParseSuccessNotice, ProjectEditor } from "../app/platform";

export interface SaveSuccessNotice {
  name: string;
  authSuccess: boolean;
  authMessage: string;
}

export interface PageRouterState {
  selectedProject: TestProject | null;
  projectEditor: ProjectEditor | null;
  showCreateForm: boolean;
  busy: boolean;
  newProjectName: string;
  newProjectDescription: string;
  newBaseUrl: string;
  newOpenapiSource: string;
  newWorkspace: string;
  newDbEnabled: boolean;
  newDbDialect: string;
  newDbRef: string;
  newDbSchema: string;
  newDbTables: string;
  activeFlowOperationId: string | null;
  documentText: string;
  documentError: string;
  parsedDocument: ParsedRequirementDocument | null;
  requirementDocuments: ParsedRequirementDocument[];
  operations: OperationContract[];
  selectedOperation: OperationContract | null;
  selectedOperationIds: string[];
  completedOperationIds: ReadonlySet<string>;
  allFinalCases: TestCase[];
  finalCaseSets: FinalCaseSet[];
  currentStep: number;
  overviewAction: { page: PageKey; label: string; description: string };
  workflowSteps: readonly string[];
  page: PageKey;
  startingWorkflow: boolean;
  message: string;
  queue: ApiProcessingQueue | null;
  workflow: WorkflowRunSnapshot | null;
  selectedCaseIds: string[];
  batchApproval: BatchExecutionApproval | null;
  targetEnvironment: string;
  baseUrl: string;
  sideEffectCaseIds: string[];
  sideEffectsConfirmed: boolean;
  execution: BatchExecutionResponse | null;
  selectedResult: ExecutionResult | null;
  parseSuccess: ParseSuccessNotice | null;
  saveSuccess: SaveSuccessNotice | null;
}

export interface PageRouterActions {
  setShowCreateForm: (value: boolean) => void;
  setNewProjectName: (value: string) => void;
  setNewProjectDescription: (value: string) => void;
  setNewBaseUrl: (value: string) => void;
  setNewOpenapiSource: (value: string) => void;
  setNewWorkspace: (value: string) => void;
  setNewDbEnabled: (value: boolean) => void;
  setNewDbDialect: (value: string) => void;
  setNewDbRef: (value: string) => void;
  setNewDbSchema: (value: string) => void;
  setNewDbTables: (value: string) => void;
  createProject: () => void;
  startCreateProject: () => void;
  deleteSelectedProject: () => void;
  saveProjectSettings: () => void;
  updateProjectEditor: (patch: Partial<ProjectEditor>) => void;
  setDocumentText: (value: string) => void;
  resetRequirementContext: () => void;
  setMessage: (value: string) => void;
  parseFileDocument: (file: File) => void;
  parseTextDocument: () => void;
  selectRequirementDocument: (document: ParsedRequirementDocument) => void;
  setPage: Dispatch<SetStateAction<PageKey>>;
  selectOperation: (operation: OperationContract) => void;
  runWorkflow: () => void;
  toggleOperation: (operationId: string) => void;
  retryWorkflowQueue: () => void;
  skipWorkflowQueue: () => void;
  approveCurrentRequirement: () => void;
  toggleAllCases: () => void;
  toggleCase: (caseId: string) => void;
  toggleCaseSet: (caseSet: FinalCaseSet) => void;
  setTargetEnvironment: (value: string) => void;
  setBaseUrl: (value: string) => void;
  setSideEffectsConfirmed: (value: boolean) => void;
  approveForExecution: () => void;
  executeApproved: (autoRegression?: boolean) => void;
  setSelectedResult: (result: ExecutionResult | null) => void;
  exportReportHtml: () => void;
  setParseSuccess: (notice: ParseSuccessNotice | null) => void;
  setSaveSuccess: (notice: SaveSuccessNotice | null) => void;
}

interface AppPageRouterProps {
  state: PageRouterState;
  actions: PageRouterActions;
}

export function AppPageRouter({ state, actions }: AppPageRouterProps) {
  const {
    selectedProject,
    projectEditor,
    showCreateForm,
    busy,
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
    activeFlowOperationId,
    documentText,
    documentError,
    parsedDocument,
    requirementDocuments,
    operations,
    selectedOperation,
    selectedOperationIds,
    completedOperationIds,
    allFinalCases,
    finalCaseSets,
    currentStep,
    overviewAction,
    workflowSteps,
    page,
    startingWorkflow,
    message,
    queue,
    workflow,
    selectedCaseIds,
    batchApproval,
    targetEnvironment,
    baseUrl,
    sideEffectCaseIds,
    sideEffectsConfirmed,
    execution,
    selectedResult,
    parseSuccess,
    saveSuccess,
  } = state;
  const {
    setShowCreateForm,
    setNewProjectName,
    setNewProjectDescription,
    setNewBaseUrl,
    setNewOpenapiSource,
    setNewWorkspace,
    setNewDbEnabled,
    setNewDbDialect,
    setNewDbRef,
    setNewDbSchema,
    setNewDbTables,
    createProject,
    startCreateProject,
    deleteSelectedProject,
    saveProjectSettings,
    updateProjectEditor,
    setDocumentText,
    resetRequirementContext,
    setMessage,
    parseFileDocument,
    parseTextDocument,
    selectRequirementDocument,
    setPage,
    selectOperation,
    runWorkflow,
    toggleOperation,
    retryWorkflowQueue,
    skipWorkflowQueue,
    approveCurrentRequirement,
    toggleAllCases,
    toggleCase,
    toggleCaseSet,
    setTargetEnvironment,
    setBaseUrl,
    setSideEffectsConfirmed,
    approveForExecution,
    executeApproved,
    setSelectedResult,
    exportReportHtml,
    setParseSuccess,
    setSaveSuccess,
  } = actions;

  function renderProjectEmpty() {
    return <section className="empty-card empty-card-large"><div className="empty-mark">项目</div><h3>还没有测试项目</h3><p>需求文档可以先独立解析；如需读取源码、数据库和接口契约，再创建一个测试项目作为辅助证据上下文。</p><button className="button button-primary" onClick={() => setShowCreateForm(true)}>创建测试项目</button></section>;
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

  return renderPage();
}
