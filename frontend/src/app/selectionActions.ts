import type { Dispatch, SetStateAction } from "react";
import type { PageKey } from "../app/platform";
import type {
  ApiProcessingQueue,
  BatchExecutionApproval,
  BatchExecutionResponse,
  ExecutionApproval,
  FinalCaseSet,
  OperationContract,
  ParsedRequirementDocument,
  TestProject,
  WorkflowRunSnapshot,
} from "../types/api";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface SelectionActionContext {
  activeFlowOperationId: string | null;
  selectedOperationIds: string[];
  completedOperationIds: ReadonlySet<string>;
  selectedProject: TestProject | null;
  requirementDocuments: ParsedRequirementDocument[];
  parsedDocument: ParsedRequirementDocument | null;
  operations: OperationContract[];
  setSelectedOperation: StateSetter<OperationContract | null>;
  setSelectedOperationIds: StateSetter<string[]>;
  setMessage: StateSetter<string>;
  setQueue: StateSetter<ApiProcessingQueue | null>;
  setWorkflow: StateSetter<WorkflowRunSnapshot | null>;
  setApproval: StateSetter<ExecutionApproval | null>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setStartingWorkflow: StateSetter<boolean>;
  setParsedDocument: StateSetter<ParsedRequirementDocument | null>;
  setDocumentName: StateSetter<string>;
  setDocumentText: StateSetter<string>;
  setPage: StateSetter<PageKey>;
  setSelectedProject: StateSetter<TestProject | null>;
  setFinalCaseSets: StateSetter<FinalCaseSet[]>;
}

export function createSelectionActions(context: SelectionActionContext) {
  const {
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
  } = context;

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
    // 保留已累计生成的用例，但开始新接口前清理上一个接口的临时队列、
    // 执行许可和报告状态。
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


  function toggleOperation(operationId: string) {
    const operation = operations.find((item) => item.operation_id === operationId);
    if (operation) selectOperation(operation);
  }

  return {
    selectOperation,
    selectProject,
    toggleOperation,
  };
}

