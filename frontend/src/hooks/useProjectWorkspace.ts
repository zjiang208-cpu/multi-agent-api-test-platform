import { useEffect } from "react";
import { api } from "../api/client";
import {
  isQueueTerminal,
  operationsForDocument,
  sortRequirementDocuments,
} from "../app/platform";
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
import type { Dispatch, SetStateAction } from "react";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface ProjectWorkspaceLoaderProps {
  selectedProject: TestProject | null;
  setProjects: StateSetter<TestProject[]>;
  setSelectedProject: StateSetter<TestProject | null>;
  setMessage: StateSetter<string>;
  setOperations: StateSetter<OperationContract[]>;
  setRequirementDocuments: StateSetter<ParsedRequirementDocument[]>;
  setParsedDocument: StateSetter<ParsedRequirementDocument | null>;
  setBaseUrl: StateSetter<string>;
  setSelectedOperationIds: StateSetter<string[]>;
  setSelectedOperation: StateSetter<OperationContract | null>;
  setQueue: StateSetter<ApiProcessingQueue | null>;
  setFinalCaseSets: StateSetter<FinalCaseSet[]>;
  setWorkflow: StateSetter<WorkflowRunSnapshot | null>;
  setApproval: StateSetter<ExecutionApproval | null>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setStartingWorkflow: StateSetter<boolean>;
  setDocumentText: StateSetter<string>;
  setDocumentName: StateSetter<string>;
}

export function useProjectWorkspace({
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
}: ProjectWorkspaceLoaderProps) {
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
}
