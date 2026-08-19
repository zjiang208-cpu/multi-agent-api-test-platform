import { methodClass } from "../app/platform";
import type { PageKey } from "../app/platform";
import type {
  OperationContract,
  ParsedRequirementDocument,
  TestProject,
} from "../types/api";
import type { ReactNode } from "react";

interface OperationsPageProps {
  showCreateForm: boolean;
  createForm: ReactNode;
  emptyState: ReactNode;
  selectedProject: TestProject | null;
  operations: OperationContract[];
  requirementDocuments: ParsedRequirementDocument[];
  parsedDocument: ParsedRequirementDocument | null;
  selectedOperation: OperationContract | null;
  selectedOperationIds: string[];
  completedOperationIds: Set<string>;
  activeFlowOperationId: string | null | undefined;
  busy: boolean;
  onNavigate: (page: PageKey) => void;
  onSelectOperation: (operation: OperationContract) => void;
  onRunWorkflow: () => void;
  onToggleOperation: (operationId: string) => void;
}

export function OperationsPage({
  showCreateForm,
  createForm,
  emptyState,
  selectedProject,
  operations,
  requirementDocuments,
  parsedDocument,
  selectedOperation,
  selectedOperationIds,
  completedOperationIds,
  activeFlowOperationId,
  busy,
  onNavigate,
  onSelectOperation,
  onRunWorkflow,
  onToggleOperation,
}: OperationsPageProps) {
  const setPage = onNavigate;
  const selectOperation = onSelectOperation;
  const runWorkflow = onRunWorkflow;
  const toggleOperation = onToggleOperation;

    if (!selectedProject) return showCreateForm ? createForm : emptyState;
    const documentLoaded = requirementDocuments.length > 0;
    const visibleOperations = operations;
    const documentStatus = !parsedDocument
      ? "尚未加载需求文档"
      : parsedDocument.project_id === selectedProject.project_id
        ? "已加载到当前项目"
        : "已解析，开始分析时会保存到当前项目";
    const documentStatusClass = documentLoaded && parsedDocument?.project_id === selectedProject.project_id ? "status-ready" : "status-warning";
    const selectedRequirementContent = parsedDocument && selectedOperation ? parsedDocument.content : "";
    const selectedContentLabel = parsedDocument ? `完整原文 · ${parsedDocument.line_count} 行` : "暂无原文";

    return <>
      <div className="page-heading">
        <div><span className="kicker">接口识别</span><h2>接口目录</h2><p>这里汇总本次上传的全部需求文档接口。每次选择 1 个接口，完成用例设计后再继续选择下一个。</p></div>
        <span className={`status-badge ${documentLoaded ? "status-ready" : "status-warning"}`}>{documentLoaded ? `来自 ${requirementDocuments.length} 份需求文档` : "请先解析需求文档"}</span>
      </div>
      <section className="card catalog-card">
        <div className="toolbar"><div><strong>{visibleOperations.length} 个接口</strong><span>{documentLoaded ? `已解析 ${requirementDocuments.length} 份需求文档` : "暂无需求文档输入"}</span></div><span className="status-badge status-neutral">每次最多选择 1 个</span></div>
        {visibleOperations.length ? <div className="table-wrap"><table><thead><tr><th className="check-col">选择</th><th>方法</th><th>接口路径</th><th>接口说明</th><th>需求来源</th><th>状态</th></tr></thead><tbody>{visibleOperations.map((operation) => {
          const completed = completedOperationIds.has(operation.operation_id);
          const inProgress = activeFlowOperationId === operation.operation_id;
          const locked = Boolean(activeFlowOperationId && activeFlowOperationId !== operation.operation_id);
          const selected = selectedOperationIds.includes(operation.operation_id);
          return <tr className={`${selected ? "row-selected" : ""} ${completed || locked ? "row-completed" : ""}`} key={operation.operation_id} onClick={() => { if (!activeFlowOperationId) selectOperation(operation); }}>
            <td className="check-col"><button type="button" className={`operation-selector ${selected ? "is-selected" : ""}`} aria-label={inProgress ? "当前接口流程进行中" : selected ? "取消选择接口" : "选择接口"} aria-pressed={selected} disabled={completed || Boolean(activeFlowOperationId)} onClick={(event) => { event.stopPropagation(); selectOperation(operation); }} /></td>
            <td><span className={methodClass(operation.method)}>{operation.method}</span></td>
            <td><code>{operation.path}</code></td>
            <td><strong>{operation.summary || "未提供说明"}</strong><small className="table-subtext">{operation.operation_id}</small></td>
            <td><span className="source-text">{operation.source_refs?.[0]?.section ?? operation.source_refs?.[0]?.reference ?? "接口契约"}</span>{operation.source_refs?.[0]?.start_line && <small className="table-subtext">Lines {operation.source_refs[0].start_line}–{operation.source_refs[0].end_line}</small>}</td>
            <td><span className={`status-badge ${completed ? "status-ready" : inProgress ? "status-warning" : "status-neutral"}`}>{completed ? "用例已生成" : inProgress ? "流程进行中" : locked ? "等待当前接口" : "可选择"}</span></td>
          </tr>;
        })}</tbody></table></div> : <div className="empty-table"><div className="empty-mark">API</div><h3>{documentLoaded ? "已上传的需求文档还没有识别出接口" : "还没有加载需求文档"}</h3><p>请先在“需求文档”上传或粘贴业务需求，接口目录不会自动加载项目历史接口。</p><button className="button button-primary" onClick={() => setPage("documents")}>去上传需求文档</button></div>}
        <div className="queue-launch"><div><strong>当前接口分析</strong><span>{selectedOperationIds.length ? "已选择 1 个接口" : "每次选择 1 个尚未生成用例的接口"} · {documentStatus}</span></div><button className="button button-primary" onClick={() => void runWorkflow()} disabled={busy || !documentLoaded || selectedOperationIds.length !== 1}>{busy ? "正在进入下一节点…" : "开始分析当前接口"}</button></div>
        {selectedOperationIds.length > 0 && <div className="queue-preview">{selectedOperationIds.map((operationId, index) => { const operation = visibleOperations.find((item) => item.operation_id === operationId); return <div key={operationId}><span>{index + 1}</span><strong>{operation ? `${operation.method} ${operation.path}` : operationId}</strong><button className="button button-small button-ghost" onClick={() => toggleOperation(operationId)} disabled={busy || Boolean(activeFlowOperationId)}>移除</button></div>; })}</div>}
      </section>
      {selectedOperation && <section className="card requirement-detail-card">
        <div className="card-heading"><div><span className="kicker">需求文档</span><h3>需求详情 · {selectedOperation.method} {selectedOperation.path}</h3></div><span className={`status-badge ${documentStatusClass}`}>{documentStatus}</span></div>
        {parsedDocument ? <><div className="parsed-meta"><div><span>文件名</span><strong title={parsedDocument.filename}>{parsedDocument.filename}</strong></div><div><span>接口</span><strong>{selectedOperation.operation_id}</strong></div><div><span>字符数</span><strong>{parsedDocument.char_count.toLocaleString()}</strong></div><div><span>接口原文</span><strong>{selectedContentLabel}</strong></div><div><span>文档编号</span><code title={parsedDocument.document_id}>{parsedDocument.document_id}</code></div></div><div className="requirement-source-content"><div className="source-content-heading"><strong>当前接口对应的需求原文</strong><span>{selectedContentLabel}</span></div><pre>{selectedRequirementContent || "（当前接口没有可展示的需求原文）"}</pre></div></> : <div className="empty-inline requirement-detail-empty"><p>当前接口尚未关联需求文档，请先完成需求文档解析。</p></div>}
      </section>}
    </>;
}

