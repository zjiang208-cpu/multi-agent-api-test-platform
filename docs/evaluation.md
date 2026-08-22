# 离线 LLM 质量评测

项目新增了一套不依赖线上服务的离线评测框架，入口为：

```powershell
python -m evals.runner --dataset <manifest.yaml> --input <eval-samples.json>
```

报告同时生成 JSON 和 HTML。评测结果必须来自人工确认的 Ground Truth；未完成标注时报告状态为
`pending_annotation`，不会生成质量分数。若人工确认某条必要断言是模型漏生成，应写入
`reviewed_missing_assertion_ids`：报告可以进入 `ready`，但该断言仍计入分母、不会计入匹配数。

## 评测边界

Ground Truth 只标注接口应覆盖的核心 Test Point，不强行规定唯一的标准 Case。每个 Test Point 可以声明必要的断言，人工映射负责处理自然语言语义差异。

| 层级 | 指标 | 判定方式 |
| --- | --- | --- |
| NLU | Test Point Recall | 生成 Test Point 覆盖的 Ground Truth 数 / Ground Truth 总数 |
| NLU | Response Test Point Recall | 生成 Test Point 覆盖的自动响应断言点 / 响应断言点总数 |
| NLU | Observation Test Point Recall | 生成 Test Point 覆盖的人工观察点 / 观察点总数；不等同于自动执行能力 |
| NLU | Test Point Precision | 有证据支持的生成 Test Point 数 / 生成总数 |
| NLU | Hallucination Rate | 无证据支持的生成 Test Point 数 / 生成总数 |
| Designer | Test Point Coverage | 至少被一个 Case 引用的 Ground Truth Test Point / Ground Truth 总数 |
| Designer | Response Test Point Coverage | 被 Case 实质覆盖的自动响应断言点 / 响应断言点总数 |
| Designer | Observation Coverage | 被 Case 引用且完成人工映射的 `verification_mode: observation` 契约点 / 观察契约点总数；它是覆盖准备度，不等同于缓存、数据库或 Redis 观察证据已经执行成功 |
| Designer | Assertion Coverage | 已映射的必要断言 / 必要断言总数 |
| Designer | Executable Case Rate | 通过现有 Case Validator 的 Case / Case 总数 |
| Designer | Duplicate Rate | 重复 Case 数 / Case 总数 |
| Reviewer | Gap Recall / Precision | 对已知 Mutation 缺陷的发现结果进行确定性匹配 |
| Telemetry | First-pass、Repair、Retry、耗时、Token | 聚合 workflow snapshot 中已有的调用元数据 |

`assertion_matches` 表示“生成结果实际提供了对应断言”，`reviewed_missing_assertion_ids` 表示“人工确认
该必要断言在本次生成中缺失”。后者用于区分评测标注尚未完成和模型确实漏测，不能当作通过。

## Reviewer Mutation

`evals/mutations/reviewer_mutations.py` 提供四类已知缺陷：

- 删除 Case，制造 Test Point 覆盖缺口；
- 删除必填 path 参数值，制造结构合法但请求不可执行的用例；
- 复制 Case，制造重复用例；
- 把 Assertion 改成执行器不支持的通配符路径。

Mutation 的目标由程序记录，Reviewer 只需要输出结构化发现，评测器据此计算 Gap Recall、Gap Precision 和 False Positive Rate。第一版不使用 LLM-as-a-Judge。

四类缺陷分别对应 `missing_test_point_ids`、`invalid_case_ids`、`duplicate_case_ids` 和
`unsupported_assertion_ids`。不使用“删除单条断言后要求 Reviewer 返回已删除 Assertion ID”的口径，
因为该 ID 已不在 Reviewer 输入中；也不把证据不足但结构合法的断言误算为 `unsupported_assertion_ids`。

生产 Reviewer 的离线 Mutation 执行器不会启动 FastAPI 或被测系统。先执行 dry-run：

```powershell
python -m evals.reviewer_runner `
  --snapshot path/to/private-workflow-snapshot.yaml `
  --base-sample evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --plan evals/datasets/baseline_v1/reviewer_mutation_plan.yaml `
  --data-dir backend/.data `
  --dry-run
```

dry-run 通过后，在已安全设置 `DEEPSEEK_API_KEY` 的同一终端运行：

```powershell
python -m evals.reviewer_runner `
  --snapshot path/to/private-workflow-snapshot.yaml `
  --base-sample evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --plan evals/datasets/baseline_v1/reviewer_mutation_plan.yaml `
  --data-dir backend/.data `
  --output evals/datasets/baseline_v1/samples/get-shop-id-reviewer-results-redacted.json
```

执行器复用生产 Reviewer、当前提示词、证据裁剪和重试配置，只落盘结构化 Reviewer 字段及
Token/耗时/重试元数据。输出写入 Git 忽略目录，并在写入前执行脱敏审计；原始提示词、原始模型响应、
项目 ID 和密钥不会进入结果文件。

正式 Reviewer Suite 应包含一份未变异对照组。评测器会从 Mutation 发现中扣除对照组已有发现，
再计算净新增缺陷的 Recall、Precision 和 False Positive Rate，避免把基础样本原有问题误算成 Mutation 误报。
Reviewer 汇总指标可以处于 `ready`；当整个 Ground Truth manifest 尚未完成确认时，报告总状态仍保持
`pending_annotation`，两者含义不同。

当全量 manifest 尚未确认时，可以在用户明确确认单接口 Ground Truth 后生成 verified pilot。当前保留的 get-shop Pilot 仍用于复现首个接口的历史评测：

```powershell
python -m evals.pilot `
  --dataset evals/datasets/baseline_v1/manifest.yaml `
  --input evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --operation-id get-shop-id `
  --output evals/datasets/baseline_v1/pilots/get-shop-id-verified.yaml `
  --confirm-ground-truth
```

该命令要求生成 Test Point 全部完成注释、所有必要断言完成映射，并且不会修改全量 manifest。

同一 Workflow 的 Designer 草稿与 Reviewer 最终结果可以生成脱敏 Ablation 包：

```powershell
python -m evals.build_ablation_pack `
  --input evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --snapshot path/to/private-workflow-snapshot.yaml `
  --output evals/datasets/baseline_v1/samples/get-shop-id-ablation-redacted.json
```

Ablation 只比较同一次运行中的结构变化与指标差异，不把不同提示词版本、不同业务数据或不同模型调用混在一起。Reviewer 未自动改写用例时，结构指标增量可以为 0；报告仍会按类别记录 Reviewer 的诊断项数量，用于区分“没有自动修复”与“没有发现问题”。缺陷召回率、精确率和误报率仍必须由独立的 Reviewer 缺陷注入套件计算，不能从普通 Ablation 样本推断。

## 从接口需求文档建立候选 Ground Truth

可以先对本地 Markdown 接口需求目录运行：

```powershell
python -m evals.requirements_catalog `
  --source "path/to/hm-dianping/docs/api" `
  --output evals/datasets/baseline_v1/requirements_catalog.yaml
```

生成结果只保留接口编号、方法、路径、权限、章节元数据和候选 Test Point，不复制需求正文。每个候选点的状态为 `draft`，需要人工确认后才能合并到正式 `manifest.yaml`。`audit` 区域会单独列出重复编号、编号空档、旧兼容接口、缺少验收章节和缺少失败章节的文档。

当前目录规范化口径已经固定：注销当前账户使用 `USER-009`，`USER-001/002` 暂不纳入范围；图片删除的 DELETE 接口作为推荐契约，GET 接口作为兼容契约，两者分别保留观察态和目标态。

再用历史 baseline 和候选目录生成 10 个基线接口的待标注清单：

```powershell
python -m evals.runner `
  --scaffold-from-baseline evals/datasets/baseline_v1/sources/baseline_fresh_metrics_20260817_020506.json `
  --catalog evals/datasets/baseline_v1/requirements_catalog.yaml `
  --manifest-output evals/datasets/baseline_v1/manifest.yaml
```

清单中的 `verification_mode: observation` 表示需要通过缓存、数据库、用户状态或多次请求观察验证的契约，不会被误当作普通 JSON 断言；只有人工确认后，才允许将数据集改为 `verified`。
同时，具备前置数据或可观测性要求的点会写入 `preconditions`，用于在执行前检查数据准备是否充分；它们不是自动生成的质量分数。
对应的 `fixture_requirements` 会区分三种情况：`local_token` 使用 `$DB_FIXTURE[...]` 或 `$AUTH_FIXTURE[...]` 脱敏令牌由后端本地解析，`manual_setup` 需要测试环境准备状态，`manual_observation` 需要缓存、数据库或会话观察。没有现成安全令牌的场景不会猜测真实 ID、名称或凭据。
路径参数缺失等路由级边界不与业务参数断言混合，当前 Operation 只纳入可通过既定路径模板执行的参数边界。

当前 `baseline_v1` 已基于需求文档、Controller/Service、鉴权与异常处理链路、实体与数据库约束完成人工证据审阅。可用下列命令从审阅前备份重复生成 1.1.0 verified 清单和本地审阅记录：

```powershell
python -m evals.ground_truth_review `
  --input evals/datasets/baseline_v1/raw/manifest.pre-review-20260820.yaml `
  --output evals/datasets/baseline_v1/manifest.yaml `
  --record evals/reports/baseline_v1/ground-truth-review-20260820.yaml
```

verified 只表示 Ground Truth 本身已经确认。正式全量报告还必须为 10 个接口分别提供完成映射的脱敏样本；缺少任一接口时，Runner 会将报告标为 `pending_input`，防止把单接口结果误当成全量指标。

正式评测前建议先审计输入文件：

```powershell
python -m evals.runner --audit-input path/to/local-eval-samples.json
```

运行评测时可以强制启用同一检查：

```powershell
python -m evals.runner `
  --dataset evals/datasets/baseline_v1/manifest.yaml `
  --input path/to/local-eval-samples.json `
  --require-redacted-input
```

该检查只拒绝明显的 Token、Cookie、Authorization、密码、DSN、原始模型输出和原始响应体等字段，不会自动改写原始文件；通过检查后仍需完成 Ground Truth 和人工映射。

## Fixture 计划审计

在正式评测前，可以对清单做一次完全离线的结构审计：

```powershell
python -m evals.runner `
  --fixture-audit evals/datasets/baseline_v1/manifest.yaml `
  --fixture-audit-output evals/reports/baseline_v1/fixture_audit.json
```

审计会统计 `local_token`、`manual_setup`、`manual_observation` 和各类 Fixture 的数量，并检查有前置条件的点是否都有计划、观察点是否声明观察要求、同一点是否重复引用 Fixture。`ready` 只表示计划结构完整，仍需在本地测试环境准备人工状态；命令不会连接数据库、Redis、鉴权服务或被测系统。

## 数据安全与当前状态

真实需求文档、业务响应、模型原始输出和密钥只允许留在本地忽略目录。`baseline_v1/manifest.yaml`、样本和报告均被 `.gitignore` 排除。

当前本地 Ground Truth 已完成 10 个接口的证据审阅，但历史 baseline 仍只是 metrics-only 汇总，缺少各接口完整的 Requirement、Test Point、Case 和 Assertion 快照。因此还需要逐接口生成、脱敏并映射新的 workflow snapshot，才能形成全量质量数字。

项目提供了一个按实际 `WorkflowRunSnapshot` 结构整理的脱敏参考文件 `evals/examples/offline_workflow_snapshot.json`。它只用于验证快照适配器；即使 manifest 已标记为 `verified`，只要快照缺少人工点位或断言映射，评测报告仍会保持 `pending_annotation`，不能被当作真实质量结果。
