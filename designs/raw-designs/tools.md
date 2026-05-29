# 多 AI 模型放射科报告评估（Radiology Report Evaluation with Multiple AI Models）
本文说明模块和工作流会使用的工具。

# 工具
## 工具 1：Likert 量表 LLM 评估（Likert-Scale LLM Evaluation）
描述：使用 LLM 或 VLM 模拟放射科医生基于 Likert 量表评估人工/模型撰写的放射科报告。

输入：
- 输入自由文本报告（单文件，用于评估）
- 输入医学图像/体数据（单文件，与输入报告对应，可选）

逻辑：
- 向 LLM 或 VLM 提供上下文
    - system/instruction-prompt
    - report-to-eval
    - Likert-scale-table-definition
    - image/volume（仅 VLM 支持视觉输入时使用，纯文本 LLM 跳过）
- LLM 或 VLM 返回每个指标的结果
    - 1 到 5 的 Likert 量表评分
    - 评估解释（free-text）
- 以 JSON 格式返回

规格：
- 只通过云 API 调用 LLM 或 VLM
- system/instruction-prompt 和 Likert-scale-table-definition 预定义在独立 `.txt` 文件中
- Likert 量表指标：
    - 完整性与准确性（Completeness and Accuracy）
        - 1（Poor）：主要发现缺失或错误。
        - 2（Fair）：多项发现缺失，或存在明显不准确。
        - 3（Good）：大多数关键发现存在且准确，仅有少量遗漏或错误。
        - 4（Very Good）：报告全面且准确，仅有轻微遗漏。
        - 5（Excellent）：报告各方面完整且正确。
    - 简洁性与清晰度（Conciseness and Clarity）
        - 1（Poor）：报告冗长、混乱且表达不直接。
        - 2（Fair）：报告难以理解，包含不必要信息。
        - 3（Good）：整体清楚，且较为简洁。
        - 4（Very Good）：清晰、直接、书写良好。
        - 5（Excellent）：非常简短、直接、易懂。
    - 术语准确性（Terminological Accuracy）
        - 1（Poor）：医学术语存在频繁且严重错误。
        - 2（Fair）：术语存在多处明显错误。
        - 3（Good）：术语基本正确，仅有少量小错误。
        - 4（Very Good）：术语准确，只有罕见且无关紧要的错误。
        - 5（Excellent）：所有医学术语使用精确且正确。
    - 结构与风格（Structure and Style）
        - 1（Poor）：缺少逻辑结构，且不符合放射科报告风格。
        - 2（Fair）：结构较差，明显偏离标准风格。
        - 3（Good）：具备基本结构和风格，但组织仍可改进。
        - 4（Very Good）：结构良好，较好遵循放射科报告规范。
        - 5（Excellent）：结构示范性强，符合专业放射科写作风格。
    - 整体写作质量（Overall Writing Quality）
        - 1（Poor）：需要完全重写。
        - 2（Fair）：需要大幅修改以提升清晰度和正确性。
        - 3（Good）：可接受，但适合中等幅度修订。
        - 4（Very Good）：写作良好，只需少量校对或编辑。
        - 5（Excellent）：无需修改。
- 对缺少 image/volume 配对的输入，也返回 `"warning"` key，提醒缺少图像/体数据配对。


<!-- TODO: 适配 ZXF 工作 -->
## 工具 2：实体-关系病灶提取（Entity-Relation Finding Extraction）
描述：使用固定提取模板，从自由文本报告中提取关键放射学发现、诊断及其相关信息。

输入：
- 输入自由文本报告（单文件）
- 检查模态（Study modality，str）

逻辑：
- 运行 `<PLACEHOLDER>` 命令并输入：
    - 自由文本报告路径
    - 从匹配模态中选出的固定模板（只做精确匹配，按模板文件名做简单搜索）
    示例：`/Users/kasidit/Documents/tsinghua/Research/radiology_report_benchmark/data/structural_report_examples/ours_flat.json`
- 该命令应写出一个 JSON 文件，内容包括提取出的关键发现及其信息
示例：`/Users/kasidit/Documents/tsinghua/Research/radiology_report_benchmark/data/structural_report_examples/2026-01-29_00-55_ours_flat_filled.json`
备注：当前先忽略 `<PLACEHOLDER>` 命令，只参考模板和预期输出。

规格：
- 每种检查模态使用独立 JSON 文件保存固定模板，按名称区分，例如 `chest_xray.json`、`chest_ct.json`、`brain_mri.json`
- 该工具也需要 LLM API 调用，但会使用单独的第三方函数（third party function），由该函数内部处理流程；因此本工具只负责向第三方函数传入正确的输入、模板和输出路径。
- 第三方函数通过终端命令执行，需要为此预留实现。

备注：固定模板会由外部提供，生产环境不需要编码/生成模板；仅允许为测试生成 demo 模板。当前可以先返回随机结果。


## 工具 3：层级结构检查（Hierarchical Structure Check）
描述：使用 LLM 从自由文本报告中提取书写结构信息。

输入：
- 输入自由文本报告（单文件）

逻辑：
- 向 LLM 提供上下文
    - system/instruction-prompt
    - report-to-eval
    - fixed structure template
- LLM 返回：
    - 裁剪段落，并将其分类到固定模板中的对应类别
    - 以 JSON 文件返回 -> `Dict[str, List[str]]`（不存在的类别返回空列表）
- 根据固定模板中的权重计算加权分数；
例如 `[finding]*[weight1] + [impression]*[weight2] + ... = [final-score]`
- 返回 LLM 分类文本和 final-score，格式为单个 JSON 对象

规格：
- Fixed structure template 是适用于所有模态的通用模板，包含 2 类信息
    - 分类 key：`Findings`、`Impression`、`Patient Information`、`Additional Information` 等
    - 每个 key 的 weight：用于最终评分计算
    备注：按合理方式生成该模板，但需放在独立 JSON 文件中。
- 只通过云 API 调用 LLM
- system/instruction-prompt 预定义在 `.txt` 文件中


## 工具 4：错误危害评估（Error Hazard Evaluation）
描述：使用 LLM 评估错误，并为每个错误给出危害级别。

输入：
- `A` report finding graph（来自工具 2）
- `B` report finding graph（来自工具 2）

逻辑：
- 向 LLM 提供上下文：
    - system/instruction-prompt
    - `A` report finding graph（作为待评估目标）
    - `B` report finding graph（作为 ground truth）
    - Likert-scale-table-definition
- LLM 返回 JSON：
    - 每个错误对应 1 到 5 的 Likert 量表评分
    - 每个错误的评估解释（free-text）

规格：
- system/instruction-prompt 和 Likert-scale-table-definition 存放在外部独立文件中
- LLM 只使用云 API
- 该工具可以与工具 5 协同使用，以降低 LLM 任务复杂度


## 工具 5：跨报告图谱对齐（Cross-Report Graph Alignment）
描述：匹配两份不同报告中的 finding graph。

输入：
- `A` report finding graph（来自工具 2）
- `B` report finding graph（来自工具 2）

逻辑：
- 将两份报告的 finding graph 匹配为：
    [matched]：两份报告中均存在且匹配的 key
    [a-only] 或 [b-only]：只存在于一份报告中，另一份报告为 NotAssessed 或不存在的 key
    [mismatched]：两份报告中均存在但不匹配的 key
- 按以下条件计算指标：
    - 以 `A` report 作为 ground truth，评估 `B` report
    - 以 `B` report 作为 ground truth，评估 `A` report
- 用于计算的指标：
    - 分类指标，例如 accuracy、f1-score
    - ReXVal 错误：
        | 类别 | 图谱操作 |
        |----------|----------------|
        | false_finding | A 中存在节点，B 中没有对齐节点 |
        | omission_finding | B 中存在节点，A 中没有对齐节点 |
        | incorrect_location | 节点已对齐，但位置不同 |
        | incorrect_severity | 节点已对齐，但严重程度不同 |
        | false_comparison | A 中存在 comparison relation，B 中不存在 |
        | missing_comparison | B 中存在 comparison relation，A 中不存在 |
        备注：当前计划省略 `false_comparison` 和 `missing_comparison`，因为它们与当前工作不兼容。
- 返回 JSON，包含原始匹配图谱和计算出的指标

规格：
- `matched` 一词在这里比较模糊，因为提取出的 finding 可能是定性或定量的；定性项（例如文本）使用精确匹配，定量项（例如数字、测量值）需要设计匹配逻辑。


## 工具 6：结构差异（Structure Difference）
描述：

输入：
- `A` 自由文本报告
- `B` 自由文本报告

逻辑：
- 使用工具 3：层级结构检查（Hierarchical Structure Check）分别评估两份报告的结构
- 比较两份报告的结构分数

规格：
- 无


## 工具 7：模态识别（Modality Recognition）
描述：检测输入图像/体数据的模态。

输入：
- 输入图像/体数据（单文件，dicom、png、jpeg 等，多数为 dicom）

逻辑：
- 从 dicom header 检测模态
- 若提供的是非 dicom 文件，或 dicom header 中没有模态信息，则使用 VLM 检测模态
- 将模态名映射到工作流定义的标准 key

规格：
- 标准 key 定义在独立文件中
- VLM 只使用云 API


## 工具 8：2D/3D 报告生成（2D/3D Report Generation）
描述：用 AI 模型从输入图像/体数据生成报告，可选结合输入报告。

输入：
- 输入图像/体数据（单文件）
- 检查模态（study modality）
- 输入自由文本报告（单文件，可选）

逻辑：
- 使用所有本地 AI 模型和部分云 API 模型生成放射科报告
- 本地 AI 模型仅在模态兼容时使用，不兼容的模型跳过

规格：
- 需要调研本地 AI 模型的现有实现方式，并尽量设计成灵活适配
- 若要实现该工具，必须先询问用户本地 AI 模型推理代码在哪里，或这些本地模型应如何使用


## 工具 9：选择 Top K 报告/模型（Select Top K Reports/Models）
描述：从已有指标中选择排名靠前的 `K` 个模型/报告。
-> 为每个模型/报告得到单一统一分数（合并所有指标维度，保留模型/报告维度）

输入：
- 来自 `N` 份报告的指标列表（来自模块 1、模块 2 或二者）

逻辑：
- 将所有定量指标归一化到 [0,1]，丢弃所有定性指标
- 计算 `N` 份报告的所有指标加权均值（按报告/模型）
- 按相同位置顺序返回所有加权分数

规格：
- 注意与其他工具和工作流的集成方式
- 每个指标的权重保存在某种外部文件中；当前先生成默认权重


## 工具 10：按模型加权指标（Modelwise Weighted metrics）
描述：从多个模型指标中计算单一代表值。
-> 为每个指标得到单一统一分数（合并所有模型维度，保留指标维度）

输入：
- 多份报告的指标列表（来自模块 1、模块 2 或二者）

逻辑：
- 将所有定量指标归一化到 [0,1]，丢弃所有定性指标
- 计算所有模型/报告的加权均值（按指标）
- 按相同位置顺序返回所有加权分数

规格：
- 每个模型的权重保存在某种外部文件中；当前先生成默认权重


## 工具 11：按危害加权指标（Hazardwise Weighted metrics）
描述：计算所有指标的危害加权分数。
-> 仅用 hazard weight 乘以所有指标，不做维度缩减

输入：
- 多份报告的指标列表（来自模块 1、模块 2 或二者）

逻辑：
- 所有指标应已通过工具 4 评估，并已有 hazard score
- 将 hazard weight 乘到指标上（保留所有维度）
- 仅应用于所有定量指标；若尚未归一化则先归一化
- 返回与输入列表相同的结构

规格：
- 每个 hazard level 的权重保存在某种外部文件中；当前先生成默认权重


## 工具 12：统计计算（Statistic Calculation）
描述：基于给定指标列表执行标准统计计算。

输入：
- 多份报告的指标列表（来自模块 1、模块 2 或二者）

逻辑：
- 计算给定指标的 mean、std、ci 等

规格：
- 输出应便于后续绘制 scatter plot 等图表
