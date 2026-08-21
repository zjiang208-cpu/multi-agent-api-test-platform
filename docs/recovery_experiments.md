# Multi-Agent Workflow Recovery 三轮实验记录

## 1. 评测范围

评测对象为 `Reviewer → Supplement Designer → Final Validator` 的缺陷恢复闭环。
基线包含 10 个接口，每轮包含 10 个 `recovery_mutation` 样本和 10 个
`recovery_control` 样本，共 20 个样本。

## 2. 实验结果

| 实验轮次 | 结果 | 报告指标 |
| --- | ---: | --- |
| 第一次 | 90% | `Coverage Recovery Rate` |
| 第二次 | 80% | `Supplement Target Recall` |
| 第三次 | 100% | `Coverage Recovery Rate` |

三轮实验记录结果为：90%、80%、100%。

## 3. 本地证据

- 第一次报告：`evals/reports/baseline_v1/recovery/results/recovery-evaluation.json`
- 第二次报告：`evals/reports/baseline_v1/recovery-current-20260821/results-v2/recovery-evaluation.json`
- 第三次报告：`evals/reports/baseline_v1/recovery-current-20260821/results-v3/recovery-evaluation.json`
- 10 接口基线报告：`evals/reports/baseline_v1/current-10-20260821.json`

完整历史说明和评测中间产物仅保存在本地 `evals/reports/archive-20260821/`，不纳入 GitHub
公开材料。
