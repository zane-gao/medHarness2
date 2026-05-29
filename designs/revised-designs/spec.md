# 放射科报告评估系统：合并设计规格（Radiology Report Evaluation System）

> 由设计追问会整理生成。本文是实现的权威依据，替代此前所有设计文档。

---

## 1. 系统概览

基于 CLI 的放射科报告评估系统。

- **输入：** 自由文本放射科报告 + 可选医学图像/体数据
- **输出：** 定量指标 + 定性评估
- **方法：** 固定传统工具 + AI 模型生成的参考报告
- **`src/` 中的现有代码：** 已废弃。不要复用，重新实现。

---

## 2. 拆分方案

按顺序实现 5 个子项目：

| # | 子项目 | 范围 | 依赖 |
|---|-------------|-------|-------------|
| 1 | **基础层（Foundation）** | 配置、LLM 客户端、日志、CLI、布局 | 无 |
| 2 | **独立工具（Independent Tools）** | 工具 1、3、7、9、10、11、12 | 基础层 |
| 3 | **依赖工具（Dependent Tools）** | 工具 2、4、5、6 | 基础层 + 独立工具 |
| 4 | **模块（Modules）** | 模块 1、模块 2 | 基础层 + 全部工具 |
| 5 | **工作流（Workflows）** | 工作流 1、2、3 + 工具 8 | 基础层 + 全部工具 + 全部模块 |

---

## 3. 项目布局

```
radiology_report_benchmark/
  config/
    api.yaml
    models.yaml
    weights.yaml
    hazard_weights.yaml
    alignment_tolerance.yaml
    modality_map.yaml
    prompts/
      tool1_system.txt
      tool1_likert_definition.txt
      tool3_system.txt
      tool4_system.txt
      tool4_likert_definition.txt
    templates/
      chest_xray.json
      chest_ct.json
      brain_mri.json
      ...
  src/
    __init__.py
    cli.py                    # Typer 嵌套子命令
    config.py                 # Pydantic 加载器
    llm_client.py             # 统一 LLM/VLM 客户端
    utils/
      __init__.py
      logging_config.py
      file_io.py
    tools/
      __init__.py
      tool1.py                # Likert-Scale LLM Evaluation
      tool2.py                # Entity-Relation Finding Extraction
      tool3.py                # Hierarchical Structure Check
      tool4.py                # Error Hazard Evaluation
      tool5.py                # Cross-Report Graph Alignment
      tool6.py                # Structure Difference
      tool7.py                # Modality Recognition
      tool8.py                # 2D/3D Report Generation (Adapter)
      tool9.py                # Select Top K Reports/Models
      tool10.py               # Modelwise Weighted Metrics
      tool11.py               # Hazardwise Weighted Metrics
      tool12.py               # Statistic Calculation
    modules/
      __init__.py
      module1.py              # Single Report Evaluation
      module2.py              # Pairwise Report Evaluation
    workflows/
      __init__.py
      workflow1.py            # Single + AI + Pairwise
      workflow2.py            # Batch Radiologist vs Models
      workflow3.py            # Department vs Model Group
```

---

## 4. 关键设计决策

| 决策项 | 选择 |
|----------|--------|
| 配置格式 | 按领域拆分多个 YAML 文件，使用 Pydantic 校验 |
| 配置位置 | 从项目根目录使用固定相对路径 `./config/` |
| LLM 客户端 | 统一类，单一方法 `call(prompt, image_path=None)`，通过配置切换 provider |
| 重试策略 | 临时失败使用指数退避（exponential backoff） |
| 文本 vs 视觉 | 单一方法，image 参数可选 |
| CLI 框架 | Typer，使用嵌套子命令：`tool`、`module`、`workflow` |
| 工具接口 | 纯函数，不做文件 I/O。CLI 层处理 I/O |
| 输出格式 | 仅 JSON。Excel/CSV 导出作为独立可选步骤 |
| 工具 8（生成） | 适配器模式。local model 可能位于其他位置、可能不完整、也可能不存在；支持 cloud fallback |
| 指标缓存 | 模块中使用可选 path 参数。工作流使用 working directory |
| 执行方式 | 默认顺序执行，在可行处支持调整 |

---

## 5. 基础层规格

### 5.1 配置系统

**文件：** `config/api.yaml`、`config/models.yaml`、`config/weights.yaml`、`config/hazard_weights.yaml`、`config/alignment_tolerance.yaml`、`config/modality_map.yaml`

- 单目录中按领域拆分多个 YAML 文件
- 加载时使用 Pydantic schema 校验，并合并为单一 config object
- 缺失时生成默认配置
- 所有 API key 和共享配置集中管理

### 5.2 LLM/VLM 客户端

**文件：** `src/llm_client.py`

```python
def call(prompt: str, image_path: Optional[str] = None, **kwargs) -> str
```

- 通过 `api.yaml` 切换 provider（`provider: openai|anthropic|...`）
- 使用指数退避重试
- 返回原始文本；调用方负责 JSON 解析
- 工具中不直接调用 API

### 5.3 日志

- 使用标准库 `logging`
- 日志级别通过配置调整
- 每个工具和模块在关键步骤写入 `logging.debug`

### 5.4 CLI

```
radiology-eval tool <tool-name> [args]
radiology-eval module <module-name> [args]
radiology-eval workflow <workflow-name> [args]
```

---

## 6. 工具规格

### 通用工具接口原则
- 纯函数接收原始数据。工具内部不做文件 I/O。
- 所有工具使用 `llm_client.call()`。不直接调用 API。

---

### 工具 1：Likert 量表 LLM 评估（Likert-Scale LLM Evaluation）
**文件：** `src/tools/tool1.py`

- 输入：report text（str），可选 image path（str）
- 单次 LLM 调用，要求结构化输出（JSON mode / function calling）。最多 3 次重试，可配置。
- Prompts：`config/prompts/tool1_system.txt`、`config/prompts/tool1_likert_definition.txt`
- 输出：`Dict[str, Dict[str, Union[int, str]]]`
  - Key = 指标名（metric name）
  - Value = `{"score": 1-5, "explanation": str}`
- 指标：
  1. 完整性与准确性（Completeness and Accuracy）
  2. 简洁性与清晰度（Conciseness and Clarity）
  3. 术语准确性（Terminological Accuracy）
  4. 结构与风格（Structure and Style）
  5. 整体写作质量（Overall Writing Quality）
- 若没有 image：包含 `"warning": "No image/volume provided"`，并写入 warning 日志

---

### 工具 2：实体-关系病灶提取（Entity-Relation Finding Extraction）
**文件：** `src/tools/tool2.py`

- 输入：report text（str），study modality（str）
- 模板选择：按 modality key 精确匹配 -> `config/templates/{modality}.json`
- 通过 `subprocess.run` 执行外部命令。命令接收：
  - 报告文件路径（report file path，temp file）
  - 模板文件路径（template file path）
  - 输出文件路径（output file path，temp file）
- 命令写出 JSON。工具读取后返回 dict。
- 当前：使用 placeholder command。返回随机但 schema-valid 的 JSON。
- Schema：按模板 key 提取 findings，并包含 `"missing"` keys list。
- 命令字符串来自 `config/api.yaml` 下的 `extraction_command`

**阻塞项：** 向用户确认真实 command signature 和 output schema。

---

### 工具 3：层级结构检查（Hierarchical Structure Check）
**文件：** `src/tools/tool3.py`

- 输入：report text（str）
- 单次 LLM 调用，要求结构化输出
- Prompt：`config/prompts/tool3_system.txt`
- Template：`config/structure_template.json`（通用，适用于所有模态）
  - Keys：section names（Findings、Impression、Patient Information、Additional Information 等）
  - 每个 key 有 weight，用于评分计算
- LLM 将每个段落分类到一个或多个 key。一个 key 可对应多个段落。
- 输出：单个 JSON 对象
  - `classified: Dict[str, List[str]]`（缺失 section 使用空列表）
  - `score: float`（paragraphs * weight 的求和）

---

### 工具 4：错误危害评估（Error Hazard Evaluation）
**文件：** `src/tools/tool4.py`

- 输入：report A finding graph（Dict），report B finding graph（Dict）
- 单次 LLM 调用，要求结构化输出
- Prompts：`config/prompts/tool4_system.txt`、`config/prompts/tool4_likert_definition.txt`
- LLM 识别 A 相对 B（ground truth）的错误
- 输出：JSON，包含 error list
  - 每个 error：`{"error_type": str, "hazard_level": 1-5, "explanation": str}`
- 与工具 5 保持分离。不做 combined mode。

---

### 工具 5：跨报告图谱对齐（Cross-Report Graph Alignment）
**文件：** `src/tools/tool5.py`

- 输入：report A finding graph（Dict），report B finding graph（Dict）
- 匹配逻辑：
  - 定性项：精确文本匹配
  - 定量项：单位归一化后的语义匹配，并带 tolerance
    - 单位归一化（cm -> mm）
    - 使用 `config/alignment_tolerance.yaml` 中的可配置 tolerance 比较
    - 在 tolerance 内但不完全一致 -> category `"approximate_match"`
- Categories：`matched`、`a-only`、`b-only`、`mismatched`、`approximate_match`
- 指标（双向 + 对称）：
  - A 作为 ground truth 评估 B：accuracy、f1-score per finding
  - B 作为 ground truth 评估 A：accuracy、f1-score per finding
  - 对称一致性分数（Symmetric agreement score）
- ReXVal 错误：
  - `false_finding`：A 中有节点，B 中没有对齐节点
  - `omission_finding`：B 中有节点，A 中没有对齐节点
  - `incorrect_location`：节点已对齐，但位置不同
  - `incorrect_severity`：节点已对齐，但严重程度不同
  - `false_comparison` 和 `missing_comparison`：当前省略
- 输出：JSON，包含 raw matching graph + calculated metrics + symmetric score

---

### 工具 6：结构差异（Structure Difference）
**文件：** `src/tools/tool6.py`

- 输入：report A text（str），report B text（str）
- 包装工具 3：调用 `tool3(report_a)` 和 `tool3(report_b)`
- 输出：delta dict
  - Keys：模板中的 sections
  - Values：`{"score_a": float, "score_b": float, "difference": float}`

---

### 工具 7：模态识别（Modality Recognition）
**文件：** `src/tools/tool7.py`

- 输入：image/volume file path（str）
- 若为 DICOM：用 pydicom 解析 header，提取 Modality 字段
- 若为非 DICOM 或缺少 header：通过统一 client 调用 VLM
- Mapping：`config/modality_map.yaml`（raw modality -> standard key）
- 输出：映射后的 standard key（str），例如 `chest_ct`、`brain_mri`、`chest_xray`

---

### 工具 8：2D/3D 报告生成（Adapter）
**文件：** `src/tools/tool8.py`

- 输入：image/volume file path（str），study modality（str），可选 reference report（str）
- 适配器按最坏情况保持灵活：
  - Local model adapter：若可用，调用本地推理。可配置 model list 来自 `config/models.yaml`。
  - Cloud model fallback：本地不可用或失败时调用云 API。
  - 若本地模型推理代码位于其他位置，adapter 动态加载并调用。
  - 若没有本地模型，则 cloud-only。
  - 返回所有成功模型生成的报告列表。
- 每份生成报告带有 model source（local/cloud、model name）

**阻塞项：** 向用户确认本地模型位置及其暴露的接口。

---

### 工具 9：选择 Top K 报告/模型（Select Top K Reports/Models）
**文件：** `src/tools/tool9.py`

- 输入：来自 N 份报告的 metrics list（`List[Dict[str, Any]]`）
- 丢弃定性指标（free text）。保留定量指标，包括 Likert scores（1-5）。
- 对每个指标在所有报告范围内使用 min-max scaling 归一化到 [0, 1]
- 使用 `config/weights.yaml` 中的权重计算每份报告的 weighted mean
- 输出：按输入相同位置顺序返回 weighted scores list

---

### 工具 10：按模型加权指标（Modelwise Weighted Metrics）
**文件：** `src/tools/tool10.py`

- 输入：来自多个模型/报告的 metrics list
- 使用与工具 9 相同的归一化方式
- 计算所有模型的每个指标 weighted mean（保留 metrics dimension）
- 输出：每个指标的 weighted scores list

---

### 工具 11：按危害加权指标（Hazardwise Weighted Metrics）
**文件：** `src/tools/tool11.py`

- 输入：带关联 hazard scores 的 metrics list（来自工具 4）
- 若尚未归一化，则先归一化
- 将每个 metric 乘以 `config/hazard_weights.yaml` 中的 hazard weight
- Hazard weights：level（1-5）x category（false_finding、omission_finding、incorrect_location、incorrect_severity）的矩阵
- 不做维度缩减。保留所有维度。
- 输出：与输入结构相同，但包含 hazard-weighted values

---

### 工具 12：统计计算（Statistic Calculation）
**文件：** `src/tools/tool12.py`

- 输入：来自多份报告的 metrics list
- 按指标计算：mean、std、confidence interval
- 输出：每个指标一个 flat dict，可直接 JSON serialization，并便于后续绘图

---

## 7. 模块规格

### 模块 1：单报告评估（Single Report Evaluation）
**文件：** `src/modules/module1.py`

- 输入：report text（str），可选 image path（str），可选 modality（str）
- 若未提供 modality 但提供了 image：先调用工具 7
- 编排：
  1. 工具 1：Likert 量表 LLM 评估（Likert-Scale LLM Evaluation）
  2. 工具 2：实体-关系病灶提取（Entity-Relation Finding Extraction）
  3. 工具 3：层级结构检查（Hierarchical Structure Check）
- 执行：默认顺序执行，可通过参数调整为 parallel
- 聚合：按 tool name 嵌套为统一 JSON
  ```json
  {"tool1": {...}, "tool2": {...}, "tool3": {...}}
  ```
- 可选 cache path 参数。若提供，则将 JSON 保存到文件。

---

### 模块 2：成对报告评估（Pairwise Report Evaluation）
**文件：** `src/modules/module2.py`

- 输入：report A text（str），report B text（str），可选 image path（str），可选 modality（str）
- 若未提供 modality 但提供了 image：先调用工具 7
- 编排（顺序执行）：
  1. 对 report A 调用工具 2（finding graph A）
  2. 对 report B 调用工具 2（finding graph B）
  3. 工具 4：错误危害评估（graph A、graph B）
  4. 工具 5：跨报告图谱对齐（graph A、graph B）
  5. 工具 6：结构差异（report A text、report B text）
- 聚合：按 tool name 嵌套为统一 JSON
  ```json
  {"tool2_a": {...}, "tool2_b": {...}, "tool4": {...}, "tool5": {...}, "tool6": {...}}
  ```
- 可选 cache path 参数。若提供，则将 JSON 保存到文件。

---

## 8. 工作流规格

### 通用工作流原则
- 工作流负责编排模块和工具，并处理文件 I/O、批处理与缓存。
- 所有工作流使用 working directory 存放中间结果。
- 可引用模块缓存指标；缓存缺失时重新计算。

---

### 工作流 1：单报告 + AI 生成 + 成对对比（Single Report + AI Generation + Pairwise Comparison）
**文件：** `src/workflows/workflow1.py`

- 输入：human report file path，image/volume file path
- 流程：
  1. 通过工具 7 检测 modality（若需要）
  2. 对 human report 运行模块 1（缓存结果）
  3. 调用工具 8，通过所有可用模型生成 reports
  4. 对每份 generated report 运行模块 1（缓存在 working directory）
  5. 使用工具 9 按 composite score 排名 generated reports
  6. 选择 top N reports（N 可配置）
  7. 运行模块 2 成对评估：human report vs each top N report
  8. 将所有结果聚合为 nested JSON
- 输出：nested JSON，包含人工报告的模块 1 结果、Top N 模型报告及其模块 1 结果、成对模块 2 结果

---

### 工作流 2：批量放射科医生 vs 模型评估（Batch Radiologist Evaluation vs Models）
**文件：** `src/workflows/workflow2.py`

- 输入：Excel 文件，列为：report_path、image_path、radiologist_id
- 流程（顺序执行，为后续 parallel migration 预留）：
  1. 按 radiologist 分组报告
  2. 对每名 radiologist：
     a. 使用工具 8 为其所有病例生成报告
     b. 对每个病例：对医生报告和全部模型报告运行模块 1
     c. 对每个模型：对全部病例运行模块 2 成对评估（doctor vs model）
     d. 收集每个 doctor-model pair 的 per-case metrics
  3. 对每名 doctor：应用工具 10（Modelwise Weighted），按指标跨所有模型聚合
  4. 对每名 doctor：应用工具 11（Hazardwise Weighted）处理 hazard-weight metrics
  5. 对全部 doctors：应用工具 12（Statistic Calculation）生成科室级统计
- 汇总顺序：Modelwise -> Hazardwise -> Stats
- 输出：per-doctor metrics、department-level statistics、percentile rankings

---

### 工作流 3：科室级医生 vs 模型组对比（Department-Level Doctor vs Model Group Comparison）
**文件：** `src/workflows/workflow3.py`

- 输入：Excel 文件，列为：report_path、image_path、radiologist_id
- 流程：
  1. 对所有医生报告和所有模型生成报告运行模块 1
  2. 对模型：使用 weighted average（权重来自 config）计算每个病例的 representative score
  3. 对每个病例：比较 doctor score 和 model representative score
  4. 将所有统计委托给工具 12：
     - 每份报告的得分差异（Per report score difference）
     - 得分分布（Score distribution，doctor vs model）
     - 优于模型的报告数量（Number of reports better than model）
- 输出：包含统计结果的 comparison JSON

---

## 9. 实现前需要解决的阻塞项

1. **本地 AI 模型（Tool 8）：** 本地模型在哪里？使用什么 inference framework？接口是什么？询问用户。
2. **外部提取命令（Tool 2）：** 真实 command signature 是什么？输出 JSON schema 是什么？询问用户。
3. **模态模板：** 固定模板（`chest_xray.json`、`chest_ct.json` 等）由外部提供。确认来源，或为测试生成 demo templates。
4. **Prompt 内容：** 工具 1、3、4 的 system prompts 和 Likert definitions 需要编写。生成默认值后交用户 review。
5. **配置默认值：** Weights、model registry、API keys 需要合理默认值。生成默认值并标记给用户 review。
6. **DICOM 测试数据：** 需要包含已知 modality 的样例 DICOM 文件来测试工具 7。检查 `data/`。

---

## 10. 实现顺序与检查点

```
阶段 1：基础层（Foundation）
  -> 验证：可以加载 config，可以调用 LLM client（mock），CLI 显示 help

阶段 2：独立工具（Independent Tools）
  -> 验证：每个工具都能通过 CLI 独立运行，并产生 valid JSON

阶段 3：依赖工具（Dependent Tools）
  -> 验证：工具 2 产生 schema-valid random JSON，工具 4/5/6 可以接收

阶段 4：模块（Modules）
  -> 验证：模块 1 可在 test report 上运行，模块 2 可在 test pair 上运行

阶段 5：工作流（Workflows）
  -> 验证：工作流 1 可在 data/test/ 上端到端完成
```

---

## 11. Agent 派发策略（Agent Spawning Strategy）

每个子项目由单独 agent session 实现。派发时提供：
1. 该子项目的完整 spec
2. 来自基础层的项目布局和接口契约
3. 依赖列表
4. 可读写文件路径
5. 设计文档位置
6. 指令："不要使用 skills。直接实现。"
7. 指令："编码前遇到任何歧义都先向用户确认。"

| Agent | 范围 | 关键文件 |
|-------|-------|-----------|
| Agent 1 | 基础层（Foundation） | `src/config.py`、`src/llm_client.py`、`src/cli.py`、`src/utils/`、`config/` |
| Agent 2 | 独立工具（Independent Tools） | `src/tools/tool1.py`、`tool3.py`、`tool7.py`、`tool9.py`、`tool10.py`、`tool11.py`、`tool12.py` |
| Agent 3 | 依赖工具（Dependent Tools） | `src/tools/tool2.py`、`tool4.py`、`tool5.py`、`tool6.py` |
| Agent 4 | 模块（Modules） | `src/modules/module1.py`、`src/modules/module2.py` |
| Agent 5 | 工作流（Workflows） | `src/workflows/workflow1.py`、`workflow2.py`、`workflow3.py`、`src/tools/tool8.py` |
