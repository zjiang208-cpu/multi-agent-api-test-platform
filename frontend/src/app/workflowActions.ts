import type { Dispatch, SetStateAction } from "react";
import { api } from "../api/client";
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
import type { PageKey } from "../app/platform";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface WorkflowActionContext {
  selectedOperationIds: string[];
  selectedOperation: OperationContract | null;
  selectedProject: TestProject | null;
  parsedDocument: ParsedRequirementDocument | null;
  completedOperationIds: ReadonlySet<string>;
  operations: OperationContract[];
  workflow: WorkflowRunSnapshot | null;
  queue: ApiProcessingQueue | null;
  rememberRequirementDocument: (document: ParsedRequirementDocument) => void;
  setBusy: StateSetter<boolean>;
  setStartingWorkflow: StateSetter<boolean>;
  setMessage: StateSetter<string>;
  setWorkflow: StateSetter<WorkflowRunSnapshot | null>;
  setApproval: StateSetter<ExecutionApproval | null>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setQueue: StateSetter<ApiProcessingQueue | null>;
  setPage: StateSetter<PageKey>;
  setSelectedOperation: StateSetter<OperationContract | null>;
  setSelectedOperationIds: StateSetter<string[]>;
  setDocumentText: StateSetter<string>;
  setOperations: StateSetter<OperationContract[]>;
  setFinalCaseSets: StateSetter<FinalCaseSet[]>;
  setSelectedCaseIds: StateSetter<string[]>;
}

export function createWorkflowActions(context: WorkflowActionContext) {
  const {
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
  } = context;

  async function waitForQueueSettled(projectId: string, runId: string, maxAttempts = 90): Promise<ApiProcessingQueue | null> {
    let latest: ApiProcessingQueue | null = null;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      latest = await api.processingQueue(projectId, runId);
      if (!["PENDING", "RUNNING"].includes(latest.status)) return latest;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    return latest;
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

  return {
    waitForQueueSettled,
    runWorkflow,
    retryWorkflowQueue,
    skipWorkflowQueue,
    approveCurrentRequirement,
  };
}
