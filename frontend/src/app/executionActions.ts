import { api } from "../api/client";
import { downloadReportHtml } from "./report";
import type { Dispatch, SetStateAction } from "react";
import type { PageKey } from "../app/platform";
import type {
  BatchExecutionApproval,
  BatchExecutionResponse,
  TestCase,
  TestProject,
} from "../types/api";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface ExecutionActionContext {
  selectedProject: TestProject | null;
  selectedCaseIds: string[];
  targetEnvironment: string;
  baseUrl: string;
  sideEffectCaseIds: string[];
  sideEffectsConfirmed: boolean;
  batchApproval: BatchExecutionApproval | null;
  execution: BatchExecutionResponse | null;
  allFinalCases: TestCase[];
  setBusy: StateSetter<boolean>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setPage: StateSetter<PageKey>;
  setMessage: StateSetter<string>;
}

export function createExecutionActions(context: ExecutionActionContext) {
  const {
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
  } = context;

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

  return {
    approveForExecution,
    executeApproved,
    exportReportHtml,
  };
}

