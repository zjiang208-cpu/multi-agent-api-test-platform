import { api } from "../api/client";
import { operationsForDocument, sortRequirementDocuments } from "../app/platform";
import type { Dispatch, SetStateAction } from "react";
import type {
  ApiProcessingQueue,
  BatchExecutionResponse,
  BatchExecutionApproval,
  ExecutionApproval,
  FinalCaseSet,
  OperationContract,
  ParsedRequirementDocument,
  TestProject,
  WorkflowRunSnapshot,
} from "../types/api";
import type { PageKey, ParseSuccessNotice } from "../app/platform";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface DocumentActionContext {
  activeFlowOperationId: string | null;
  selectedProject: TestProject | null;
  parsedDocument: ParsedRequirementDocument | null;
  documentText: string;
  setParsedDocument: StateSetter<ParsedRequirementDocument | null>;
  setRequirementDocuments: StateSetter<ParsedRequirementDocument[]>;
  setDocumentText: StateSetter<string>;
  setDocumentName: StateSetter<string>;
  setDocumentError: StateSetter<string>;
  setOperations: StateSetter<OperationContract[]>;
  setSelectedOperation: StateSetter<OperationContract | null>;
  setSelectedOperationIds: StateSetter<string[]>;
  setQueue: StateSetter<ApiProcessingQueue | null>;
  setWorkflow: StateSetter<WorkflowRunSnapshot | null>;
  setApproval: StateSetter<ExecutionApproval | null>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setFinalCaseSets: StateSetter<FinalCaseSet[]>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setSelectedCaseIds: StateSetter<string[]>;
  setStartingWorkflow: StateSetter<boolean>;
  setBusy: StateSetter<boolean>;
  setMessage: StateSetter<string>;
  setPage: StateSetter<PageKey>;
  setParseSuccess: StateSetter<ParseSuccessNotice | null>;
}

export function createDocumentActions(context: DocumentActionContext) {
  const {
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
  } = context;

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

  return {
    resetWorkflowContext,
    resetRequirementContext,
    rememberRequirementDocument,
    selectRequirementDocument,
    parseTextDocument,
    parseFileDocument,
  };
}
