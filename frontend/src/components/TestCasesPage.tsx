import type { PageKey } from "../app/platform";
import type {
  BatchExecutionApproval,
  FinalCaseSet,
  OperationContract,
  TestCase,
} from "../types/api";

type TestCasesPageProps = {
  finalCaseSets: FinalCaseSet[];
  allFinalCases: TestCase[];
  operations: OperationContract[];
  selectedCaseIds: string[];
  batchApproval: BatchExecutionApproval | null;
  onNavigate: (page: PageKey) => void;
  onToggleAllCases: () => void;
  onToggleCase: (caseId: string) => void;
  onToggleCaseSet: (caseSet: FinalCaseSet) => void;
};

export function TestCasesPage({
  finalCaseSets,
  allFinalCases,
  operations,
  selectedCaseIds,
  batchApproval,
  onNavigate,
  onToggleAllCases,
  onToggleCase,
  onToggleCaseSet,
}: TestCasesPageProps) {
  const setPage = onNavigate;
  const toggleAllCases = onToggleAllCases;
  const toggleCase = onToggleCase;
  const toggleCaseSet = onToggleCaseSet;

    if (!finalCaseSets.length) return <div className="empty-card"><div className="empty-mark">例</div><h3>还没有测试用例</h3><p>请先选择一个接口，完成需求确认和用例设计。</p><button className="button button-primary" onClick={() => setPage("operations")}>选择接口</button></div>;
    const caseCount = allFinalCases.length;
    const reviewerAdded = finalCaseSets.reduce((sum, item) => sum + item.added_case_ids.length, 0);
    const unresolved = finalCaseSets.reduce((sum, item) => sum + item.unresolved_questions.length + item.remaining_gaps.length, 0);
    const allCasesSelected = caseCount > 0 && allFinalCases.every((item) => selectedCaseIds.includes(item.case_id));
    const someCasesSelected = allFinalCases.some((item) => selectedCaseIds.includes(item.case_id));
    const caseSelectionLocked = Boolean(batchApproval);
    return <>
      <div className="page-heading">
        <div><span className="kicker">测试设计结果</span><h2>测试用例</h2><p>每个接口独立生成用例，并持续累计到当前项目；展开接口即可查看和选择用例。</p></div>
        <span className="status-badge status-ready">已完成 {finalCaseSets.length} 个接口</span>
      </div>
      <div className="stats-grid"><div className="metric-card"><span>测试用例</span><strong>{caseCount}</strong><small>项目累计用例</small></div><div className="metric-card"><span>自动补充</span><strong>{reviewerAdded}</strong><small>发现覆盖缺口时补充</small></div><div className="metric-card"><span>副作用用例</span><strong>{allFinalCases.filter((item) => item.side_effect).length}</strong><small>执行前需要确认</small></div><div className="metric-card"><span>待解决问题</span><strong>{unresolved}</strong><small>{unresolved ? "进入执行前需人工确认" : "已完成冻结"}</small></div></div>
      <section className="card case-library-card">
        <div className="toolbar"><div><strong>批次用例选择</strong><span>{selectedCaseIds.length} / {caseCount} 条已选择</span></div><div className="toolbar-actions"><label className="case-select-all"><input type="checkbox" checked={allCasesSelected} ref={(node) => { if (node) node.indeterminate = someCasesSelected && !allCasesSelected; }} onChange={toggleAllCases} disabled={caseSelectionLocked} /><span>全部接口用例</span></label><button className="button button-small button-secondary" onClick={() => setPage("operations")}>继续选择接口</button><button className="button button-small button-primary" onClick={() => setPage("execution")} disabled={!selectedCaseIds.length}>进入统一执行确认</button></div></div>
        <div className="case-accordion-list">{finalCaseSets.map((set) => {
          const operation = operations.find((item) => item.operation_id === set.api_operation_id);
          const operationLabel = operation ? `${operation.method} ${operation.path}` : set.api_operation_id ?? set.requirement_id;
          const selectedCount = set.cases.filter((item) => selectedCaseIds.includes(item.case_id)).length;
          const allSetCasesSelected = set.cases.length > 0 && selectedCount === set.cases.length;
          const someSetCasesSelected = selectedCount > 0 && !allSetCasesSelected;
          return <details className="case-accordion" key={set.final_case_set_id}>
            <summary><input className="case-set-checkbox" type="checkbox" aria-label={`选择 ${operationLabel} 的全部用例`} checked={allSetCasesSelected} ref={(node) => { if (node) node.indeterminate = someSetCasesSelected; }} onClick={(event) => event.stopPropagation()} onChange={() => toggleCaseSet(set)} disabled={caseSelectionLocked} /><span className="case-summary-copy"><strong>{operationLabel}</strong><small>{set.cases.length} 条用例 · 已选择 {selectedCount} 条</small></span><span className="status-badge status-ready">用例已生成</span></summary>
            <div className="table-wrap"><table><thead><tr><th className="check-col">选择</th><th>用例</th><th>分类</th><th>预期行为</th><th>副作用</th></tr></thead><tbody>{set.cases.map((testCase) => <tr key={testCase.case_id}><td className="check-col"><input type="checkbox" aria-label={`选择用例 ${testCase.title}`} checked={selectedCaseIds.includes(testCase.case_id)} onChange={() => toggleCase(testCase.case_id)} disabled={caseSelectionLocked} /></td><td><strong>{testCase.title}</strong><small className="table-subtext">{testCase.case_id}</small></td><td>{testCase.category}</td><td className="expected-cell">{testCase.expected_behavior}</td><td>{testCase.side_effect ? <span className="status-badge status-warning">需确认</span> : <span className="status-badge status-neutral">无</span>}</td></tr>)}</tbody></table></div>
          </details>;
        })}</div>
      </section>
    </>;
}
