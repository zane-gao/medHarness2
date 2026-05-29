# 放射科报告评估系统设计规格（Radiology Report Evaluation System）

## 概览

共 5 个子项目设计规格，已完成推敲，可进入实现。

| # | 规格 | 范围 | 依赖 |
|---|------|-------|-------------|
| 1 | [2026-05-28-foundation-design.md](plans/2026-05-28-foundation-plan.md) | 配置、LLM 客户端、日志、CLI、项目布局 | 无 |
| 2 | [2026-05-28-independent-tools-design.md](plans/2026-05-28-independent-tools-plan.md) | 工具 1、3、7、9、10、11、12 | 基础层（Foundation） |
| 3 | [2026-05-28-dependent-tools-design.md](plans/2026-05-28-dependent-tools-plan.md) | 工具 2、4、5、6 | 基础层 + 独立工具 |
| 4 | [2026-05-28-modules-design.md](plans/2026-05-28-modules-plan.md) | 模块 1、模块 2 | 基础层 + 全部工具 |
| 5 | [2026-05-28-workflows-design.md](plans/2026-05-28-workflows-plan.md) | 工作流 1、2、3 + 工具 8 | 基础层 + 全部工具 + 全部模块 |

## 实现顺序

基础层 -> 独立工具 -> 依赖工具 -> 模块 -> 工作流

每个子项目由单独 agent session 实现，避免上下文过载。

## 实现前需要解决的关键阻塞项

1. **本地 AI 模型（Tool 8）：** 询问用户本地模型在哪里，以及暴露什么接口。
2. **外部提取命令（Tool 2）：** 询问用户命令签名和输出 JSON schema。
3. **模态模板：** 向用户确认模板 JSON 文件来源。
4. **Prompt 内容：** 为工具 1、3、4 生成默认内容，但要求用户 review。
5. **配置默认值：** 生成合理默认值，但标记给用户 review。
6. **DICOM 测试数据：** 检查 `data/` 中是否有可测试工具 7 的样例 DICOM。
