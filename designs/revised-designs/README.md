# medHarness2 设计说明

当前以 `spec.md` 为权威设计稿。

实现原则：

- 先完成单病例 MVP 闭环，再扩展批量统计。
- Python library 是核心，CLI 是最小可验证入口。
- 云端 GPT/VLM API 只作为 evaluator/fallback；本地报告生成模型通过 registry/adapter 接入。
- 不复制旧 `medHarness` 的大模型资源，只引用其 readiness 文档和已验证路径。

历史分阶段计划保留在 `plans/` 中，仅作参考；实现时以当前 `spec.md` 的 MVP 范围为准。
