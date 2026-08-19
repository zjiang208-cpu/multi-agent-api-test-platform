import { statusText } from "../app/platform";
import type { ApiProcessingQueue, FinalCaseSet } from "../types/api";
import type { PageKey } from "../app/platform";

interface WorkflowStatusPageProps {
  mode: "failure" | "skipped";
  queue: ApiProcessingQueue | null;
  message: string;
  finalCaseSets: FinalCaseSet[];
  busy: boolean;
  onRetry: () => void;
  onSkip: () => void;
  onNavigate: (page: PageKey) => void;
}

export function WorkflowStatusPage({
  mode,
  queue,
  message,
  finalCaseSets,
  busy,
  onRetry,
  onSkip,
  onNavigate,
}: WorkflowStatusPageProps) {
  if (mode === "skipped") {
    return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>接口已跳过</h2><p>当前接口的审查缺口已保留，未冻结为可执行用例；你可以继续选择其他接口。</p></div><span className="status-badge status-warning">已跳过</span></div><section className="card workflow-failure-card"><div className="workflow-loading-mark">↷</div><h3>当前接口未进入执行用例库</h3><p>跳过只会解除队列阻塞，不会改变 Reviewer 的审查结论。</p><div className="gate-actions"><button className="button button-primary" onClick={() => onNavigate("operations")}>继续选择接口</button><button className="button button-secondary" onClick={() => onNavigate("cases")} disabled={!finalCaseSets.length}>查看已生成用例</button></div></section></>;
  }

  if (!queue) return null;
  const item = queue.items[queue.current_index];
  const canReuseNlu = Boolean(
    item?.workflow_id
    && ["FAILED", "BLOCKED"].includes(item.status)
    && ["DESIGNER", "REVIEWER"].includes(item.current_stage),
  );
  return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>{canReuseNlu ? "用例设计失败" : "顺序分析失败"}</h2><p>{canReuseNlu ? "NLU 需求、证据和测试点已保存；重试将直接复用这些结果，不再重复调用需求分析。" : "后台分析任务已返回失败状态，当前队列和失败原因已保留。你可以重试当前接口，也可以跳过它继续处理后续接口。"}</p></div><span className="status-badge status-danger">失败</span></div><section className="card workflow-failure-card"><div className="workflow-loading-mark">!</div><h3>当前接口未进入下一节点</h3><p>{item?.error_message ?? message}</p><div className="workflow-start-facts"><div><span>处理队列</span><strong>{queue.items.length} 个接口</strong></div><div><span>当前接口</span><strong>第 {queue.current_index + 1} 个接口</strong></div><div><span>队列状态</span><strong>{statusText(queue.status)}</strong></div></div><div className="gate-actions"><button className="button button-primary" onClick={onRetry} disabled={busy}>{canReuseNlu ? "复用需求结果重试" : "重新分析当前接口"}</button>{queue.status === "BLOCKED" && <button className="button button-secondary" onClick={onSkip} disabled={busy}>跳过并继续</button>}<button className="button button-ghost" onClick={() => onNavigate("operations")} disabled={busy}>返回接口目录</button></div></section></>;
}
