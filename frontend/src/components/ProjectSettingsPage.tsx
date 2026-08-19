import type { ProjectEditor } from "../app/platform";
import { formatDate } from "../app/platform";
import type { TestProject } from "../types/api";

type ProjectSettingsPageProps = {
  selectedProject: TestProject | null;
  projectEditor: ProjectEditor | null;
  showCreateForm: boolean;
  busy: boolean;
  newProjectName: string;
  newProjectDescription: string;
  newBaseUrl: string;
  newOpenapiSource: string;
  newWorkspace: string;
  newDbEnabled: boolean;
  newDbDialect: string;
  newDbRef: string;
  newDbSchema: string;
  newDbTables: string;
  onNewProjectNameChange: (value: string) => void;
  onNewProjectDescriptionChange: (value: string) => void;
  onNewBaseUrlChange: (value: string) => void;
  onNewOpenapiSourceChange: (value: string) => void;
  onNewWorkspaceChange: (value: string) => void;
  onNewDbEnabledChange: (value: boolean) => void;
  onNewDbDialectChange: (value: string) => void;
  onNewDbRefChange: (value: string) => void;
  onNewDbSchemaChange: (value: string) => void;
  onNewDbTablesChange: (value: string) => void;
  onCreateProject: () => void;
  onCancelCreate: () => void;
  onStartCreate: () => void;
  onDeleteSelectedProject: () => void;
  onSaveProjectSettings: () => void;
  onUpdateEditor: (patch: Partial<ProjectEditor>) => void;
  onCreateEmptyProject: () => void;
};

export function ProjectSettingsPage({
  selectedProject,
  projectEditor,
  showCreateForm,
  busy,
  newProjectName,
  newProjectDescription,
  newBaseUrl,
  newOpenapiSource,
  newWorkspace,
  newDbEnabled,
  newDbDialect,
  newDbRef,
  newDbSchema,
  newDbTables,
  onNewProjectNameChange,
  onNewProjectDescriptionChange,
  onNewBaseUrlChange,
  onNewOpenapiSourceChange,
  onNewWorkspaceChange,
  onNewDbEnabledChange,
  onNewDbDialectChange,
  onNewDbRefChange,
  onNewDbSchemaChange,
  onNewDbTablesChange,
  onCreateProject,
  onCancelCreate,
  onStartCreate,
  onDeleteSelectedProject,
  onSaveProjectSettings,
  onUpdateEditor,
  onCreateEmptyProject,
}: ProjectSettingsPageProps) {
  if (showCreateForm) {
    return <section className="card form-card">
      <div className="card-heading">
        <div><span className="kicker">项目配置</span><h3>创建测试项目</h3><p className="form-subtitle">配置被测服务和可选证据来源，需求文档仍在独立页面上传。</p></div>
        <button className="button button-ghost" onClick={onCancelCreate}>取消</button>
      </div>
      <div className="form-grid">
        <label>项目名称<input value={newProjectName} onChange={(event) => onNewProjectNameChange(event.target.value)} placeholder="例如：订单服务 API 测试" /></label>
        <label>被测服务 Base URL<input value={newBaseUrl} onChange={(event) => onNewBaseUrlChange(event.target.value)} placeholder="http://127.0.0.1:8081" /></label>
        <label className="field-wide">项目说明<textarea value={newProjectDescription} onChange={(event) => onNewProjectDescriptionChange(event.target.value)} rows={2} /></label>
        <label>接口描述来源（可选）<textarea value={newOpenapiSource} onChange={(event) => onNewOpenapiSourceChange(event.target.value)} placeholder="每行一个本地文件或 URL" rows={3} /></label>
        <label>源码工作区路径（可选）<input value={newWorkspace} onChange={(event) => onNewWorkspaceChange(event.target.value)} placeholder="例如：D:\\workspace\\your-service" /></label>
        <label>数据库连接引用<input value={newDbRef} onChange={(event) => onNewDbRefChange(event.target.value)} placeholder="例如：env:TEST_DB_DSN" disabled={!newDbEnabled} /></label>
        <label>数据库类型<select value={newDbDialect} onChange={(event) => onNewDbDialectChange(event.target.value)} disabled={!newDbEnabled}><option value="mysql">MySQL</option><option value="postgresql">PostgreSQL</option><option value="sqlite">SQLite</option></select></label>
        <label>数据库 Schema（可选）<input value={newDbSchema} onChange={(event) => onNewDbSchemaChange(event.target.value)} placeholder="例如：public" disabled={!newDbEnabled} /></label>
        <label>允许读取的表<textarea value={newDbTables} onChange={(event) => onNewDbTablesChange(event.target.value)} placeholder="每行一个表名，例如：example_table" rows={3} disabled={!newDbEnabled} /></label>
      </div>
      <label className="switch-row"><input type="checkbox" checked={newDbEnabled} onChange={(event) => onNewDbEnabledChange(event.target.checked)} /><span><strong>启用数据库真实夹具</strong><small>模型选择夹具令牌，真实 ID 由后端只读查询并在本地替换，不发送给模型。</small></span></label>
      <div className="form-note">连接信息必须使用环境变量引用（如 env:TEST_DB_DSN）；平台只读取白名单表的标识字段，不展示数据库连接串。</div>
      <div className="form-actions"><button className="button button-primary" onClick={onCreateProject} disabled={busy || !newProjectName.trim() || !newBaseUrl.trim()}>保存项目</button></div>
    </section>;
  }

  if (!selectedProject || !projectEditor) {
    return <section className="empty-card empty-card-large"><div className="empty-mark">项目</div><h3>还没有测试项目</h3><p>需求文档可以先独立解析；如需读取源码、数据库和接口契约，再创建一个测试项目作为辅助证据上下文。</p><button className="button button-primary" onClick={onCreateEmptyProject}>创建测试项目</button></section>;
  }

  return <>
    <div className="page-heading">
      <div><span className="kicker">配置与安全</span><h2>项目设置</h2><p>当前正在编辑“{selectedProject.name}”。切换左侧项目后，这里的内容会同步切换。</p></div>
      <div className="page-heading-actions"><button className="button button-secondary" onClick={onStartCreate}>+ 新建项目</button><button className="button button-danger" onClick={onDeleteSelectedProject} disabled={busy}>删除当前项目</button></div>
    </div>
    <section className="card settings-editor">
      <div className="settings-section-heading"><span className="kicker">认证提供器</span><h3>登录、凭证提取与请求注入</h3></div>
      <label className="switch-row"><input type="checkbox" checked={projectEditor.authEnabled} onChange={(event) => onUpdateEditor({ authEnabled: event.target.checked })} /><span><strong>启用可配置认证</strong><small>认证请求只在执行前由后端确定性发送；凭证引用只保存 env:NAME，不会发送给模型。</small></span></label>
      <div className="form-grid database-fields auth-fields">
        <label>认证方式<select value={projectEditor.authKind} onChange={(event) => onUpdateEditor({ authKind: event.target.value as "http" | "sms" })} disabled={!projectEditor.authEnabled}><option value="http">HTTP 登录请求</option><option value="sms">短信验证码登录</option></select></label>
        <label>登录方法<input value={projectEditor.authLoginMethod} onChange={(event) => onUpdateEditor({ authLoginMethod: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="POST" /></label>
        <label>请求体类型<select value={projectEditor.authBodyType} onChange={(event) => onUpdateEditor({ authBodyType: event.target.value as "json" | "form" | "none" })} disabled={!projectEditor.authEnabled}><option value="json">JSON</option><option value="form">表单</option><option value="none">无请求体</option></select></label>
        <label>登录路径<input value={projectEditor.authLoginPath} onChange={(event) => onUpdateEditor({ authLoginPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="/auth/login" /></label>
        <label>提取来源<select value={projectEditor.authExtractSource} onChange={(event) => onUpdateEditor({ authExtractSource: event.target.value as "json" | "header" | "cookie" })} disabled={!projectEditor.authEnabled}><option value="json">JSON 响应</option><option value="header">响应头</option><option value="cookie">响应 Cookie</option></select></label>
        <label>提取路径或名称<input value={projectEditor.authExtractPath} onChange={(event) => onUpdateEditor({ authExtractPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="$.data.token 或 Set-Cookie 名称" /></label>
        <label>注入位置<select value={projectEditor.authInjectLocation} onChange={(event) => onUpdateEditor({ authInjectLocation: event.target.value as "header" | "cookie" })} disabled={!projectEditor.authEnabled}><option value="header">请求头</option><option value="cookie">请求 Cookie</option></select></label>
        <label>注入名称<input value={projectEditor.authInjectName} onChange={(event) => onUpdateEditor({ authInjectName: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="Authorization 或 session" /></label>
        <label>前缀<input value={projectEditor.authInjectPrefix} onChange={(event) => onUpdateEditor({ authInjectPrefix: event.target.value })} disabled={!projectEditor.authEnabled || projectEditor.authInjectLocation === "cookie"} placeholder="Bearer；Cookie 留空" /></label>
        <label>Token TTL（秒）<input type="number" min="1" max="604800" step="1" value={projectEditor.authTtlSeconds} onChange={(event) => onUpdateEditor({ authTtlSeconds: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="1800" /><small className="help-text">后端启动后按此周期自动刷新；留空仅在需要时获取。</small></label>
        {projectEditor.authKind === "sms" && <>
          <label>手机号环境变量引用<input value={projectEditor.authSmsPhoneRef} onChange={(event) => onUpdateEditor({ authSmsPhoneRef: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="env:TEST_LOGIN_PHONE" /></label>
          <label>验证码请求方法<input value={projectEditor.authSmsCodeMethod} onChange={(event) => onUpdateEditor({ authSmsCodeMethod: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="POST" /></label>
          <label>验证码请求路径<input value={projectEditor.authSmsCodePath} onChange={(event) => onUpdateEditor({ authSmsCodePath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="/auth/sms/code" /></label>
          <label>验证码来源<select value={projectEditor.authSmsCodeSource} onChange={(event) => onUpdateEditor({ authSmsCodeSource: event.target.value as "redis" | "json" })} disabled={!projectEditor.authEnabled}><option value="redis">Redis</option><option value="json">JSON 响应</option></select></label>
          <label>验证码提取路径或 Redis Key<input value={projectEditor.authSmsCodeSource === "redis" ? projectEditor.authSmsRedisKey : projectEditor.authSmsCodeExtractPath} onChange={(event) => onUpdateEditor(projectEditor.authSmsCodeSource === "redis" ? { authSmsRedisKey: event.target.value } : { authSmsCodeExtractPath: event.target.value })} disabled={!projectEditor.authEnabled} placeholder={projectEditor.authSmsCodeSource === "redis" ? "login:code:{{phone}}" : "$.data.code"} /></label>
          {projectEditor.authSmsCodeSource === "redis" && <>
            <label>Redis 地址<input value={projectEditor.authSmsRedisHost} onChange={(event) => onUpdateEditor({ authSmsRedisHost: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="127.0.0.1" /></label>
            <label>Redis 端口<input type="number" min="1" max="65535" value={projectEditor.authSmsRedisPort} onChange={(event) => onUpdateEditor({ authSmsRedisPort: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="6379" /></label>
            <label>Redis 密码引用<input value={projectEditor.authSmsRedisPasswordRef} onChange={(event) => onUpdateEditor({ authSmsRedisPasswordRef: event.target.value })} disabled={!projectEditor.authEnabled} placeholder="env:REDIS_PASSWORD" /></label>
          </>}
          <label className="field-wide">验证码请求参数（JSON）<textarea value={projectEditor.authSmsCodeQueryParams} onChange={(event) => onUpdateEditor({ authSmsCodeQueryParams: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"phone":"{{phone}}"}' /></label>
          <label className="field-wide">验证码请求头（JSON）<textarea value={projectEditor.authSmsCodeHeaders} onChange={(event) => onUpdateEditor({ authSmsCodeHeaders: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"Content-Type":"application/json"}' /></label>
          <label className="field-wide">验证码请求体（JSON）<textarea value={projectEditor.authSmsCodeBody} onChange={(event) => onUpdateEditor({ authSmsCodeBody: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"phone":"{{phone}}"}' /></label>
        </>}
        <label className="field-wide">登录查询参数（JSON）<textarea value={projectEditor.authQueryParams} onChange={(event) => onUpdateEditor({ authQueryParams: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder="{}" /></label>
        <label className="field-wide">登录请求头（JSON）<textarea value={projectEditor.authHeaders} onChange={(event) => onUpdateEditor({ authHeaders: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"Content-Type":"application/json"}' /></label>
        <label className="field-wide">登录请求体（JSON）<textarea value={projectEditor.authBody} onChange={(event) => onUpdateEditor({ authBody: event.target.value })} disabled={!projectEditor.authEnabled} rows={3} placeholder='{"username":"{{username}}","password":"{{password}}"}' /></label>
        <label className="field-wide">凭证引用（JSON）<textarea value={projectEditor.authCredentialRefs} onChange={(event) => onUpdateEditor({ authCredentialRefs: event.target.value })} disabled={!projectEditor.authEnabled} rows={2} placeholder='{"username":"env:TEST_LOGIN_USER","password":"env:TEST_LOGIN_PASSWORD"}' /></label>
      </div>
      <div className="card-heading"><div><span className="kicker">基本信息</span><h3>{selectedProject.name}</h3><p className="form-subtitle">项目编号 {selectedProject.project_id} · 更新于 {formatDate(selectedProject.updated_at)}</p></div><span className="status-badge status-ready">可编辑</span></div>
      <div className="form-grid">
        <label>项目名称<input value={projectEditor.name} onChange={(event) => onUpdateEditor({ name: event.target.value })} /></label>
        <label>被测服务 Base URL<input value={projectEditor.baseUrl} onChange={(event) => onUpdateEditor({ baseUrl: event.target.value })} placeholder="http://127.0.0.1:8081" /></label>
        <label className="field-wide">项目说明<textarea value={projectEditor.description} onChange={(event) => onUpdateEditor({ description: event.target.value })} rows={2} /></label>
        <label>请求超时（秒）<input type="number" min="0.1" max="300" step="0.1" value={projectEditor.timeoutSeconds} onChange={(event) => onUpdateEditor({ timeoutSeconds: event.target.value })} /></label>
        <label>源码工作区路径（可选）<input value={projectEditor.sourceWorkspace} onChange={(event) => onUpdateEditor({ sourceWorkspace: event.target.value })} placeholder="例如：D:\\workspace\\your-service" /></label>
        <label className="field-wide">接口描述来源（可选）<textarea value={projectEditor.openapiSources} onChange={(event) => onUpdateEditor({ openapiSources: event.target.value })} placeholder="每行一个本地文件或 URL" rows={3} /></label>
      </div>
      <label className="switch-row"><input type="checkbox" checked={projectEditor.verifyTls} onChange={(event) => onUpdateEditor({ verifyTls: event.target.checked })} /><span><strong>校验 HTTPS 证书</strong><small>本地 HTTP 服务不受影响；HTTPS 环境建议保持开启。</small></span></label>

      <div className="settings-section-heading"><span className="kicker">数据库真实夹具</span><h3>本地只读解析请求参数</h3></div>
      <label className="switch-row"><input type="checkbox" checked={projectEditor.databaseEnabled} onChange={(event) => onUpdateEditor({ databaseEnabled: event.target.checked })} /><span><strong>启用数据库真实夹具</strong><small>模型只选择无真实值的夹具令牌，后端在模型审查完成后从白名单表读取 ID 并本地替换。</small></span></label>
      <div className="form-grid database-fields">
        <label>数据库类型<select value={projectEditor.databaseDialect} onChange={(event) => onUpdateEditor({ databaseDialect: event.target.value })} disabled={!projectEditor.databaseEnabled}><option value="mysql">MySQL</option><option value="postgresql">PostgreSQL</option><option value="sqlite">SQLite</option></select></label>
        <label>连接环境变量引用<input value={projectEditor.databaseRef} onChange={(event) => onUpdateEditor({ databaseRef: event.target.value })} placeholder="env:TEST_DB_DSN" disabled={!projectEditor.databaseEnabled} /></label>
        <label>数据库 Schema（可选）<input value={projectEditor.databaseSchema} onChange={(event) => onUpdateEditor({ databaseSchema: event.target.value })} placeholder="例如：public" disabled={!projectEditor.databaseEnabled} /></label>
        <label>允许读取的表<textarea value={projectEditor.allowedTables} onChange={(event) => onUpdateEditor({ allowedTables: event.target.value })} placeholder="每行一个表名，例如：example_table" rows={3} disabled={!projectEditor.databaseEnabled} /></label>
      </div>
      <div className="form-note">真实数据库值不会发送给 DeepSeek。连接串必须放在本机环境变量中；设置页只保存 env:NAME 引用和表白名单。</div>
      <div className="form-actions"><button className="button button-primary" onClick={onSaveProjectSettings} disabled={busy}>保存当前项目设置</button></div>
    </section>
  </>;
}
