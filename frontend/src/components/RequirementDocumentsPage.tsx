import { formatDate, operationsForDocument } from "../app/platform";
import type { OperationContract, ParsedRequirementDocument } from "../types/api";

type RequirementDocumentsPageProps = {
  hasProject: boolean;
  activeFlowOperationId: string | null;
  documentText: string;
  documentError: string;
  busy: boolean;
  parsedDocument: ParsedRequirementDocument | null;
  requirementDocuments: ParsedRequirementDocument[];
  operations: OperationContract[];
  onFileDocument: (file: File) => void;
  onDocumentTextChange: (value: string) => void;
  onParseText: () => void;
  onSelectDocument: (document: ParsedRequirementDocument) => void;
};

export function RequirementDocumentsPage({
  hasProject,
  activeFlowOperationId,
  documentText,
  documentError,
  busy,
  parsedDocument,
  requirementDocuments,
  operations,
  onFileDocument,
  onDocumentTextChange,
  onParseText,
  onSelectDocument,
}: RequirementDocumentsPageProps) {
  return <>
    <div className="page-heading">
      <div><span className="kicker">开始测试</span><h2>需求文档解析</h2><p>上传面向接口的需求文档，平台会提取业务规则、接口行为和异常场景。源码与数据库仅作为可选辅助证据。</p></div>
      <span className="status-badge status-ready">独立入口</span>
    </div>
    <div className="document-layout">
      <section className="card document-input-card">
        <div className="card-heading"><div><span className="kicker">输入文档</span><h3>上传文件或粘贴内容</h3></div><span className="help-text">单文件最大 10 MB</span></div>
        <label className="document-drop"><input type="file" accept=".md,.markdown" disabled={Boolean(activeFlowOperationId)} onChange={(event) => { const file = event.target.files?.[0]; if (file) onFileDocument(file); }} /><span className="drop-title">选择需求文档文件</span><span className="drop-copy">Markdown</span></label>
        <div className="document-divider"><span>或直接粘贴</span></div>
        <textarea className="document-textarea" value={documentText} disabled={Boolean(activeFlowOperationId)} onChange={(event) => onDocumentTextChange(event.target.value)} placeholder="粘贴需求背景、业务规则、接口行为、异常场景等内容…" maxLength={500000} />
        <div className="document-footer"><span>{documentText.length.toLocaleString()} / 500,000 字符</span><button className="button button-primary" onClick={onParseText} disabled={busy || Boolean(activeFlowOperationId) || !documentText.trim()}>{busy ? "解析中…" : "解析需求文档"}</button></div>
        {documentError && <div className="callout callout-danger">{documentError}</div>}
      </section>
      <section className="document-side">
        <section className="card"><div className="card-heading"><div><span className="kicker">解析能力</span><h3>支持的文档格式</h3></div></div><div className="format-list"><span>Markdown</span></div><p className="card-copy">解析服务会提取 Markdown 原文、章节标题、行号和文档摘要。解析完成后，平台会自动识别接口并映射到接口目录。</p></section>
      </section>
    </div>
    {hasProject && requirementDocuments.length > 0 && <section className="card document-library">
      <div className="card-heading">
        <div><span className="kicker">项目文档</span><h3>已上传需求文档</h3></div>
        <span className="status-badge status-neutral">共 {requirementDocuments.length} 份</span>
      </div>
      <div className="document-library-list">
        {requirementDocuments.map((document) => {
          const active = document.document_id === parsedDocument?.document_id;
          const operationCount = operationsForDocument(operations, document.document_id).length;
          return <button
            type="button"
            className={`document-library-item ${active ? "is-active" : ""}`}
            key={document.document_id}
            onClick={() => onSelectDocument(document)}
          >
            <span className="document-library-main">
              <strong title={document.filename}>{document.filename}</strong>
              <small>{document.format.toUpperCase()} · {document.line_count.toLocaleString()} 行 · {operationCount} 个接口</small>
            </span>
            <span className="document-library-side">
              <small>{formatDate(document.updated_at ?? document.created_at)}</small>
              <span className={`status-badge ${active ? "status-ready" : "status-neutral"}`}>{active ? "当前文档" : "选择"}</span>
            </span>
          </button>;
        })}
      </div>
    </section>}
  </>;
}
