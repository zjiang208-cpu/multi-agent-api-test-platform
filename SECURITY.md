# Security Baseline

Phase 1 applies these rules:

- Secrets are represented by references such as `api_key_ref`, `dsn_ref`, or
  `auth_ref`, not secret values. The LLM uses only the original
  `DEEPSEEK_API_KEY` process environment variable.
- Configuration/status endpoints return whether an optional capability is
  configured, never its credential or raw environment value.
- Project payloads reject unknown fields so callers cannot silently persist raw
  password/token fields.
- Remote target execution is disabled by default.
- Project metadata is stored beneath the configured data directory.
- The platform does not import or execute target-project code.
- Automatic SMS login, when enabled by a configured phone reference, code
  endpoint, and Redis or JSON code source, only uses the declared target
  endpoints and configured code store. The resulting token is held in process
  memory and is never persisted, displayed, or sent to the LLM.
- Configured HTTP Auth Providers persist only request templates and environment
  variable references. Resolved login credentials are substituted in memory,
  extracted credentials are held only for the execution process, and injected
  request headers/cookies remain redacted in reports.

Source-root containment, sensitive-file rejection, read-only DB profiles,
request/response limits, and bounded/masked LLM prompts are implemented in the
current workflow. Real credentials remain outside the repository.
