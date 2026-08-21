# 脱敏离线样例

这里的文件只用于验证评测框架的输入契约和指标计算链路：

- `offline_smoke_manifest.yaml`：一个完全虚构的 `demo-get-item` 接口及其三类 Ground Truth 点；
- `offline_smoke_samples.json`：一条完整样例和一条 Reviewer 重复用例 Mutation 样例。
- `offline_workflow_snapshot.json`：按项目实际 `WorkflowRunSnapshot` 结构整理的脱敏快照，转换后保持待人工映射状态。

样例中的接口路径、证据编号、Fixture Token 和请求值均为占位符，不代表真实业务接口、真实数据或真实模型输出。运行结果只能说明离线评测代码工作正常，不能作为项目的 LLM 质量数字。
