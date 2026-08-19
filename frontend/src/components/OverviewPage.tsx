import type { ReactNode } from "react";
import type { PageKey } from "../app/platform";
import type { OperationContract, ParsedRequirementDocument, TestCase, TestProject, FinalCaseSet } from "../types/api";

interface OverviewPageProps {
  showCreateForm: boolean;
  createForm: ReactNode;
  emptyState: ReactNode;
  selectedProject: TestProject | null;
  operations: OperationContract[];
  parsedDocument: ParsedRequirementDocument | null;
  allFinalCases: TestCase[];
  finalCaseSets: FinalCaseSet[];
  selectedOperation: OperationContract | null;
  currentStep: number;
  overviewAction: { page: PageKey; label: string; description: string };
  workflowSteps: readonly string[];
  onNavigate: (page: PageKey) => void;
}

export function OverviewPage({
  showCreateForm,
  createForm,
  emptyState,
  selectedProject,
  operations,
  parsedDocument,
  allFinalCases,
  finalCaseSets,
  selectedOperation,
  currentStep,
  overviewAction,
  workflowSteps,
  onNavigate,
}: OverviewPageProps) {
  const setPage = onNavigate;

  if (showCreateForm) return createForm;
    if (!selectedProject) return emptyState;
    return <>
      <div className="page-heading overview-heading">
        <div>
          <span className="kicker">当前项目</span>
          <h2>{selectedProject.name}</h2>
          <p>从 Markdown 需求到批量执行与测试报告，当前任务按接口顺序推进。</p>
        </div>
        <button className="button button-primary" onClick={() => setPage(overviewAction.page)}>{overviewAction.label}</button>
      </div>
      <div className="stats-grid stats-grid-three">
        <div className="metric-card"><span>可测试接口</span><strong>{operations.length}</strong><small>从需求文档识别</small></div>
        <div className="metric-card"><span>当前需求文档</span><strong>{parsedDocument ? "已解析" : "—"}</strong><small>{parsedDocument?.filename ?? "尚未上传文档"}</small></div>
        <div className="metric-card"><span>项目用例</span><strong>{allFinalCases.length}</strong><small>{finalCaseSets.length ? `已完成 ${finalCaseSets.length} 个接口` : "尚未生成用例"}</small></div>
      </div>
      <section className="card workflow-card">
        <div className="card-heading">
          <div>
            <span className="kicker">当前任务</span>
            <h3>{selectedOperation ? `${selectedOperation.method} ${selectedOperation.path}` : parsedDocument?.filename ?? "等待上传需求文档"}</h3>
          </div>
          <span className={`status-badge ${currentStep >= 4 ? "status-ready" : currentStep > 0 ? "status-warning" : "status-neutral"}`}>{workflowSteps[currentStep]}</span>
        </div>
        <div className="next-step-panel">
          <div>
            <span>下一步</span>
            <strong>{overviewAction.label}</strong>
          </div>
          <p>{overviewAction.description}</p>
        </div>
      </section>
    </>;
}
