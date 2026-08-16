# 基于 Multi-Agent 的接口自动化测试平台

这是一个基于 Multi-Agent 的接口自动化测试平台，面向通用接口需求文档，
通过多源证据完成接口识别、需求分析、测试点提取、用例设计、批量执行与报告生成。
平台与具体业务系统解耦，当前主流程使用 Markdown 格式的接口需求文档。

> 从需求文档到可执行测试报告的接口测试工作台。

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

## 产品演示

下面以 `GET /shop/{id}` 接口为例，展示平台如何从需求文档逐步完成接口识别、
需求分析、测试用例设计、批量执行和报告生成。

### 一眼看懂流程

```text
需求文档 → 接口选择 → 需求分析 → 需求确认 → 用例设计 → 执行确认 → 测试执行 → 测试报告
```

所有截图保留原始比例，并统一使用 960px 展示宽度。

### 1. 项目概览：确认当前任务和阶段

<p align="center"><img src="docs/screenshots/01-project-overview.png" width="960" alt="项目概览：显示当前项目、任务进度和下一步操作"></p>

页面左侧是项目和测试流程导航，顶部是 7 阶段进度条，中间区域显示当前项目、
已识别接口、需求文档和测试用例数量。首次进入时，系统提示先上传需求文档。

### 2. 输入需求文档：上传或粘贴 Markdown

<p align="center"><img src="docs/screenshots/02-requirement-document.png" width="960" alt="需求文档：上传文件或直接粘贴内容"></p>

用户可以上传 Markdown 文件，也可以直接粘贴业务背景、接口规则、异常场景和响应约定。
平台会保留原文，后续解析结果都可以回溯到需求来源。

### 3. 解析成功：识别接口和文档信息

<p align="center"><img src="docs/screenshots/03-requirement-parsed.png" width="960" alt="需求文档解析成功：显示文档统计和识别到的接口数量"></p>

解析完成后，页面展示文件名、字符数、行数和文档编号，并提示从需求原文中识别出的
可测试接口数量。解析结果会成为后续接口目录和需求分析的输入。

### 4. 接口目录：选择本次要分析的接口

<p align="center"><img src="docs/screenshots/04-interface-catalog.png" width="960" alt="接口目录：展示接口方法、路径、说明和需求来源"></p>

接口目录将需求文档中的接口集中展示。用户可以查看 HTTP 方法、路径、接口说明、
原文行号和来源文档，并选择一个接口进入后续流程。

### 5. 需求分析：提取业务规则和测试点

<p align="center"><img src="docs/screenshots/05-requirement-analysis.png" width="960" alt="需求分析：后台分析当前接口的需求和测试点"></p>

NLU 角色根据需求原文和关联证据提取业务规则、成功与失败场景、参数约束和待确认问题。
页面会显示处理队列和当前接口，前端可以在后台处理期间保持响应。

### 6. 需求确认：人工检查分析结果

<p align="center"><img src="docs/screenshots/06-requirement-confirmation.png" width="960" alt="需求确认：查看业务规则、测试点和辅助证据"></p>

用户在这里确认需求快照是否准确：左侧是业务规则和预期行为，右侧是测试点与证据来源，
底部集中显示待确认问题。只有确认后，系统才会进入用例设计。

### 7. 用例设计：生成并审查测试用例

<p align="center"><img src="docs/screenshots/07-test-case-design.png" width="960" alt="用例设计：显示接口处理进度和后台设计状态"></p>

Designer 根据确认后的需求和测试点生成测试用例，Reviewer 负责检查覆盖范围、
请求可执行性、断言和证据映射，把“应该验证什么”转换成可执行测试。

### 8. 测试用例：选择要执行的用例集合

<p align="center"><img src="docs/screenshots/08-test-cases.png" width="960" alt="测试用例：按接口查看并批量选择生成的用例"></p>

用户可以展开接口查看用例名称、分类和预期行为，并批量勾选本次执行范围。
示例覆盖成功、资源不存在和参数边界等场景。

### 9. 执行确认：确认目标环境和副作用

<p align="center"><img src="docs/screenshots/09-execution-confirmation.png" width="960" alt="执行确认：确认接口数量、用例数量和自动回归策略"></p>

在真正发起请求前，系统要求确认目标环境、服务地址、用例数量、副作用用例以及
自动回归策略。这个人工闸门用于防止误把测试请求发送到生产环境。

### 10. 测试报告：查看执行结果和断言明细

<p align="center"><img src="docs/screenshots/10-test-report.png" width="960" alt="测试报告：查看 PASS、FAIL、HTTP 状态和断言结果"></p>

报告中心汇总总用例数、PASS、FAIL 和断言失败数量，并按接口列出每个用例的
HTTP 状态、断言通过数和详情入口。报告还支持导出 HTML，便于归档或交付。

### 演示重点

- 需求、接口、测试点、用例和报告之间保持可追溯关系。
- NLU、Designer、Reviewer 负责理解和审查；HTTP 执行和断言由确定性执行层完成。
- 需求确认和执行确认是两个独立人工闸门，分别控制规则正确性和执行授权。
- 示例数据用于展示流程，不代表生产数据。

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
