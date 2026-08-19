import type { BatchExecutionApproval, FinalCaseSet, TestCase } from "../types/api";
import type { PageKey } from "../app/platform";

interface ExecutionPageProps {
  allFinalCases: TestCase[];
  finalCaseSets: FinalCaseSet[];
  batchApproval: BatchExecutionApproval | null;
  selectedCaseIds: string[];
  targetEnvironment: string;
  baseUrl: string;
  sideEffectCaseIds: string[];
  sideEffectsConfirmed: boolean;
  busy: boolean;
  onNavigate: (page: PageKey) => void;
  onTargetEnvironmentChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onSideEffectsConfirmedChange: (value: boolean) => void;
  onApproveForExecution: () => void;
  onExecuteApproved: (autoRegression?: boolean) => void;
}

export function ExecutionPage({
  allFinalCases,
  finalCaseSets,
  batchApproval,
  selectedCaseIds,
  targetEnvironment,
  baseUrl,
  sideEffectCaseIds,
  sideEffectsConfirmed,
  busy,
  onNavigate,
  onTargetEnvironmentChange,
  onBaseUrlChange,
  onSideEffectsConfirmedChange,
  onApproveForExecution,
  onExecuteApproved,
}: ExecutionPageProps) {
  const setPage = onNavigate;
  const setTargetEnvironment = onTargetEnvironmentChange;
  const setBaseUrl = onBaseUrlChange;
  const setSideEffectsConfirmed = onSideEffectsConfirmedChange;
  const approveForExecution = onApproveForExecution;
  const executeApproved = onExecuteApproved;

    if (!allFinalCases.length) return <div className="empty-card empty-warning"><div className="empty-mark">!</div><h3>还没有可执行用例</h3><p>请先选择一个接口并完成需求确认与用例设计。</p><button className="button button-secondary" onClick={() => setPage("operations")}>选择接口</button></div>;
    return <><div className="page-heading"><div><span className="kicker">执行前确认</span><h2>统一执行确认</h2><p>确认目标环境、服务地址、用例数量和可能产生副作用的用例，然后批量执行。</p></div><span className="status-badge status-warning">执行前人工确认</span></div><section className="card gate-card"><div className="gate-title"><div><span className="kicker">批次执行范围</span><h3>{finalCaseSets.length} 个接口 · {allFinalCases.length} 条测试用例</h3></div>{batchApproval && <span className="status-badge status-ready">已批准</span>}</div>{batchApproval ? <><div className="approval-banner"><strong>已批准执行 {batchApproval.selected_case_count} 条用例</strong><span>{batchApproval.target_environment}</span></div><div className="approval-details"><div><span>接口数量</span><strong>{finalCaseSets.length}</strong></div><div><span>副作用用例</span><strong>{batchApproval.side_effect_case_ids.length || "无"}</strong></div><div><span>自动回归</span><strong>{batchApproval.auto_regression_allowed ? "允许" : "不允许"}</strong></div></div><div className="gate-actions"><button className="button button-primary" onClick={() => void executeApproved(false)} disabled={busy}>{busy ? "执行中…" : "批量执行"}</button>{batchApproval.auto_regression_allowed && <button className="button button-secondary" onClick={() => void executeApproved(true)} disabled={busy}>自动回归未变化用例</button>}</div></> : <><div className="form-grid gate-form"><label>目标环境<input value={targetEnvironment} onChange={(event) => setTargetEnvironment(event.target.value)} placeholder="local / test / staging" /></label><label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label><label>确认用例数量<input value={selectedCaseIds.length} readOnly /></label></div><div className="selected-case-box"><div><strong>本次批量执行范围</strong><span>已选择 {selectedCaseIds.length} / {allFinalCases.length} 条用例</span></div><button className="button button-small button-ghost" onClick={() => setPage("cases")}>调整用例</button></div>{sideEffectCaseIds.length > 0 && <label className="danger-confirm"><input type="checkbox" checked={sideEffectsConfirmed} onChange={(event) => setSideEffectsConfirmed(event.target.checked)} /><span><strong>我确认以下用例可能产生副作用</strong><small>{sideEffectCaseIds.join("、")}</small></span></label>}<div className="gate-submit"><button className="button button-primary" onClick={() => void approveForExecution()} disabled={busy || !selectedCaseIds.length || !baseUrl.trim() || (sideEffectCaseIds.length > 0 && !sideEffectsConfirmed)}>确认并生成批量执行许可</button><span>批准后仍不会自动执行，需再次点击“批量执行”。</span></div></>}</section></>;
}

