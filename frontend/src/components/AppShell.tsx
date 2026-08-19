import type { ReactNode } from "react";
import type { TestProject } from "../types/api";
import {
  navGroups,
  workflowSteps,
  type NavItem,
  type PageKey,
} from "../app/platform";
import { BrandMark, NavIcon } from "./NavigationIcons";

type AppShellProps = {
  projects: TestProject[];
  selectedProject: TestProject | null;
  page: PageKey;
  activeNav: NavItem;
  currentStep: number;
  message: string;
  busy: boolean;
  onSelectProject: (project: TestProject) => void;
  onCreateProject: () => void;
  onNavigate: (page: PageKey) => void;
  children: ReactNode;
};

export function AppShell({
  projects,
  selectedProject,
  page,
  activeNav,
  currentStep,
  message,
  busy,
  onSelectProject,
  onCreateProject,
  onNavigate,
  children,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><BrandMark /></div>
          <div><strong>接口测试工作台</strong><span>Multi-Agent workflow</span></div>
        </div>
        <div className="sidebar-section project-section">
          <span className="sidebar-label">当前项目</span>
          {projects.length
            ? <select aria-label="当前项目" value={selectedProject?.project_id ?? ""} onChange={(event) => {
              const project = projects.find((item) => item.project_id === event.target.value);
              if (project) onSelectProject(project);
            }}><option value="" disabled>选择项目</option>{projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.name}</option>)}</select>
            : <button className="sidebar-create" onClick={onCreateProject}>+ 创建测试项目</button>}
        </div>
        <nav className="main-nav" aria-label="主导航">
          {navGroups.map((group) => <div className="nav-group" key={group.label}>
            <span className="nav-group-label">{group.label}</span>
            {group.items.map((item) => <button key={item.key} className={`nav-item ${page === item.key ? "active" : ""}`} aria-current={page === item.key ? "page" : undefined} onClick={() => onNavigate(item.key)}><NavIcon name={item.icon} /><span>{item.label}</span></button>)}
          </div>)}
        </nav>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div><span className="breadcrumb">{selectedProject?.name ?? "接口测试工作台"} / {activeNav.label}</span><h1>{activeNav.label}</h1></div>
        </header>
        <main className="content" id="main-content">
          <section className="workflow-progress" aria-label="测试任务进度">
            <div className="progress-caption">
              <div><span className="kicker">测试任务进度</span><strong>{workflowSteps[currentStep]}</strong></div>
              <span>第 {Math.min(currentStep + 1, workflowSteps.length)} / {workflowSteps.length} 阶段</span>
            </div>
            <ol className="stepper">{workflowSteps.map((step, index) => <li className={`step ${index < currentStep ? "complete" : ""} ${index === currentStep ? "current" : ""}`} aria-current={index === currentStep ? "step" : undefined} key={step}><span className="step-number">{index < currentStep ? "✓" : index + 1}</span><span>{step}</span></li>)}</ol>
          </section>
          <div className={`global-notice ${busy ? "is-busy" : ""}`} role="status" aria-live="polite" aria-atomic="true"><span className="notice-indicator" />{message}</div>
          {children}
        </main>
      </div>
    </div>
  );
}
