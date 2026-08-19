import type { BatchExecutionResponse, TestCase, TestProject } from "../types/api";
import {
  assertionTarget,
  escapeHtml,
  formatDate,
  requestPath,
  statusText,
} from "./platform";

export function downloadReportHtml(
  execution: BatchExecutionResponse,
  selectedProject: TestProject | null,
  allFinalCases: TestCase[],
): void {
  const caseTitles = new Map(allFinalCases.map((item) => [item.case_id, item.title]));
  const resultSections = execution.run.results.map((result) => {
    const passedAssertions = result.assertion_results.filter((assertion) => assertion.passed).length;
    const assertionRows = result.assertion_results.length
      ? result.assertion_results.map((assertion) => `<tr>
            <td><span class="state ${assertion.passed ? "pass" : "fail"}">${assertion.passed ? "PASS" : "FAIL"}</span></td>
            <td><code>${escapeHtml(assertionTarget(assertion.type, assertion.path))}</code></td>
            <td><code>${escapeHtml(assertion.operator || "默认相等")}</code></td>
            <td><pre>${escapeHtml(assertion.expected)}</pre></td>
            <td><pre>${escapeHtml(assertion.actual)}</pre></td>
            <td>${escapeHtml(assertion.message)}</td>
          </tr>`).join("")
      : `<tr><td colspan="6" class="empty">该用例没有断言结果</td></tr>`;
    return `<section class="case-card">
        <div class="case-heading">
          <div><h2>${escapeHtml(result.case_title ?? caseTitles.get(result.case_id) ?? result.case_id)}</h2><code>${escapeHtml(result.case_id)}</code></div>
          <span class="state ${result.status === "passed" ? "pass" : "fail"}">${escapeHtml(statusText(result.status))}</span>
        </div>
        <div class="case-meta">
          <div><span>请求</span><strong>${escapeHtml(result.method)} ${escapeHtml(requestPath(result.url))}</strong></div>
          <div><span>HTTP 状态</span><strong>${escapeHtml(result.status_code ?? "—")}</strong></div>
          <div><span>耗时</span><strong>${result.duration_ms == null ? "—" : `${result.duration_ms.toFixed(1)} ms`}</strong></div>
          <div><span>断言</span><strong>${passedAssertions} / ${result.assertion_results.length} 通过</strong></div>
        </div>
        ${result.error_message ? `<div class="error"><strong>${escapeHtml(result.error_category ?? "执行错误")}</strong><p>${escapeHtml(result.error_message)}</p></div>` : ""}
        <table><thead><tr><th>结果</th><th>断言字段</th><th>运算符</th><th>期望值</th><th>实际值</th><th>说明</th></tr></thead><tbody>${assertionRows}</tbody></table>
        <details><summary>响应 Body</summary><pre>${escapeHtml(result.response_body)}</pre></details>
      </section>`;
  }).join("");
  const title = `${selectedProject?.name ?? "API 自动化测试"} · 测试报告`;
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
*{box-sizing:border-box}body{margin:0;color:#142b49;background:#f3f6fa;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}.page{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}.hero,.case-card{background:#fff;border:1px solid #dce4ef;border-radius:14px}.hero{padding:28px}.hero h1{margin:5px 0 6px;font-size:28px}.muted,.hero p{color:#718198}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:22px}.metric{padding:16px;border:1px solid #e2e8f0;border-radius:10px}.metric span{display:block;color:#8190a4;font-size:12px}.metric strong{display:block;margin-top:6px;font-size:25px}.pass-text{color:#14805e}.fail-text{color:#cf4141}.case-card{padding:22px;margin-top:16px;overflow:hidden}.case-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.case-heading h2{margin:0 0 5px;font-size:18px}.case-heading code,.case-meta code{color:#64748b}.state{display:inline-block;padding:4px 9px;border-radius:999px;font-weight:800;font-size:12px}.state.pass{color:#14805e;background:#e9f8f2}.state.fail{color:#c83d3d;background:#fff0f0}.case-meta{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:10px;margin:18px 0}.case-meta div{padding:11px;background:#f8fafc;border:1px solid #e7ecf2;border-radius:8px}.case-meta span,.case-meta strong{display:block}.case-meta span{color:#8190a4;font-size:11px}.case-meta strong{margin-top:4px;overflow-wrap:anywhere}.error{margin:14px 0;padding:12px;color:#a93434;background:#fff5f5;border-left:3px solid #d94b4b}.error p{margin:4px 0 0}table{width:100%;border-collapse:collapse;margin-top:12px;font-size:12px}th,td{padding:10px;text-align:left;vertical-align:top;border:1px solid #e2e8f0}th{color:#66758a;background:#f7f9fc}td pre,details pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12px/1.55 Consolas,"Microsoft YaHei",monospace}.empty{text-align:center;color:#8190a4}details{margin-top:14px;padding-top:12px;border-top:1px solid #e2e8f0}summary{cursor:pointer;font-weight:700}details>pre{max-height:360px;overflow:auto;margin-top:10px;padding:12px;background:#f8fafc;border-radius:8px}@media(max-width:760px){.summary,.case-meta{grid-template-columns:1fr 1fr}.page{width:min(100% - 20px,1180px)}.hero,.case-card{padding:16px}table{display:block;overflow-x:auto}}@media print{body{background:#fff}.page{width:100%;margin:0}.hero,.case-card{break-inside:avoid;border-color:#bbb}.case-card{margin-top:12px}details>pre{max-height:none}}
</style></head><body><main class="page">
<section class="hero"><span class="muted">基于 Multi-Agent 的接口自动化测试平台</span><h1>${escapeHtml(title)}</h1><p>生成时间：${escapeHtml(formatDate(execution.report.generated_at))}　·　Run ID：${escapeHtml(execution.run.run_id)}　·　环境：${escapeHtml(execution.run.target_environment ?? "local")}</p>
<div class="summary"><div class="metric"><span>总用例</span><strong>${execution.report.total_cases}</strong></div><div class="metric"><span>PASS</span><strong class="pass-text">${execution.report.passed_cases}</strong></div><div class="metric"><span>FAIL</span><strong class="fail-text">${execution.report.failed_cases}</strong></div><div class="metric"><span>断言失败</span><strong class="fail-text">${execution.report.assertion_failures} / ${execution.report.assertion_total}</strong></div></div></section>
${resultSections}</main></body></html>`;
  const blobUrl = window.URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const link = document.createElement("a");
  const projectName = (selectedProject?.name ?? "api-test").replace(/[\\/:*?"<>|]+/g, "-").trim() || "api-test";
  const timestamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
  link.href = blobUrl;
  link.download = `${projectName}-测试报告-${timestamp}.html`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(blobUrl);
}
