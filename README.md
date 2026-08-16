# 基于 Multi-Agent 的接口自动化测试平台

这是一个基于 Multi-Agent 的接口自动化测试平台，面向通用接口需求文档，
通过多源证据完成接口识别、需求分析、测试点提取、用例设计、批量执行与报告生成。
平台与具体业务系统解耦，当前主流程使用 Markdown 格式的接口需求文档。

> 从需求文档到可执行测试报告的接口测试工作台。

## 产品演示

本仓库包含一条完整的 7 阶段演示流程：需求文档、接口选择、需求分析、需求确认、
用例设计、执行确认、测试执行和测试报告。截图按实际运行顺序整理在
[`docs/screenshots/`](docs/screenshots/)，流程说明和部署边界见
[`docs/workflow.md`](docs/workflow.md)。

![项目概览](docs/screenshots/01-project-overview.png)

![需求确认](docs/screenshots/06-requirement-confirmation.png)

![测试报告](docs/screenshots/10-test-report.png)

## 核心能力

- Markdown、OpenAPI 和单接口 YAML 契约导入
- NLU、Designer、Reviewer 三个智能角色协作
- 接口识别、测试点提取和测试用例设计
- 人工确认节点和副作用用例保护
- 确定性 HTTP 执行、鉴权注入和断言评估
- 批量执行结果与 HTML 测试报告

当前实现阶段记录在：

- `CURRENT_ARCHITECTURE.md`
- `MIGRATION_PLAN.md`

## 快速开始（`pytorch` 环境）

```powershell
cd backend
conda run -n pytorch python -m pip install -e ".[dev]"
conda run -n pytorch uvicorn app.main:app --reload --port 8000
```

健康检查：`http://127.0.0.1:8000/health`

接口文档：`http://127.0.0.1:8000/docs`

在另一个终端启动前端：

```powershell
cd frontend
npm install
npm run dev
```

前端默认地址为 `http://127.0.0.1:5173`，后端默认地址为
`http://127.0.0.1:8000`，被测服务默认地址为 `http://127.0.0.1:8081`。
如需使用其他前端端口，请在启动开发服务器前设置 `VITE_PORT`。

> 本地开发时，Vite 会把 `/api` 请求代理到后端。部署到 GitHub Pages 时只能展示静态页面，
> 不能直接运行 FastAPI 和本地 `.data` 存储；完整在线 Demo 需要同时部署后端，并配置反向代理或
> 生产环境 API 地址。详细说明见 [`docs/workflow.md`](docs/workflow.md)。

当前实现包含项目与设置管理、多源证据采集、需求文档解析、接口级顺序处理、
测试点与测试用例设计、人工执行确认、确定性批量执行、断言评估和报告中心。
NLU、Designer、Reviewer 三个智能角色负责需求理解、用例设计与语义检查，
执行层使用确定性 HTTP、鉴权和断言逻辑，避免将执行结果交给模型猜测。

生产环境提示词以版本化 YAML 文件保存在 `backend/config/prompts` 下：
`nlu.v1.yaml`、`designer.v1.yaml` 和 `reviewer.v1.yaml`。每个工作流快照都会记录
各提示词的独立版本和 SHA-256 哈希值。

当前主流程使用 Markdown 格式的接口需求文档。接口目录也可以通过项目的
`requirement_sources` 导入 OpenAPI 文档或平台规定的“一文件一个接口” YAML
契约；契约中的前置条件、业务规则、响应场景和待确认问题会保留为可追溯的接口
元数据与证据。

平台不会预置目标项目、本机路径、凭证或 API 密钥。请通过私有环境变量和项目设置
配置这些内容。

LLM 配置遵循平台的进程环境变量约定：唯一的模型凭证变量是
`DEEPSEEK_API_KEY`，服务商为兼容 OpenAI 接口的 DeepSeek，模型为
`deepseek-v4-flash`，接口地址为 `https://api.deepseek.com/v1`。平台不会自动探测
其他服务商的环境变量。系统只保存 `env:DEEPSEEK_API_KEY` 引用，不会持久化或通过
接口返回密钥值。

数据库 DSN 和被测服务鉴权采用相同模式：在项目中配置
`dsn_ref=env:...` 或 `auth_ref=env:...`，由 Python 进程仅在需要时解析实际值。

被测服务使用通用的 `auth_provider` 项目设置。请配置 `login`（方法、路径、请求
模板和 `credential_refs`）、`extract`（`json`、响应 `header` 或 `cookie`，以及路径
或名称）和 `inject`（请求头或 Cookie 名称及可选前缀）。登录模板使用 `{{name}}`
引用密钥，系统只保存对应的 `env:NAME` 引用。执行批量测试前，Provider 会按此确定性
顺序获取凭证；设置 `token_ttl_seconds` 后，后端会从启动到关闭期间在后台自动刷新凭证。

`auth_provider.kind` 支持 `http` 和 `sms` 两种方式。短信适配器支持手机号环境变量
引用、验证码请求模板、Redis 或 JSON 验证码来源以及登录模板；Redis 主机、端口、
密码引用和键名模式均可配置，不假定任何业务专用表或接口。

通用 HTTP 鉴权配置示例：

```json
{
  "auth_provider": {
    "enabled": true,
    "kind": "http",
    "token_ttl_seconds": 1800,
    "login": {
      "method": "POST",
      "path": "/auth/login",
      "body_type": "json",
      "body": {"username": "{{username}}", "password": "{{password}}"},
      "credential_refs": {
        "username": "env:TEST_LOGIN_USER",
        "password": "env:TEST_LOGIN_PASSWORD"
      }
    },
    "extract": {"source": "json", "path": "$.data.token"},
    "inject": {"location": "header", "name": "Authorization", "prefix": "Bearer"}
  }
}
```

短信模式只需把 `kind` 改为 `sms`，并填写验证码请求、验证码来源和登录请求：

```json
{
  "kind": "sms",
  "token_ttl_seconds": 1800,
  "sms": {
    "phone_ref": "env:TEST_LOGIN_PHONE",
    "code_request": {"method": "POST", "path": "/auth/sms/code", "body_type": "none"},
    "code_source": "redis",
    "code_path": "login:code:{{phone}}",
    "redis_host": "127.0.0.1",
    "redis_port": 6379,
    "redis_password_ref": "env:REDIS_PASSWORD",
    "login": {"method": "POST", "path": "/auth/sms/login", "body_type": "json", "body": {"phone": "{{phone}}", "code": "{{code}}"}}
  },
  "extract": {"source": "json", "path": "$.data.token"},
  "inject": {"location": "header", "name": "Authorization", "prefix": "Bearer"}
}
```

## 公开仓库安全清单

- 不要提交 `.env`、真实账号、密码、Token、API Key 或业务需求原文。
- `.env.example` 只保留变量名和空值，真实值放在本机环境或部署平台的 Secret 中。
- `.data/`、`output/`、`tmp/` 和本地评测指标属于运行产物，不作为源码发布。
- 执行真实接口前，请确认目标环境、鉴权配置和副作用用例；建议只使用隔离测试环境。

## 项目文档

- [`docs/workflow.md`](docs/workflow.md)：产品流程、截图说明和部署建议
- [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md)：当前架构和实现边界
- [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md)：后续演进计划
- [`SECURITY.md`](SECURITY.md)：安全问题反馈方式
