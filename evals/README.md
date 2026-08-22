# 离线评测框架

`evals/` 提供面向 NLU、Designer、Reviewer 的确定性离线评测入口。

- `models.py`：数据集、生成结果、人工映射、Mutation 和报告契约；
- `graders/`：NLU、Designer、Reviewer、Telemetry 指标；
- `mutations/`：Reviewer 缺陷注入；
- `ablation.py`：Designer / Reviewer / Supplement / Rules 变体汇总；
- `runner.py`：JSON/HTML 报告和本地 baseline 清单脚手架。
- `requirements_catalog.py`：从本地 Markdown 接口需求目录生成脱敏的 Ground Truth 候选清单，并输出编号、兼容接口和章节完整性审计。
- `ground_truth_review.py`：固化人工证据审阅决定，补齐通用参数/请求体边界和独立场景必要断言，并生成 verified 本地清单与审阅记录。
- `baseline_ground_truth.py`：维护历史基线 10 个接口的文档驱动候选点和必要断言。
- `examples/`：完全虚构的脱敏离线样例，只用于验证评测链路，不代表真实 LLM 质量结果。
- `input_audit.py`：评测输入的只读脱敏审计，不自动改写原始 workflow snapshot。
- recovery/：Reviewer → Supplement → Validator 的 Recovery 缺陷注入、结构化修复判定和输入完整性校验。
- recovery_experiment.py：汇总多轮 Recovery 报告，输出均值、波动、合并分母以及每轮/均值是否达标。

当前框架不会自动把语义相似当作正确，也不会调用 LLM-as-a-Judge。Ground Truth
和生成结果映射必须人工确认；未确认的数据集只会输出 pending 状态。

Designer 的 `Observation Coverage` 单独统计需要缓存、数据库、用户状态或多次请求观察的契约点；它表示观察点已被 Case 引用并完成映射，不代表观察证据已经执行成功。它与普通 JSON/HTTP 断言覆盖率分开，避免仅生成响应断言却被误判为完成了行为验证。

Ground Truth Point 的 `fixture_requirements` 是脱敏的前置条件计划：支持的数据库和鉴权令牌使用 `$DB_FIXTURE[...]`、`$AUTH_FIXTURE[...]`，缓存、关系数据、空表、状态转换和调用观察使用 `manual_setup` 或 `manual_observation` 标记。评测数据不写入真实 ID、名称、Token、Cookie、DSN 或模型原始输出。

可用下面的命令对 Fixture 计划做只读审计：

```powershell
python -m evals.runner `
  --fixture-audit evals/datasets/baseline_v1/manifest.yaml `
  --fixture-audit-output evals/reports/baseline_v1/fixture_audit.json
```

审计只检查清单结构，不访问任何服务；`ready` 不代表人工 Fixture 已经在测试环境中准备完成。

可以用合成样例验证完整评测链路：

```powershell
python -m evals.runner `
  --dataset evals/examples/offline_smoke_manifest.yaml `
  --input evals/examples/offline_smoke_samples.json `
  --output evals/reports/offline_smoke_report
```

该报告只验证 NLU、Designer、Reviewer Mutation 和 Telemetry 的计算过程，不能当作真实接口或模型效果报告。

接入本地 workflow snapshot 时，先执行 `--audit-input`；正式评测可加 `--require-redacted-input` 强制拦截明显敏感字段。原始 snapshot 只留在本地，不复制到 Git。
## Recovery 评测

Recovery 计划会对同一目标 Case 独立注入多种可解释缺陷：delete_case、remove_required_path_param、remove_all_assertions 和 remove_auth_header。每个操作保留一个 clean control，并为每种 Mutation 单独运行，避免把不同缺陷混在一个样本里。

运行准备命令：

    python -m evals.build_recovery_pack --input evals/reports/baseline_v1/full-generated-evaluation-fixed.json --output-root evals/reports/baseline_v1/recovery --snapshot-root <private-workflow-snapshot-root>

    python -m evals.run_multi_recovery --base-samples evals/reports/baseline_v1/recovery/bases --plan-root evals/reports/baseline_v1/recovery --snapshot-root <private-workflow-snapshot-root> --output-root evals/reports/baseline_v1/recovery/results --dry-run

正式生成结果后，用 evals.recovery_report 评分。报告在计算指标前会检查 expected operation set、operation ID、每个操作唯一 control、至少一个 Mutation，以及重复 sample / mutation ID。历史快照 ID 只能通过显式别名文件兼容，格式如下：

    operation_id_aliases:
      observed-operation-id: canonical-operation-id

多轮结果可用下面的入口汇总；正式实验可传入五轮或更多轮报告：

    python -m evals.recovery_experiment `
      --report <run-1/recovery-evaluation.json> `
      --report <run-2/recovery-evaluation.json> `
      --report <run-3/recovery-evaluation.json> `
      --report <run-4/recovery-evaluation.json> `
      --report <run-5/recovery-evaluation.json> `
      --threshold 0.90 `
      --output <recovery-experiment-summary.json>

汇总中的 coverage_recovery_rate 对应单轮报告的 recovery_rate，按 Ground Truth Test Point 做 micro 统计；同时保留 defect_recovery_rate，用于检查缺失参数、断言或鉴权头是否真的恢复，而不是只看测试点数量回来。all_runs_meet_threshold 表示每一轮都达到 90%，mean_meets_threshold 只表示多轮均值达到 90%，两者含义不同。
