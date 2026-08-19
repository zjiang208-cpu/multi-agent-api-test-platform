import { useEffect } from "react";
import { api } from "../api/client";
import type { Dispatch, SetStateAction } from "react";
import type {
  ApiProcessingQueue,
  BatchExecutionApproval,
  BatchExecutionResponse,
  ExecutionApproval,
  ExecutionResult,
  TestCase,
  TestProject,
} from "../types/api";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface ExecutionStateContext {
  selectedProject: TestProject | null;
  queue: ApiProcessingQueue | null;
  workflowId?: string;
  finalCaseSetId?: string;
  finalCaseSetsLength: number;
  allFinalCases: TestCase[];
  execution: BatchExecutionResponse | null;
  setSelectedCaseIds: StateSetter<string[]>;
  setApproval: StateSetter<ExecutionApproval | null>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setSideEffectsConfirmed: StateSetter<boolean>;
  setSelectedResult: StateSetter<ExecutionResult | null>;
  setMessage: StateSetter<string>;
}

export function useExecutionState({
  selectedProject,
  queue,
  workflowId,
  finalCaseSetId,
  finalCaseSetsLength,
  allFinalCases,
  execution,
  setSelectedCaseIds,
  setApproval,
  setBatchApproval,
  setExecution,
  setSideEffectsConfirmed,
  setSelectedResult,
  setMessage,
}: ExecutionStateContext) {
  useEffect(() => {
    setSelectedCaseIds(allFinalCases.map((item) => item.case_id));
    setApproval(null);
    setBatchApproval(null);
    setExecution(null);
    setSideEffectsConfirmed(false);
  }, [workflowId, finalCaseSetId, finalCaseSetsLength]);
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
}
