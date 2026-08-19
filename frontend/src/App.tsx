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
import { createWorkflowActions } from "./app/workflowActions";
import { createDocumentActions } from "./app/documentActions";
import { createProjectActions } from "./app/projectActions";
import { createExecutionActions } from "./app/executionActions";
import { createCaseSelectionActions } from "./app/caseSelectionActions";
import { createSelectionActions } from "./app/selectionActions";
import { useProjectWorkspace } from "./hooks/useProjectWorkspace";
import { useExecutionState } from "./hooks/useExecutionState";
import { AppPageRouter } from "./components/AppPageRouter";
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

  useExecutionState({
    selectedProject,
    queue,
    workflowId: workflow?.workflow_id,
    finalCaseSetId: finalCases?.final_case_set_id,
    finalCaseSetsLength: finalCaseSets.length,
    allFinalCases,
    execution,
    setSelectedCaseIds,
    setApproval,
    setBatchApproval,
    setExecution,
    setSideEffectsConfirmed,
    setSelectedResult,
    setMessage,
  });


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

  const pageState = {
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
  };
  const pageActions = {
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
    updateProjectEditor: (patch: Partial<ProjectEditor>) => {
      setProjectEditor((current) => current ? { ...current, ...patch } : current);
    },
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
  };










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
      <AppPageRouter state={pageState} actions={pageActions} />
    </AppShell>
  );
}
