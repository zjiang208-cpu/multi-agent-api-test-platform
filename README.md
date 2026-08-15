# 基于 Multi-Agent 的接口自动化测试平台

这是一个基于 Multi-Agent 的接口自动化测试平台，面向通用接口需求文档，
通过多源证据完成接口识别、需求分析、测试点提取、用例设计、批量执行与报告生成。
平台与具体业务系统解耦，支持 Markdown、OpenAPI、YAML 等需求与接口描述来源。

The current implementation phase is recorded in:

- `CURRENT_ARCHITECTURE.md`
- `MIGRATION_PLAN.md`

## Quick start (`pytorch` environment)

```powershell
cd backend
conda run -n pytorch python -m pip install -e ".[dev]"
conda run -n pytorch uvicorn app.main:app --reload --port 8000
```

Health check: `http://127.0.0.1:8000/health`

API documentation: `http://127.0.0.1:8000/docs`

Start the frontend in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

The frontend defaults to `http://127.0.0.1:5173`. The backend defaults to
`http://127.0.0.1:8000`, and the tested Java service defaults to
`http://127.0.0.1:8081`. To use another frontend port, set
`VITE_PORT` before running the development server.

当前实现包含项目与设置管理、多源证据采集、需求文档解析、接口级顺序处理、
测试点与测试用例设计、人工执行确认、确定性批量执行、断言评估和报告中心。
NLU、Designer、Reviewer 三个智能角色负责需求理解、用例设计与语义检查，
执行层使用确定性 HTTP、鉴权和断言逻辑，避免将执行结果交给模型猜测。

Production prompts are versioned YAML files under `backend/config/prompts`:
`nlu.v1.yaml`, `designer.v1.yaml`, and `reviewer.v1.yaml`. Each workflow snapshot
records the independent prompt versions and SHA-256 hashes.

Operations can be discovered from OpenAPI or from the platform's
one-operation-per-YAML contracts by placing the file paths in a project's
`requirement_sources`. The YAML contract's preconditions, business rules,
response scenarios, and unresolved questions become traceable operation
metadata and evidence.

No target project, local machine path, credential, or API key is a platform
default. Configure those values through private environment/project settings.

LLM configuration follows the original platform's process environment
contract: `DEEPSEEK_API_KEY` is the only credential variable, the provider is
OpenAI-compatible DeepSeek, the model is `deepseek-v4-flash`, and the endpoint
is `https://api.deepseek.com/v1`. Other vendor environment variables are not
auto-detected. Only the `env:DEEPSEEK_API_KEY` reference is stored; the secret
value is never persisted or returned by the API.

Database DSNs and target authentication follow the same pattern: configure the
project with `dsn_ref=env:...` or `auth_ref=env:...`; the Python process resolves
the value only at the moment it is needed.

Targets use the portable `auth_provider` project setting. Configure
`login` (method, path, request template, and `credential_refs`), `extract`
(`json`, response `header`, or `cookie` plus a path/name), and `inject` (request
header or cookie name and optional prefix). Login templates reference secrets
with `{{name}}`; only the corresponding `env:NAME` references are persisted.
The provider executes this deterministic sequence before the test batch. When
`token_ttl_seconds` is set, the backend also refreshes the credential in the
background from startup until shutdown, so the target may be implemented in
Java, Python, Go, or have no source workspace at all.

`auth_provider.kind` supports both `http` and `sms`. The SMS adapter accepts a
phone environment reference, a code-request template, a Redis or JSON code
source, and a login template. Its Redis host, port, password reference, and key
pattern are all configurable; no target-specific table or endpoint is assumed.

The portable shape is:

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
