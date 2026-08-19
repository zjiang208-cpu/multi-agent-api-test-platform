import { api } from "../api/client";
import { splitLines } from "../app/platform";
import type { Dispatch, SetStateAction } from "react";
import type { PageKey, ProjectEditor } from "../app/platform";
import type {
  OperationContract,
  ProjectSettings,
  TestProject,
} from "../types/api";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export interface ProjectActionContext {
  projects: TestProject[];
  selectedProject: TestProject | null;
  projectEditor: ProjectEditor | null;
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
  setProjects: StateSetter<TestProject[]>;
  setSelectedProject: StateSetter<TestProject | null>;
  setShowCreateForm: StateSetter<boolean>;
  setPage: StateSetter<PageKey>;
  setMessage: StateSetter<string>;
  setBusy: StateSetter<boolean>;
  setSaveSuccess: StateSetter<{ name: string; authSuccess: boolean; authMessage: string } | null>;
  setBaseUrl: StateSetter<string>;
  setOperations: StateSetter<OperationContract[]>;
}

export function createProjectActions(context: ProjectActionContext) {
  const {
    projects,
    selectedProject,
    projectEditor,
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
    setProjects,
    setSelectedProject,
    setShowCreateForm,
    setPage,
    setMessage,
    setBusy,
    setSaveSuccess,
    setBaseUrl,
    setOperations,
  } = context;

  async function createProject() {
    if (!newProjectName.trim() || !newBaseUrl.trim()) return;
    if (newDbEnabled && (!newDbRef.trim() || splitLines(newDbTables).length === 0)) {
      setMessage("启用数据库证据时，必须填写数据库连接引用和允许读取的表名。");
      return;
    }
    setBusy(true);
    setMessage("正在创建测试项目…");
    const settings: ProjectSettings = {
      openapi_sources: splitLines(newOpenapiSource),
      source_workspace: newWorkspace.trim() || null,
      sut_target: { base_url: newBaseUrl.trim(), timeout_seconds: 10, allow_redirects: false, verify_tls: newBaseUrl.startsWith("https://"), auth_ref: null },
      auth_provider: { enabled: false, kind: "http", token_ttl_seconds: 1800, login: null, extract: { source: "json", path: "$.data" }, inject: { location: "header", name: "Authorization", prefix: "Bearer" } },
      database: { enabled: newDbEnabled, dialect: newDbEnabled ? newDbDialect : null, dsn_ref: newDbEnabled && newDbRef.trim() ? newDbRef.trim() : null, readonly: true, schema: newDbEnabled && newDbSchema.trim() ? newDbSchema.trim() : null, allowed_tables: newDbEnabled ? splitLines(newDbTables) : [] },
      llm: { enabled: true, provider: "openai_compatible", model: "deepseek-v4-flash", api_key_ref: "env:DEEPSEEK_API_KEY", base_url: "https://api.deepseek.com/v1", call_budget: 20 },
    };
    try {
      const project = await api.createProject({ name: newProjectName.trim(), description: newProjectDescription.trim(), settings });
      setProjects((current) => [...current, project]);
      setSelectedProject(project);
      setShowCreateForm(false);
      setPage("overview");
      setMessage("项目已创建。需求文档仍需在独立的“需求文档”页面解析。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setBusy(false);
    }
  }

  function startCreateProject() {
    setShowCreateForm(true);
    setPage("settings");
    setMessage("请填写新项目配置。现有项目不会被修改。");
  }

  async function saveProjectSettings() {
    if (!selectedProject || !projectEditor) return;
    setSaveSuccess(null);
    const timeoutSeconds = Number(projectEditor.timeoutSeconds);
    const tokenTtlSeconds = projectEditor.authTtlSeconds.trim() ? Number(projectEditor.authTtlSeconds) : null;
    const smsRedisPort = Number(projectEditor.authSmsRedisPort);
    if (!projectEditor.name.trim() || !projectEditor.baseUrl.trim()) {
      setMessage("项目名称和被测服务 Base URL 不能为空。");
      return;
    }
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0 || timeoutSeconds > 300) {
      setMessage("请求超时必须是 0 到 300 之间的数字。");
      return;
    }
    if (tokenTtlSeconds !== null && (!Number.isInteger(tokenTtlSeconds) || tokenTtlSeconds <= 0 || tokenTtlSeconds > 604800)) {
      setMessage("Token TTL 必须是 1 到 604800 秒之间的整数，留空可关闭自动刷新");
      return;
    }
    if (projectEditor.authKind === "sms" && (!projectEditor.authSmsPhoneRef.trim() || !projectEditor.authSmsCodePath.trim() || !Number.isInteger(smsRedisPort) || smsRedisPort < 1 || smsRedisPort > 65535)) {
      setMessage("短信验证需要手机号环境变量、验证码路径和有效的 Redis 端口");
      return;
    }
    let authQueryParams: Record<string, unknown> = {};
    let authHeaders: Record<string, string> = {};
    let authCredentialRefs: Record<string, string> = {};
    let authBody: unknown = null;
    let authSmsCodeQueryParams: Record<string, unknown> = {};
    let authSmsCodeHeaders: Record<string, string> = {};
    let authSmsCodeBody: unknown = null;
    try {
      authQueryParams = projectEditor.authQueryParams.trim() ? JSON.parse(projectEditor.authQueryParams) : {};
      authHeaders = projectEditor.authHeaders.trim() ? JSON.parse(projectEditor.authHeaders) : {};
      authCredentialRefs = projectEditor.authCredentialRefs.trim() ? JSON.parse(projectEditor.authCredentialRefs) : {};
      authBody = projectEditor.authBody.trim() ? JSON.parse(projectEditor.authBody) : null;
      authSmsCodeQueryParams = projectEditor.authSmsCodeQueryParams.trim() ? JSON.parse(projectEditor.authSmsCodeQueryParams) : {};
      authSmsCodeHeaders = projectEditor.authSmsCodeHeaders.trim() ? JSON.parse(projectEditor.authSmsCodeHeaders) : {};
      authSmsCodeBody = projectEditor.authSmsCodeBody.trim() ? JSON.parse(projectEditor.authSmsCodeBody) : null;
      if (!authQueryParams || Array.isArray(authQueryParams) || typeof authQueryParams !== "object") throw new Error("登录查询参数必须是 JSON 对象");
      if (!authHeaders || Array.isArray(authHeaders) || typeof authHeaders !== "object") throw new Error("登录请求头必须是 JSON 对象");
      if (!authCredentialRefs || Array.isArray(authCredentialRefs) || typeof authCredentialRefs !== "object") throw new Error("凭证引用必须是 JSON 对象");
      if (!authSmsCodeQueryParams || Array.isArray(authSmsCodeQueryParams) || typeof authSmsCodeQueryParams !== "object") throw new Error("短信验证码查询参数必须是 JSON 对象");
      if (!authSmsCodeHeaders || Array.isArray(authSmsCodeHeaders) || typeof authSmsCodeHeaders !== "object") throw new Error("短信验证码请求头必须是 JSON 对象");
    } catch (error) {
      setMessage(error instanceof Error ? `认证配置 JSON 无效：${error.message}` : "认证配置 JSON 无效");
      return;
    }
    if (projectEditor.databaseEnabled && (!projectEditor.databaseRef.trim() || splitLines(projectEditor.allowedTables).length === 0)) {
      setMessage("启用数据库证据时，必须填写数据库连接引用和允许读取的表名。");
      return;
    }
    const settings: ProjectSettings = {
      ...selectedProject.settings,
      openapi_sources: splitLines(projectEditor.openapiSources),
      source_workspace: projectEditor.sourceWorkspace.trim() || null,
      sut_target: {
        ...selectedProject.settings.sut_target,
        base_url: projectEditor.baseUrl.trim(),
        timeout_seconds: timeoutSeconds,
        verify_tls: projectEditor.verifyTls,
      },
      auth_provider: {
        enabled: projectEditor.authEnabled,
        kind: projectEditor.authKind,
        token_ttl_seconds: tokenTtlSeconds,
        login: projectEditor.authKind === "http" ? {
          method: projectEditor.authLoginMethod.trim() || "POST",
          path: projectEditor.authLoginPath.trim(),
          body_type: projectEditor.authBodyType,
          query_params: authQueryParams,
          headers: authHeaders,
          body: authBody,
          credential_refs: authCredentialRefs,
        } : null,
        extract: { source: projectEditor.authExtractSource, path: projectEditor.authExtractPath.trim() || "$.data" },
        inject: { location: projectEditor.authInjectLocation, name: projectEditor.authInjectName.trim() || "Authorization", prefix: projectEditor.authInjectPrefix.trim() || null },
        sms: {
          phone_ref: projectEditor.authSmsPhoneRef.trim(),
          code_request: {
            method: projectEditor.authSmsCodeMethod.trim() || "POST",
            path: projectEditor.authSmsCodePath.trim(),
            body_type: projectEditor.authSmsCodeBodyType,
            query_params: authSmsCodeQueryParams,
            headers: authSmsCodeHeaders,
            body: authSmsCodeBody,
            credential_refs: {},
          },
          code_source: projectEditor.authSmsCodeSource,
          code_path: (projectEditor.authSmsCodeSource === "redis" ? projectEditor.authSmsRedisKey : projectEditor.authSmsCodeExtractPath).trim(),
          redis_host: projectEditor.authSmsRedisHost.trim() || "127.0.0.1",
          redis_port: smsRedisPort,
          redis_password_ref: projectEditor.authSmsRedisPasswordRef.trim() || null,
          login: {
            method: projectEditor.authLoginMethod.trim() || "POST",
            path: projectEditor.authLoginPath.trim(),
            body_type: projectEditor.authBodyType,
            query_params: authQueryParams,
            headers: authHeaders,
            body: authBody,
            credential_refs: authCredentialRefs,
          },
        },
      },
      database: {
        enabled: projectEditor.databaseEnabled,
        dialect: projectEditor.databaseEnabled ? projectEditor.databaseDialect : null,
        dsn_ref: projectEditor.databaseEnabled ? projectEditor.databaseRef.trim() : null,
        readonly: true,
        schema: projectEditor.databaseEnabled && projectEditor.databaseSchema.trim() ? projectEditor.databaseSchema.trim() : null,
        allowed_tables: projectEditor.databaseEnabled ? splitLines(projectEditor.allowedTables) : [],
      },
    };
    setBusy(true);
    setMessage("正在保存当前项目设置…");
    try {
      const updated = await api.updateProject(selectedProject.project_id, {
        name: projectEditor.name.trim(),
        description: projectEditor.description.trim(),
        settings,
      });
      setProjects((current) => current.map((project) => project.project_id === updated.project_id ? updated : project));
      setSelectedProject(updated);
      setBaseUrl(updated.settings.sut_target.base_url);
      let authSuccess = true;
      let authMessage = projectEditor.authEnabled
        ? "正在执行鉴权预检"
        : "项目未启用可配置鉴权，未执行 Token 预检";
      if (projectEditor.authEnabled) {
        try {
          const authResult = await api.refreshProjectAuth(updated.project_id);
          authSuccess = authResult.success;
          authMessage = authResult.message;
        } catch (error) {
          authSuccess = false;
          authMessage = error instanceof Error ? error.message : "Token 预检请求失败";
        }
      }
      setMessage(authSuccess
        ? `项目“${updated.name}”设置已保存，鉴权预检成功。`
        : `项目“${updated.name}”设置已保存，但 Token 获取失败：${authMessage}`);
      setSaveSuccess({ name: updated.name, authSuccess, authMessage });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存项目设置失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedProject() {
    if (!selectedProject) return;
    const projectToDelete = selectedProject;
    if (!window.confirm(`确定从项目列表删除“${projectToDelete.name}”吗？删除后平台将不再加载该项目。`)) return;
    setBusy(true);
    setMessage(`正在删除项目“${projectToDelete.name}”…`);
    try {
      await api.deleteProject(projectToDelete.project_id);
      const remaining = projects.filter((project) => project.project_id !== projectToDelete.project_id);
      setProjects(remaining);
      setSelectedProject(remaining[0] ?? null);
      setShowCreateForm(remaining.length === 0);
      setPage(remaining.length === 0 ? "settings" : "overview");
      setMessage(remaining.length ? "项目已删除，已切换到其他项目。" : "项目已删除，可以创建新的测试项目。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除项目失败");
    } finally {
      setBusy(false);
    }
  }

  async function discoverOperations() {
    if (!selectedProject) return;
    setBusy(true);
    setMessage("正在读取 OpenAPI 与接口契约…");
    try {
      const result = await api.discoverOperations(selectedProject.project_id);
      setOperations(result.operations);
      setPage("operations");
      setMessage(`已发现 ${result.operations.length} 个可测试接口。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "接口发现失败");
    } finally {
      setBusy(false);
    }
  }

  return {
    createProject,
    startCreateProject,
    saveProjectSettings,
    deleteSelectedProject,
    discoverOperations,
  };
}

