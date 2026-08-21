import type { Dispatch, SetStateAction } from "react";
import type {
  BatchExecutionApproval,
  BatchExecutionResponse,
  ExecutionResult,
  FinalCaseSet,
  TestCase,
} from "../types/api";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface CaseSelectionActionContext {
  allFinalCases: TestCase[];
  setSelectedCaseIds: StateSetter<string[]>;
  setBatchApproval: StateSetter<BatchExecutionApproval | null>;
  setExecution: StateSetter<BatchExecutionResponse | null>;
  setSelectedResult: StateSetter<ExecutionResult | null>;
  setSideEffectsConfirmed: StateSetter<boolean>;
}


export function createCaseSelectionActions(context: CaseSelectionActionContext) {
  const {
    allFinalCases,
    setSelectedCaseIds,
    setBatchApproval,
    setExecution,
    setSelectedResult,
    setSideEffectsConfirmed,
  } = context;

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

  return {
    toggleCase,
    toggleCaseSet,
    toggleAllCases,
  };
}
