# 临床标注、正式 OCR 与论文实验流水线设计

日期：2026-07-17

## 目标

把当前 52 例 pilot 运行产物推进为三条可复现工作线：

1. 从 52 例筛出覆盖 CXR/CT/MRI 的 10 例，生成真实医生可使用的盲化双读者标注包；
2. 建立北川冻结集上的 OCR 候选比较、双次重复、verifier 抽查和 winner 门禁；
3. 建立论文实验 manifest、结果目录和统计入口。

## 不可突破的证据边界

- 未由真实医生完成的内容只能标为 `synthetic_draft`，不得写入 formal gold 或临床结果；
- 当前 benchmark 使用北川参考报告作为文本 gold；缺少真实 provider provenance、完整病例覆盖或质量门禁时，OCR 结果只能是 `blocked/in_progress`，不得生成 winner；
- 论文结果只读取验证通过的产物；缺失产物显示 `pending/blocked`，不补零、不伪造置信区间。

## 10 例标注包

选择器读取当前 52 例 manifest 和 OCR 质量审计，按模态覆盖、质量风险、finding/hazard 多样性和来源可用性排序，输出固定的 10 例清单。每例包含源文件 hash、模态、部位、参考文本和盲化候选报告；模型身份映射单独保存，不进入医生包。

标注包保留 `reader_a`、`reader_b`、`adjudication` 三个槽位，初始状态全部为 `not_started`。包生成命令可重复执行并验证 hash；不会填入模型生成的“医生答案”。

## OCR 比较

OCR manifest 记录病例、页数、源 hash、候选 provider/model/role、重复编号和输出路径。候选至少双次；主 OCR 与 verifier 产物分离。winner 规则要求：gold 与候选均存在、所有病例覆盖、provenance 完整、质量状态为 `passed`，再按临床 CER、截断、数字 token、否定词和重复一致性排序。

## 论文实验

论文 manifest 预注册 OCR、finding extraction、generation、evaluation 四组实验，记录数据划分、输入产物、命令、指标、统计方法和状态。结果目录按实验与重复编号隔离；统计汇总只消费已通过 contract/quality/evidence gate 的结果。

## 验收

- 10 例清单可由命令重复生成，三种模态均覆盖；
- 标注包 schema 校验通过且 10/10 初始未开始；
- OCR manifest 和论文 manifest schema 校验通过；
- 所有真实证据缺口在文档和前端保持明确状态；
- 最小测试、完整回归、compileall、diff check 通过。
