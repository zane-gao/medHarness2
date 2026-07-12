---
type: synthesis
title: "工作流 4 实现规格：教育建议"
sources:
  - "[[summary-radiology-eval-system-design]]"
  - "[[summary-2026-06-06-group-meeting]]"
  - "[[radiology-eval-workflows]]"
  - "[[radiology-eval-system]]"
  - "[[radiology-eval-research-story]]"
  - "[[radiology-eval-tools]]"
  - "[[radiology-eval-modules]]"
related:
  - "[[radiology-eval-workflows]]"
  - "[[radiology-eval-system]]"
  - "[[radiology-eval-research-story]]"
  - "[[radiology-eval-tools]]"
  - "[[radiology-eval-modules]]"
filed_from_query: true
date: 2026-06-17
confidence: medium
---

# 工作流 4 实现规格：教育建议

本文档描述 `radiology-eval` CLI 中工作流 4 的设计。目标读者是实现开发者：他/她可以访问现有 `radiology-eval` 代码库（基础层、12 个工具、2 个模块、工作流 1-3），但无法访问本 wiki。本文档会对齐既有实现中的术语，并说明目标、逻辑流程、输入/输出契约、禁止事项与设计风险。

> **范围提醒：**这是一份设计规格，不是实现计划。本文档不规定目录结构、函数签名或测试用例；这些内容应由后续的 writing-plans 阶段产出。

---

## 1. 术语对齐（供开发者参考）

`radiology-eval` CLI 由三层组成。下面的术语是固定的，并且与代码库中已经存在的命名保持一致。

### 工具（12 个原子操作）

| # | 工具 | 一句话说明 |
|---|------|------------|
| 1 | Likert-Scale LLM Evaluation | LLM 从 5 个维度为报告打分（1-5 分 Likert 量表 + 每个维度的解释） |
| 2 | Entity-Relation Finding Extraction | 从报告文本中提取结构化 finding graph |
| 3 | Hierarchical Structure Check | 将报告段落分类到不同章节，并计算加权结构分数 |
| 4 | Error Hazard Evaluation | 比较两个 finding graph，并输出带 hazard 类型的错误（1-5 级 hazard level） |
| 5 | Cross-Report Graph Alignment | 将两个 finding graph 对齐为 matched / a-only / b-only / mismatched 类别 |
| 6 | Structure Difference | 比较两份报告的结构分数差异 |
| 7 | Modality Recognition | 将图像/DICOM 文件映射到标准 modality key |
| 8 | 2D/3D Report Generation (Adapter) | 通过本地或云端 AI 模型从图像生成报告 |
| 9 | Select Top K Reports/Models | 按综合加权分数对报告排序 |
| 10 | Modelwise Weighted Metrics | 跨多个模型按指标聚合结果 |
| 11 | Hazardwise Weighted Metrics | 按 hazard 权重对指标加权 |
| 12 | Statistic Calculation | 计算每个指标的 mean、std、CI |

### 模块（2 个轻量编排层）

| # | 模块 | 组合的工具 | 输入 | 输出 |
|---|------|------------|------|------|
| 1 | Single Report Evaluation | Tool 1 + Tool 2 + Tool 3 | 报告文本（+ 可选图像） | 统一 JSON：`tool1`、`tool2`、`tool3` |
| 2 | Pairwise Report Evaluation | Tool 2（×2）+ Tool 4 + Tool 5 + Tool 6 | 报告 A + 报告 B | 统一 JSON：`tool2_a`、`tool2_b`、`tool4`、`tool5`、`tool6` |

### 工作流（4 条端到端文件 I/O 管线）

| # | 工作流 | 目标 | 消费 | 产出 |
|---|--------|------|------|------|
| 1 | Single Report + AI Generation + Pairwise Comparison | 评估单份报告，并将其与 top-N AI 生成报告进行基准比较 | 1 个报告文件 + 1 个图像文件 | 该报告与 top-N AI 模型的 Module 1 + Module 2 输出 |
| 2 | Batch Radiologist Evaluation vs Models | 在同伴语境下，评估某位放射科医生的一批报告与 AI 模型的差异 | Excel：`(report_path, image_path, radiologist_id)` | 每位放射科医生的指标 + 科室排名统计 |
| 3 | Department-Level Doctor vs Model Group | 比较整个放射科医生科室与 AI 模型组 | 与工作流 2 相同的 Excel | 科室 vs 模型组的聚合指标 |
| 4 | **Suggestions for Education（评估后反馈）** | 将评估结果转化为可执行的写作改进建议 | **工作流 1 结果或工作流 2 结果（二者互斥）** | 按 finding 或按放射科医生聚合的建议 JSON |

### 分层规则

- 工具是纯函数（无文件 I/O）。模块调用工具。工作流调用模块和工具，并负责文件 I/O、缓存、批处理。
- 工作流 4 是唯一一个**不直接调用任何模块或工具**的工作流。它从磁盘读取工作流 1 或工作流 2 的 JSON，并产出一个新的 JSON。它只执行一次 LLM 调用（见第 3 节）。

---

## 2. 目标

工作流 4 用于闭合评估系统的反馈回路。在工作流 1（或工作流 2）产出数值分数后，工作流 4 将这些分数转化为面向放射科医生的**可执行写作改进建议**。

两种调用模式对应不同粒度的反馈：

- **单报告模式（`--eval-report`）**：针对一份具体报告。建议锚定到单个 finding（例如，“Finding F3 缺少 laterality 信息”）。
- **放射科医生批量模式（`--eval-radiologist`）**：针对某位放射科医生在多份报告中的整体模式。建议是一般性模式（例如，“你的 conciseness 分数比科室均值低约 1.0；建议……”）。

两种模式都产出结构化 JSON 响应。不修改任何分数。不使用缓存。不接收图像输入。

---

## 3. 输入与输出

### 调用方式

```bash
radiology-eval workflow4 --eval-report <path-to-workflow1-result.json>
radiology-eval workflow4 --eval-radiologist <path-to-workflow2-result.json>
```

每次调用必须且只能设置 `--eval-report` 或 `--eval-radiologist` 其中一个。两个参数都省略 → 拒绝。两个参数同时设置 → 拒绝。

### 输入

**`--eval-report` 模式（工作流 1 结果）：**

输入 JSON 中的必需字段：
- `report_text` — 原始报告字符串
- `tool1` — 5 个维度的 Likert 分数 + 每个维度的解释
- `tool2` — finding graph：`{finding_id → {text, location, severity, …}}`
- `tool3` — 结构分类 + 分数
- `tool4` — hazard 列表（来自 Module 2 成对比较）
- `tool5` — alignment deltas
- `tool6` — structure diff
- `ai_reports` — top-N AI 生成报告列表（来自 Tool 8 输出的措辞，并经 Tool 9 排名）

**`--eval-radiologist` 模式（工作流 2 结果）：**

输入 JSON 中的必需字段：
- `radiologist_id`
- `n_reports`
- `per_dim_score_aggregates` — 每个 Tool 1 维度的 mean、std、range
- `peer_means` — 每个 Tool 1 维度的科室均值
- `per_hazard_counts` — 每个 Tool 4 hazard 类型的计数
- `tool10`、`tool11`、`tool12` 聚合结果

### 输出

**`--eval-report` 模式输出：**

```json
{
  "mode": "eval_report",
  "status": "suggestions_generated",
  "report_summary": {
    "overall_score": <float>,
    "weakest_metric": "<metric name>",
    "weakest_score": <int 1-5>,
    "peer_gap": {"<dim>": <gap> | null}
  },
  "suggestions": [
    {
      "finding_id": "F<n>",
      "metric": "<metric name>",
      "metric_score": <int 1-5>,
      "current_text": "<quoted finding text>",
      "suggestion": "<rewrite guidance with example>",
      "reasoning": "<CoT explanation>"
    }
  ],
  "general_suggestions": [
    {
      "metric": "<metric name>",
      "issue": "<observed pattern>",
      "suggestion": "<guidance>",
      "reasoning": "<CoT explanation>"
    }
  ]
}
```

**`--eval-radiologist` 模式输出：**

```json
{
  "mode": "eval_radiologist",
  "status": "suggestions_generated",
  "radiologist_summary": {
    "radiologist_id": "<id>",
    "n_reports": <int>,
    "weakest_metrics": ["<dim1>", "<dim2>"],
    "peer_gaps": {"<dim>": <gap>}
  },
  "suggestions": [
    {
      "metric": "<metric name>",
      "pattern": "<observed across batch>",
      "peer_comparison": "<how it differs from peer mean>",
      "suggestion": "<guidance>",
      "reasoning": "<CoT explanation>"
    }
  ]
}
```

`finding_id` 只出现在 `--eval-report` 模式。`peer_gap` 在同伴数据不可用时为 `null`。

---

## 4. 逻辑流程

### 通用预检（两种模式）

1. 解析 CLI 参数，验证刚好存在一个模式参数。
2. 从磁盘加载输入 JSON（只读，不得修改源文件）。
3. 按模式验证 JSON 是否包含所有必需字段。
4. 分支进入对应模式的流程。

### `--eval-report` 模式流程

```text
输入：Workflow 1 结果 JSON
  │
  ├─ 提取：report_text, tool1_scores{5 个维度 + 解释},
  │           tool2_graph{finding_id → {text, location, severity}},
  │           tool3_structure, tool4_hazards[], tool5_alignment,
  │           tool6_structure_diff, ai_reports{按模型组织}
  │
  ├─ 计算最弱指标：
  │   - argmin(tool1_scores) 始终作为主要目标
  │   - peer-gap component：需要 W1 结果之外的额外同伴数据；
  │     如果缺失，则 peer_gap 为 null
  │
  ├─ 确定按 finding 的目标：
  │   - 所有 Completeness & Accuracy 或
  │     Terminological Accuracy 分数低于阈值的 finding node
  │   - 所有在 tool4_hazards 中被标记为 actionable type 的 finding
  │     (omission_finding, incorrect_location, incorrect_severity, false_finding)
  │
  ├─ 构建 prompt context：
  │   - report_text（完整文本）
  │   - tool2_graph（序列化为适合 prompt 的格式）
  │   - tool1_scores + 每个维度的解释
  │   - tool4_hazards（过滤到 actionable types）
  │   - tool5_alignment deltas (a_only, b_only, mismatched)
  │   - ai_reports：按 Tool 9 排名取 top-3 措辞
  │
  ├─ 单次 LLM 调用（CoT 系统提示词 + 结构化输出 schema）
  │   - temperature: 0.3
  │   - schema 校验失败时最多重试 3 次
  │
  ├─ 校验 LLM 输出：
  │   - Schema 校验（suggestion 结构、finding_id 引用）
  │   - 交叉引用校验：每个 finding_id 都必须存在于 tool2_graph
  │   - reasoning 字段存在且非空
  │
  └─ 返回 JSON 响应
```

### `--eval-radiologist` 模式流程

```text
输入：Workflow 2 结果 JSON
  │
  ├─ 提取：radiologist_id, n_reports, per_dim_score_aggregates,
  │           peer_means{5 个维度}, per_hazard_counts{tool4 types},
  │           tool10_modelwise, tool11_hazardwise, tool12_stats
  │
  ├─ 计算弱指标：
  │   - 任意满足 radiologist score < (peer_mean - 1.0) 的维度
  │   - 任意 radiologist count 超过 peer baseline 的 hazard category
  │
  ├─ 构建 prompt context：
  │   - radiologist_id, n_reports
  │   - per_dim_score_aggregates (mean, std, range)
  │   - peer_means
  │   - per_hazard_counts vs peer baseline
  │   - tool12_stats (percentile, ranking)
  │
  ├─ 单次 LLM 调用（CoT 系统提示词 + 结构化输出 schema）
  │   - temperature: 0.3
  │   - schema 校验失败时最多重试 3 次
  │
  ├─ 校验 LLM 输出：
  │   - Schema 校验
  │   - 每条建议都引用实际存在的弱指标
  │   - reasoning 字段存在
  │
  └─ 返回 JSON 响应
```

### LLM 调用规格

- **每次调用只进行一次 LLM 调用。** 不拆成“先抽取、再生成建议”的两阶段流程。
- **系统提示词中包含 CoT 指令。** 系统提示词必须要求模型在输出建议前 “think step by step”，并由 `reasoning` 字段记录 CoT 轨迹。
- **强制结构化输出 schema。** 使用函数调用 / JSON 模式。
- **模型选择：** 通过现有 `config/models.yaml` 配置。本文档不固定具体模型。
- **Temperature：** 0.3（接近确定性，但允许措辞有一定变化）。
- **重试：** schema 校验失败时最多重试 3 次。3 次失败后返回错误响应。

---

## 5. 最弱指标选择规则

混合规则：

1. **始终包含** Tool 1 中绝对分数最低的单个维度。
   - `--eval-report` 模式：来自输入 JSON 中的 tool1_scores。
   - `--eval-radiologist` 模式：来自 per_dim_score_aggregates。

2. **额外包含** 任何比分科室均值低超过 1.0 的维度（peer-gap component）。
   - `--eval-report` 模式：peer-gap 需要工作流 2 的同伴语境。如果未提供，则禁用 peer-gap component（`peer_gap` 字段为 `null`）。
   - `--eval-radiologist` 模式：始终计算 peer-gap（W2 结果中包含 peer_means）。

阈值（1.0）是配置参数，不是硬编码常量。

---

## 6. 建议输出规则

- **`--eval-report` 模式：**
  - 对 Tool 2 graph 中每个满足以下条件的 finding node 输出**按 finding 的建议**：相关指标（Completeness & Accuracy、Terminological Accuracy）低于阈值，或该 finding 在 Tool 4 hazard 列表中被标记为 actionable。
  - 对每个非 finding 级别的弱指标输出**一般建议**（Conciseness、Structure、Overall Quality，或任何无法归因到单个 finding 的弱指标）。

- **`--eval-radiologist` 模式：**
  - **只输出一般建议**，针对该放射科医生批量画像中的每个弱指标各输出一条。
  - 不输出按 finding 的建议，因为 finding 是报告级别的，不是放射科医生级别的。

每条建议都必须包含非空 `reasoning` 字段。引用 `finding_id` 的建议必须引用输入 Tool 2 graph 中实际存在的 finding。

---

## 7. 需要处理的失败模式

实现者自行决定响应格式和退出码。本列表枚举实现必须检测的失败条件：

| # | 条件 | 严重程度 |
|---|------|----------|
| 1 | 同时设置 `--eval-report` 和 `--eval-radiologist` | 拒绝 |
| 2 | 未设置任何模式参数 | 拒绝 |
| 3 | 输入文件路径无法解析 | 拒绝 |
| 4 | JSON 格式错误 / 无法解析 | 拒绝 |
| 5 | 缺少必需字段（按模式区分） | 拒绝 |
| 6 | Tool 2 graph 为空（仅 W1 模式） | 拒绝：无法输出按 finding 的建议 |
| 7 | 未检测到弱指标（所有维度均 >= 阈值） | 不是失败：返回空建议并带状态标记，由调用方决定后续处理 |
| 8 | LLM 调用暂时失败（网络、限流、超时） | 最多带退避重试 3 次。全部失败后拒绝 |
| 9 | LLM 输出 schema 无效（JSON 结构错误、缺少必需键） | 最多重试 3 次。全部失败后拒绝 |
| 10 | LLM 输出中的 `reasoning` 字段为空 | 带明确提醒重试一次。仍为空则拒绝 |
| 11 | LLM 幻觉出 `finding_id`（引用 Tool 2 graph 中不存在的 F<X>） | 带明确提醒“只能使用 graph 中的 finding_ids”重试一次。仍然存在则拒绝 |

---

## 8. 禁止事项

实现不得做以下事情：

1. **不要静默强制转换**：输入格式错误时必须显式失败，而不是产出部分结果。
2. **不要缓存结果**：每次调用都重新运行 LLM。
3. **不要调用图像 grounding VLM**：图像输入已从 API 表面移除。只有在单独设计错误检测工作流时才可重新加入（本文档范围外）。
4. **不要修改输入 JSON**：输入只读。工作流 4 不得修改源 W1 或 W2 结果文件。
5. **不要强制内部分数阈值**：何时调用工作流 4 由调用方决定。
6. **不要同时接受 W1 和 W2 输入**：它们在不同调用中互斥。
7. **不要输出泛泛的“你的报告可以更好”式建议**：每条建议都必须引用具体 `finding_id`（W1 模式）或具体弱指标（W2 模式）。
8. **不要丢弃 CoT reasoning 字段**：每条建议中的 `reasoning` 字段都是必需的。根据 Spitzer et al. 的证据，缺少 CoT 会降低建议质量。
9. **不要在代码中固定单一 LLM 模型**：模型选择属于配置问题。
10. **不要引入本文档输出 schema 未记录的顶层字段**。

---

## 9. 风险与弱点（已知限制）

这些问题来自设计本身。实现时需要了解这些限制，避免错误解读建议。

### 9.1 Schramm 级联效应（依赖输入质量）

工作流 4 基于 Tool 2 finding graph 进行推理。Tool 2 的质量受输入报告质量限制。如果报告写得很差（Schramm et al. 中非放射科医生的 completeness 为 2.27/4），finding graph 会不完整，按 finding 的建议可能引用缺失或幻觉出的节点。

**弱点：**工作流 4 没有输入质量门控；它信任上游管线。

**残余风险：**对低质量报告生成的建议不可靠。建议应标记为 provisional；这是已知限制，不是缺陷。

### 9.2 Yamagishi 偏差（LLM 偏好 LLM 输出）

工作流 4 的 prompt 包含 top-3 AI 生成报告措辞作为参考示例。LLM 可能更倾向建议采用这些措辞，而不是保留放射科医生自己的写作风格。根据 Yamagishi et al.：在风格比较中，LLM 裁判偏好 LLM 生成文本的比例为 70-99%。

**弱点：**建议可能系统性地推动放射科医生转向 LLM 风格写作，从而削弱临床报告风格的多样性。

**缓解（软约束）：**系统提示词必须明确要求**保留放射科医生的表达风格**，并将 AI 措辞视为一个可选参考，而非目标本身。效果取决于提示词工程。

**残余风险：**如果缓解失败，工作流 4 会变成一种写作同质化工具。

### 9.3 Spitzer CoT 依赖

根据 Spitzer et al.：CoT explanations 将诊断准确率提高了 12.2%（P=0.001）。本文档要求每条建议都包含 `reasoning` 字段。如果未来某次 prompt 修订删除或弱化了 CoT 指令，建议质量会在无声中下降。

**弱点：**质量绑定到一个特定的 prompt 设计选择上。

**缓解：**schema 强制要求 `reasoning` 为非空 key。硬失败模式（第 7 节第 10 项）可以捕获字段丢失。

**残余风险：**如果 LLM 在上下文压力下（长报告、复杂 finding）压缩或丢弃 reasoning，建议会退化，但不一定触发硬错误。

### 9.4 Phadke 利益相关方分歧（只优化放射科医生）

根据 Phadke et al.：放射科医生和肿瘤科医生会对同一份 AI impression 给出不同评价。工作流 4 的建议默认面向放射科医生。

**弱点：**建议可能不适合其他临床利益相关方。

**残余风险：**如果工作流 4 输出被复用于非放射科医生受众，质量会无声下降。

### 9.5 peer-gap 数据中的归因污染

工作流 4 的 `--eval-radiologist` 模式消费来自工作流 2 的 peer-gap 数据。部分医院采用 draft-then-validate 工作流，最终报告是两位放射科医生共同工作的复合结果。由于系统层面无法解决“只能拿到已验证最终报告”的归因问题，这类场景中的 peer-gap 数据会受到污染。

**弱点：**W2 模式下的 peer-gap 建议可能被作者归因噪声所偏置。

**残余风险：**这是从工作流 2 继承的数据质量边界情况，不是工作流 4 的设计缺陷。

### 9.6 CoT 轨迹可检查性 vs 泄露风险

CoT 轨迹可能暴露专有 prompt 内容、内部评分规则或敏感医院数据。`reasoning` 字段会出现在输出 JSON 中。

**弱点：**如果输出被记录日志或审计，reasoning 会成为审计轨迹的一部分。

**缓解：**沿用标准 CLI 访问控制。本文档不对 reasoning 字段做脱敏。

**残余风险：**工作流 4 输出应被视为包含模型显式推理内容，而不是已脱敏文本。

### 9.7 阈值敏感性（peer-gap 魔法数字）

混合指标规则对 peer-gap component 使用“比分科室均值低 1.0”作为阈值。这是配置参数，但当前来源没有提供经验依据。

**弱点：**建议可能过于激进（低阈值 → 建议过多、噪声大），也可能过于保守（高阈值 → 漏掉边缘问题）。

**残余风险：**阈值需要经验校准。如果没有验证（本文档范围外），该选择就是任意的。

### 9.8 缺少建议质量反馈闭环

工作流 4 只输出建议，但不衡量建议是否被采纳、是否有帮助、是否准确。

**弱点：**系统无法从放射科医生的反应中学习。

**残余风险：**工作流 4 可能持续产出无用建议，而系统无法在没有外部验证的情况下发现这一点。验证明确不在本文档范围内。

---

## 10. 范围外（延后处理）

以下内容明确不属于本文档范围：

- 验证队列设计（放射科医生 panel 规模、Likert 量表选择、评审者间一致性指标）
- “何时应该调用工作流 4”的阈值策略（由调用方决定）
- 多语言建议生成（仅单语言，默认 = 英文）
- 向放射科医生交付建议的持久化审计轨迹
- 基于图像 grounding 的错误检测（属于另一个工作流问题，可能归入 Tool 4 增强）
- 反馈收集机制（放射科医生对每条建议打分）
- 对 1.0 peer-gap 阈值的经验校准

---

## 11. 实现验收标准

当满足以下全部条件时，实现可以被接受：

1. CLI 只接受 `--eval-report` 或 `--eval-radiologist` 其中一个；对零个或两个参数都拒绝。
2. 输入 JSON 校验能捕获第 7 节中的全部 11 种失败模式。
3. LLM 调用是单次调用，temperature 为 0.3，使用结构化输出，最多重试 3 次。
4. 每条建议都有非空 `reasoning` 字段。
5. `--eval-report` 模式：建议中的每个 `finding_id` 都存在于输入 Tool 2 graph 中。
6. `--eval-radiologist` 模式：任何建议中都不得出现 `finding_id` 字段。
7. 输出 JSON schema 与第 3 节中对应模式的 schema 匹配。
8. 不使用缓存。不接收图像输入。不修改输入 JSON。
9. 失败响应是显式的，不返回静默的部分结果。
10. 实现者能解释第 9 节中的每个风险如何体现在 prompt 设计中（或接受对应残余风险）。

---

## 相关页面

- [[radiology-eval-workflows]] — 父级工作流页面（已有占位设计）
- [[radiology-eval-system]] — 系统架构枢纽
- [[radiology-eval-research-story]] — IMRD 研究叙事（工作流 4 位于“评估后教育”部分）
- [[radiology-eval-tools]] — 本规格引用的 12 个工具
- [[radiology-eval-modules]] — Module 1 和 Module 2，其输出会输入工作流 4
- [[summary-radiology-eval-system-design]] — 原始设计来源
- [[summary-2026-06-06-group-meeting]] — 引入工作流 4 的组会记录
