import { methodClass, statusText } from "../app/platform";
import type { PageKey } from "../app/platform";
import type { ApiProcessingQueue, OperationContract, WorkflowRunSnapshot } from "../types/api";

type RequirementReviewPageProps = {
  startingWorkflow: boolean;
  message: string;
  queue: ApiProcessingQueue | null;
  workflow: WorkflowRunSnapshot | null;
  selectedOperation: OperationContract | null;
  operations: OperationContract[];
  busy: boolean;
  onApproveCurrentRequirement: () => void;
  onNavigate: (page: PageKey) => void;
};

export function RequirementReviewPage({
  startingWorkflow,
  message,
  queue,
  workflow,
  selectedOperation,
  operations,
  busy,
  onApproveCurrentRequirement,
  onNavigate,
}: RequirementReviewPageProps) {
  const setPage = onNavigate;
  const approveCurrentRequirement = onApproveCurrentRequirement;

    if (startingWorkflow) return <><div className="page-heading"><div><span className="kicker">需求确认</span><h2>正在进入需求分析</h2><p>顺序处理已经启动，需求提取完成后会自动展示需求、测试点和辅助证据。</p></div><span className="status-badge status-warning">处理中</span></div><section className="card workflow-start-card"><div className="workflow-loading-mark">分析</div><h3>正在分析当前接口需求</h3><p>{message}</p>{queue && <div className="workflow-start-facts"><div><span>处理队列</span><strong>{queue.items.length} 个接口</strong></div><div><span>当前接口</span><strong>第 {queue.current_index + 1} 个</strong></div><div><span>队列状态</span><strong>{statusText(queue.status)}</strong></div></div>}<div className="workflow-loading-line"><span className="loading-dot" /><span>页面已切换到下一节点，等待后台返回分析结果…</span></div></section></>;
    if (!workflow) return <div className="empty-card"><div className="empty-mark">需</div><h3>还没有需求分析结果</h3><p>请先解析需求文档，再选择待测接口开始分析。</p><button className="button button-primary" onClick={() => setPage("documents")}>去需求文档</button></div>;
    const requirement = workflow.requirement;
    return <><div className="page-heading"><div><span className="kicker">需求分析 · 人工确认</span><h2>需求确认</h2><p>当前接口从需求文档中提取需求和测试点；确认后系统会自动设计并检查用例。</p></div>{selectedOperation && <span className="operation-pill"><span className={methodClass(selectedOperation.method)}>{selectedOperation.method}</span><code>{selectedOperation.path}</code></span>}</div>{queue && <section className="card queue-card"><div className="card-heading"><div><span className="kicker">接口处理顺序</span><h3>严格顺序处理</h3></div><span className={`status-badge ${queue.status === "READY_FOR_EXECUTION" ? "status-ready" : "status-warning"}`}>{statusText(queue.status)}</span></div><div className="queue-items">{queue.items.map((item) => { const operation = operations.find((candidate) => candidate.operation_id === item.api_operation_id); return <div className={`queue-item ${item.status === "COMPLETED" ? "is-complete" : ["WAITING_REQUIREMENT_APPROVAL", "BLOCKED"].includes(item.status) ? "is-current" : ""}`} key={item.api_operation_id}><span className="queue-order">{item.order}</span><div><strong>{operation ? `${operation.method} ${operation.path}` : item.api_operation_id}</strong><small>{item.status === "WAITING_REQUIREMENT_APPROVAL" ? "等待需求确认" : item.status === "COMPLETED" ? "已完成：测试用例已确认" : statusText(item.status)}</small></div><span className="status-badge status-neutral">{statusText(item.current_stage)}</span></div>; })}</div></section>}{queue?.status === "BLOCKED" && <div className="callout callout-warning"><strong>用例需要人工处理</strong><p>{queue.items[queue.current_index]?.error_message ?? "存在无法自动解决的覆盖或执行问题，请查看最终用例详情。"}</p>{workflow.final_cases?.remaining_gaps.map((gap) => <p key={gap}>{gap}</p>)}</div>}<div className="requirement-grid"><section className="card"><div className="card-heading"><div><span className="kicker">需求快照</span><h3>{requirement?.requirement_id ?? workflow.workflow_id}</h3></div><span className={`status-badge ${workflow.status === "WAITING_REQUIREMENT_APPROVAL" ? "status-warning" : workflow.status === "FINAL_CASES_READY" ? "status-ready" : "status-neutral"}`}>{statusText(workflow.status)}</span></div>{requirement ? <><div className="facts-grid"><div><span>版本</span><strong>v{requirement.version}</strong></div><div><span>辅助证据</span><strong>{requirement.evidence_refs.length}</strong></div><div><span>置信度</span><strong>{requirement.confidence}</strong></div></div><div className="list-section"><h4>业务规则</h4>{requirement.business_rules.length ? <ul>{requirement.business_rules.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">暂无已提取业务规则</p>}</div><div className="list-section"><h4>预期行为</h4>{requirement.expected_behaviors.length ? <ul>{requirement.expected_behaviors.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">暂无已提取预期行为</p>}</div>{requirement.conflicts.length > 0 && <div className="callout callout-warning"><strong>文档冲突</strong>{requirement.conflicts.map((item) => <p key={item}>{item}</p>)}</div>}{requirement.unresolved_questions.length > 0 && <div className="callout callout-warning"><strong>待确认问题</strong>{requirement.unresolved_questions.map((item) => <p key={item}>{item}</p>)}</div>}{workflow.status === "WAITING_REQUIREMENT_APPROVAL" && <div className="gate-submit"><button className="button button-primary" onClick={() => void approveCurrentRequirement()} disabled={busy}>{busy ? "确认中…" : "确认需求并生成用例"}</button><span>确认后将锁定当前版本，并基于该版本生成测试用例。</span></div>}</> : <div className="empty-inline"><p>需求尚未生成。</p></div>}</section><section className="card"><div className="card-heading"><div><span className="kicker">测试点</span><h3>本接口需要验证什么</h3></div><span className="status-badge status-neutral">自动提取</span></div>{workflow.test_points?.points.length ? <div className="evidence-list">{workflow.test_points.points.map((point) => <div className="evidence-item" key={point.point_id}><div><span className="evidence-type">{point.category}</span><strong>{point.title}</strong></div><p>{point.expected_result}</p><small>{point.point_id}</small></div>)}</div> : <p className="muted">当前没有生成测试点。</p>}<div className="card-heading evidence-heading"><div><span className="kicker">证据来源</span><h3>辅助证据</h3></div></div>{workflow.evidence?.facts.length ? <div className="evidence-list auxiliary-evidence-list">{workflow.evidence.facts.map((fact) => <div className="evidence-item" key={fact.evidence_id}><div><span className="evidence-type">{fact.source_type}</span><strong>{fact.evidence_id}</strong></div><p>{fact.fact}</p><small>{fact.reference}</small></div>)}</div> : <p className="muted">当前没有可用的辅助证据。</p>}</section></div></>;
}
