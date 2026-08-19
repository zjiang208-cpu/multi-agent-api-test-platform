import { assertionTarget, formatDetailValue, statusText } from "../app/platform";
import type { PageKey } from "../app/platform";
import type {
  BatchExecutionResponse,
  ExecutionResult,
  OperationContract,
  TestCase,
} from "../types/api";

interface ReportsPageProps {
  execution: BatchExecutionResponse | null;
  allFinalCases: TestCase[];
  operations: OperationContract[];
  selectedResult: ExecutionResult | null;
  onSelectResult: (result: ExecutionResult) => void;
  onClearResult: () => void;
  onNavigate: (page: PageKey) => void;
  onExportReportHtml: () => void;
}

export function ReportsPage({
  execution,
  allFinalCases,
  operations,
  selectedResult,
  onSelectResult,
  onClearResult,
  onNavigate,
  onExportReportHtml,
}: ReportsPageProps) {
  const setPage = onNavigate;
  const setSelectedResult = onSelectResult;
  const clearSelectedResult = onClearResult;
  const exportReportHtml = onExportReportHtml;

    if (!execution) return <div className="empty-card"><div className="empty-mark">报</div><h3>还没有执行报告</h3><p>确认执行范围并运行用例后，报告会在这里展示。</p><button className="button button-primary" onClick={() => setPage("execution")}>去执行中心</button></div>;
    const resultTitle = new Map(allFinalCases.map((item) => [item.case_id, item.title]));
    const resultsByOperation = [...execution.run.results.reduce((grouped, result) => {
      const operationId = result.api_operation_id ?? result.requirement_id;
      grouped.set(operationId, [...(grouped.get(operationId) ?? []), result]);
      return grouped;
    }, new Map<string, ExecutionResult[]>()).entries()];
    return <>
      <div className="page-heading">
        <div><span className="kicker">执行结果</span><h2>报告中心</h2><p>查看批量执行结果、HTTP 状态和每条断言的字段、期望值与实际值。</p></div>
        <div className="page-heading-actions">
          <span className={"status-badge " + (execution.report.status === "passed" ? "status-ready" : "status-danger")}>{statusText(execution.report.status)}</span>
          <button className="button button-secondary" onClick={exportReportHtml}>导出 HTML 报告</button>
        </div>
      </div>
      <div className="stats-grid">
        <div className="metric-card"><span>总用例</span><strong>{execution.report.total_cases}</strong><small>本次批量执行</small></div>
        <div className="metric-card"><span>PASS</span><strong className="metric-success">{execution.report.passed_cases}</strong><small>通过用例</small></div>
        <div className="metric-card"><span>FAIL</span><strong className="metric-danger">{execution.report.failed_cases}</strong><small>断言或业务结果不符合预期</small></div>
        <div className="metric-card"><span>断言失败</span><strong className="metric-danger">{execution.report.assertion_failures}</strong><small>共 {execution.report.assertion_total} 条断言</small></div>
      </div>
      <section className="card report-library-card">
        <div className="toolbar">
          <div><strong>执行明细</strong><span>Run ID：{execution.run.run_id}</span></div>
          <span className="source-text">{execution.run.target_environment ?? "local"}</span>
        </div>
        <div className="report-accordion-list">{resultsByOperation.map(([operationId, results]) => {
          const operation = operations.find((item) => item.operation_id === operationId);
          const passed = results.filter((item) => item.status === "passed").length;
          return <details className="report-accordion" key={operationId}>
            <summary><span><strong>{operation ? `${operation.method} ${operation.path}` : operationId}</strong><small>{results.length} 条结果 · {passed} 条通过</small></span><span className={`status-badge ${passed === results.length ? "status-ready" : "status-danger"}`}>{passed === results.length ? "全部通过" : "存在失败"}</span></summary>
            <div className="table-wrap"><table>
              <thead><tr><th>用例编号</th><th>用例名称</th><th>结果</th><th>HTTP 状态</th><th>断言</th><th>操作</th></tr></thead>
              <tbody>{results.map((result) => {
              const passedAssertions = result.assertion_results.filter((assertion) => assertion.passed).length;
              return <tr key={result.case_id}>
                <td><code>{result.case_id}</code></td>
                <td>{result.case_title ?? resultTitle.get(result.case_id) ?? "—"}</td>
                <td><span className={"status-badge status-" + (result.status === "passed" ? "ready" : result.status === "failed" ? "danger" : "warning")}>{statusText(result.status)}</span></td>
                <td>{result.status_code ?? "—"}</td>
                <td><span className="assertion-summary">{passedAssertions} / {result.assertion_results.length} 通过</span></td>
                <td><button className="button button-small button-ghost" onClick={() => setSelectedResult(result)}>查看详情</button></td>
              </tr>;
              })}</tbody>
            </table></div>
          </details>;
        })}</div>
      </section>
      {selectedResult && <div className="modal-backdrop" role="presentation" onClick={() => clearSelectedResult()}>
        <section className="result-modal" role="dialog" aria-modal="true" aria-labelledby="result-detail-title" onClick={(event) => event.stopPropagation()}>
          <button className="modal-close" aria-label="关闭断言详情" onClick={() => clearSelectedResult()}>×</button>
          <div className="result-modal-heading">
            <div>
              <span className="kicker">执行详情</span>
              <h2 id="result-detail-title">断言详情</h2>
              <p>{selectedResult.case_title ?? resultTitle.get(selectedResult.case_id) ?? selectedResult.case_id}</p>
            </div>
            <span className={"status-badge status-" + (selectedResult.status === "passed" ? "ready" : selectedResult.status === "failed" ? "danger" : "warning")}>{statusText(selectedResult.status)}</span>
          </div>
          <div className="result-meta-grid">
            <div><span>请求方法</span><strong>{selectedResult.method}</strong></div>
            <div><span>HTTP 状态</span><strong>{selectedResult.status_code ?? "—"}</strong></div>
            <div><span>耗时</span><strong>{selectedResult.duration_ms == null ? "—" : selectedResult.duration_ms.toFixed(1) + " ms"}</strong></div>
            <div className="result-meta-wide"><span>请求 URL</span><code>{selectedResult.url}</code></div>
          </div>
          {selectedResult.error_message && <div className="callout callout-danger"><strong>{selectedResult.error_category ?? "执行错误"}</strong><p>{selectedResult.error_message}</p></div>}
          <div className="assertion-detail-heading">
            <strong>断言列表</strong>
            <span>{selectedResult.assertion_results.filter((item) => item.passed).length} / {selectedResult.assertion_results.length} 通过</span>
          </div>
          {selectedResult.assertion_results.length ? <div className="assertion-detail-list">
            {selectedResult.assertion_results.map((assertion) => <article className={"assertion-detail-item " + (assertion.passed ? "is-passed" : "is-failed")} key={assertion.assertion_id}>
              <div className="assertion-detail-title">
                <div><span className={"assertion-state " + (assertion.passed ? "passed" : "failed")}>{assertion.passed ? "PASS" : "FAIL"}</span><code>{assertion.assertion_id}</code></div>
                <span>{assertion.type ?? "类型未记录"}</span>
              </div>
              <dl className="assertion-detail-grid">
                <div><dt>断言字段</dt><dd><code>{assertionTarget(assertion.type, assertion.path)}</code></dd></div>
                <div><dt>运算符</dt><dd><code>{assertion.operator || "默认相等"}</code></dd></div>
                <div><dt>期望值</dt><dd><pre>{formatDetailValue(assertion.expected)}</pre></dd></div>
                <div><dt>实际值</dt><dd><pre>{formatDetailValue(assertion.actual)}</pre></dd></div>
              </dl>
              <p className="assertion-message">{assertion.message}</p>
              {!!assertion.evidence_refs?.length && <p className="assertion-evidence">辅助证据：{assertion.evidence_refs.join("、")}</p>}
            </article>)}
          </div> : <div className="empty-inline"><p>该用例没有生成断言结果；请查看执行错误信息。</p></div>}
          <details className="response-detail">
            <summary>查看响应 Body</summary>
            <pre>{formatDetailValue(selectedResult.response_body)}</pre>
          </details>
          <div className="modal-actions"><button className="button button-primary" onClick={() => clearSelectedResult()}>关闭</button></div>
        </section>
      </div>}
    </>;
}

