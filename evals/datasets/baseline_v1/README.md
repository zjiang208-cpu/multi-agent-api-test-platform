# Baseline v1 离线评测数据集

这里保存评测数据的结构说明和模板，不保存真实业务需求、响应、模型原始输出或密钥。

## 建议流程

先从外部接口需求文档生成候选目录，示例命令如下。该命令只读取 Markdown，输出内容为接口元数据和待人工确认的候选 Test Point，不复制需求正文：

```powershell
python -m evals.requirements_catalog `
  --source "path/to/hm-dianping/docs/api" `
  --output evals/datasets/baseline_v1/requirements_catalog.yaml
```

生成目录中的 `audit.issues` 用于收口重复编号、旧兼容接口和文档结构不一致问题。候选目录保持 `draft`，不能直接作为已验证 Ground Truth。

当前已确认的目录口径：`USER-007` 保留给查询用户详细资料，注销当前账户规范为 `USER-009`；`USER-001/002` 暂不纳入当前评测范围；图片删除接口以 DELETE 为推荐接口，GET 作为兼容接口保留。

1. 使用本地保留的历史指标和需求目录生成待标注清单：

   ```powershell
   python -m evals.runner `
     --scaffold-from-baseline evals/datasets/baseline_v1/sources/baseline_fresh_metrics_20260817_020506.json `
     --catalog evals/datasets/baseline_v1/requirements_catalog.yaml `
     --manifest-output evals/datasets/baseline_v1/manifest.yaml
   ```

   审阅前清单覆盖历史基线的10个接口，共有73个候选 Test Point。人工证据审阅补充参数缺失、类型不匹配和请求体解析边界，并校订场景断言后，当前 1.1.0 清单包含83个 Test Point、155条必要断言；其中54个是响应断言点，29个是观察点。

2. 人工逐接口补充核心 Ground Truth Test Point，并将对应 operation 的
   `annotation_status` 改为 `verified`。当前本地清单已完成该步骤；校订逻辑位于 `evals.ground_truth_review`，审阅记录写入 Git 忽略的报告目录。
3. 为每个生成的 Test Point 填写 `point_matches`，为需要验证的关键断言填写
   `assertion_matches`。
4. 只有所有 operation 都完成标注后，才把 manifest 的
   `annotation_status` 改为 `verified`。
5. 输入脱敏后的 workflow snapshot 或 EvalSample JSON，运行：

   ```powershell
   python -m evals.runner `
     --dataset evals/datasets/baseline_v1/manifest.yaml `
     --input path/to/local-eval-samples.json `
     --output evals/reports/baseline_v1
   ```

   如果输入来自项目实际的 `WorkflowRunSnapshot`，可以先参考 `evals/examples/offline_workflow_snapshot.json` 的结构，并先运行脱敏审计：

   ```powershell
   python -m evals.runner --audit-input path/to/workflow-snapshot.json
   ```

   确认通过后，正式评测命令增加 `--require-redacted-input`。快照未完成人工 `point_matches` 和 `assertion_matches` 时，报告必须保持 `pending_annotation`。

未完成标注时，评测报告会保持 `pending_annotation`；Ground Truth 已确认但缺少任一接口样本时，报告保持 `pending_input`，不会生成虚构的全量质量结论。

## 当前 get-shop 修正版样本

`manifest.yaml` 已保留当前 `get-shop` Ground Truth，包含正向完整响应字段、ID 为 0 和负数、ID 为 1 下界、非数字 ID 观察点、商铺不存在及缓存观察点。全量清单现已完成证据审阅并标记为 `verified`；原 get-shop Pilot 仍用于单接口历史结果复现。

当前修正版脱敏样本位于 `samples/get-shop-id-current-fixed-redacted.json`，记录的提示词版本为 `nlu:1.5.8|designer:1.5.8|reviewer:1.3.8`。样本不包含真实响应、模型原始输出、项目标识或密钥；非数字 ID 只保留“实际状态和响应待确认”的观察语义。

修复前的 `nlu:1.5.7 / designer:1.5.7 / reviewer:1.3.7` 只登记在 `snapshot_lineage.yaml` 中，作为历史变体，不参与当前质量评分。Reviewer 的四类缺陷注入计划位于 `reviewer_mutation_plan.yaml`，分别验证覆盖缺口、缺失必填 path 参数的不可执行请求、重复用例和执行器不支持的断言路径；它只描述待生成的 Mutation，不代表 Reviewer 已经发现这些缺陷。

生成 Reviewer 待审输入包：

```powershell
python -m evals.mutations.build_pack `
  --input evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --plan evals/datasets/baseline_v1/reviewer_mutation_plan.yaml `
  --output evals/datasets/baseline_v1/samples/get-shop-id-reviewer-mutations-redacted.json
```

该命令只生成四个变异输入，`reviewer_output` 保持为空。先使用真实私有快照做离线 dry-run：

```powershell
python -m evals.reviewer_runner `
  --snapshot backend/.data/projects/<project-id>/artifacts/workflow-runs/<workflow-id>.yaml `
  --base-sample evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --plan evals/datasets/baseline_v1/reviewer_mutation_plan.yaml `
  --data-dir backend/.data `
  --dry-run
```

验证通过后，在已设置 `DEEPSEEK_API_KEY` 的同一终端去掉 `--dry-run`，并增加：

```powershell
--output evals/datasets/baseline_v1/samples/get-shop-id-reviewer-results-redacted.json
```

执行器直接复用生产 Reviewer，但不启动或停止平台服务。结果只保留结构化结论和 Reviewer Telemetry，并在写入本地 Git 忽略目录前完成脱敏审计。

正式计算时还应加入一份未变异对照组，评测器会先扣除对照组已有发现，再聚合 4 个 Mutation 的
缺陷召回率、微平均精确率和误报率。Reviewer 汇总可以独立为 `ready`；即使 manifest 已 `verified`，
缺少其他接口样本时全量报告仍显示 `pending_input`，不能据此声称 NLU/Designer 的全量质量已经完成评测。

在项目根目录运行下面的命令即可复核本次输入审计和待标注报告：

```powershell
python -m evals.runner `
  --dataset evals/datasets/baseline_v1/pilots/get-shop-id-verified.yaml `
  --input evals/datasets/baseline_v1/samples/get-shop-id-current-fixed-redacted.json `
  --output evals/reports/get-shop-id-current-fixed `
  --require-redacted-input
```

该命令只复核 get-shop verified Pilot。全量报告必须为10个接口全部提供完成 Test Point 与断言映射的样本；缺少接口时状态为 `pending_input`。

## 标注原则

- 标注 Test Point，不标注唯一“标准 Case”。
- 每个 Ground Truth Point 应说明类别、业务意图和必要断言。
- NLU 的 Precision 需要为每个生成点标记是否有证据支持。
- Reviewer 评测使用 `evals.mutations` 生成已知缺陷，不使用 Reviewer 自评。
