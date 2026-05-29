# medHarness2 MVP 设计规格

> 本文是当前实现依据。`medHarness2` 是独立新系统，不覆盖 `/data/isbi/gzp/medHarness`；仅复用其中已验证的模型接入经验和 readiness 文档信息。

## 1. 目标

构建一个可复现、可扩展的放射科报告评估核心系统。

- **输入：** 人工自由文本报告、图像/体数据路径、可选 modality。
- **输出：** AI 候选报告、单报告评估、Top-N 排名、human-vs-AI 成对比较，统一 JSON。
- **产品形态：** Python library 为核心，CLI 只是最小验证入口；后续可接 Web/API 平台。
- **MVP 范围：** 只实现单病例 Workflow 1。批量医生评估、科室统计、百分位排名后置。

## 2. 核心边界

### 2.1 云端 LLM/VLM

`LLMClient` 只负责云端 API 调用：

```python
LLMClient.call(prompt: str, image_path: str | None = None, **kwargs) -> str
```

用途：

- Likert 评价。
- 结构分类。
- 错误 hazard level 和解释。
- 本地生成模型不可用时的 cloud fallback。

模型名、provider、base URL、API key 均来自配置；代码中不写死 `gpt-5.5`。

### 2.2 本地报告生成模型

`ReportGeneratorRegistry` 负责报告生成模型：

- 优先兼容 `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md` 中已就位模型。
- 只引用旧项目路径和 adapter 思路，不复制旧项目大资源。
- 每个模型声明支持的 modality/body part、调用方式、是否 fresh、是否 artifact。
- 本地模型不可用时允许 cloud fallback，并在 warnings 中标明。

## 3. MVP 流程

```text
human report + image/volume
  -> resolve modality
  -> generate AI reports
  -> evaluate human report and generated reports
  -> select Top-N generated reports
  -> pairwise compare human report vs Top-N
  -> write nested JSON
```

MVR CLI：

```bash
medharness2 workflow single-case \
  --report human.txt \
  --image image_or_volume_path \
  --output result.json
```

## 4. 项目布局

```text
medHarness2/
  config/
    default.yaml
    prompts/
      tool1_likert.txt
      tool3_structure.txt
      tool4_hazard.txt
    templates/
      default_finding_template.json
  docs/
    mvp_usage.md
  src/
    medharness2/
      __init__.py
      cli.py
      config.py
      llm_client.py
      schema.py
      utils/
        io.py
        logging.py
      generators/
        registry.py
      tools/
        tool1_likert.py
        tool2_extract.py
        tool3_structure.py
        tool4_hazard.py
        tool5_align.py
        tool7_modality.py
        tool8_generate.py
        tool9_rank.py
      modules/
        single_report.py
        pairwise_report.py
      workflows/
        single_case.py
  tests/
```

## 5. Tools

### Tool 1: Likert 评估

- 输入：report text、可选 image path。
- 调用 `LLMClient.call()`。
- 输出 5 个 1-5 分指标和解释。
- 无图像时添加 warning，不失败。

### Tool 2: Finding 提取

- 输入：report text、modality。
- MVP 默认 placeholder extractor，返回 schema-valid finding graph。
- 后续可替换为外部结构化提取命令或 CXR rule graph。
- 工具接口不绑定具体第三方命令。

### Tool 3: 结构检查

- 输入：report text。
- 优先 deterministic section parser；配置启用时可调用 LLM 分类。
- 输出 section presence、score、warnings。

### Tool 4: Hazard 解释

- 输入：Tool 5 产生的 error candidates。
- 只负责给每个错误补 hazard level 和 explanation。
- 不重复做图谱对齐。

### Tool 5: 图谱对齐

- 输入：report A graph、report B graph。
- 输出 matched、a_only、b_only、mismatched、approximate_match。
- 同时产生 error candidates：false_finding、omission_finding、incorrect_location、incorrect_severity。
- 支持 cm/mm 单位归一化和 tolerance。

### Tool 7: 模态识别 fallback

- 若 workflow 输入已提供 modality，跳过。
- 否则尝试 DICOM header。
- 仍无法识别时，可选调用 VLM。

### Tool 8: 报告生成

- 输入：image path、modality、可选 reference report、可选 model keys。
- 优先 `ReportGeneratorRegistry` 中本地/历史 artifact 模型。
- 本地模型不可用时调用 cloud fallback。
- 输出候选报告列表，包含 model、source、report、warnings。

### Tool 9: Top-N 排名

- 输入：多份报告的评估结果。
- 抽取数值指标，归一化，加权平均。
- 输出按分数排序的候选报告。

## 6. Modules

### Module 1: 单报告评估

```python
evaluate_single_report(report_text, image_path=None, modality=None) -> dict
```

编排 Tool 1、Tool 2、Tool 3，输出：

```json
{
  "likert": {},
  "finding_graph": {},
  "structure": {},
  "composite_inputs": {}
}
```

### Module 2: 成对报告评估

```python
evaluate_pairwise(report_a, report_b, image_path=None, modality=None) -> dict
```

编排 Tool 2、Tool 5、Tool 4，并输出结构差异摘要。

## 7. Workflow 1

```python
run_single_case(report_path, image_path, output_path, modality=None, top_n=3, model_keys=None) -> dict
```

步骤：

1. 读取人工报告。
2. 解析 modality；输入提供时直接使用，缺失时调用 Tool 7。
3. 调用 Tool 8 生成候选报告。
4. 对人工报告和全部候选报告运行 Module 1。
5. 调用 Tool 9 选择 Top-N。
6. 对 human vs Top-N 运行 Module 2。
7. 写出 nested JSON。

## 8. 后续版本

- Workflow 2：批量放射科医生 vs 模型。
- Workflow 3：科室级医生组 vs 模型组。
- Tool 10/11/12：模型维度加权、hazard 加权、统计计算。
- Web/API 平台。
- 真实结构化 extractor backend。
- 更多模态模板和真实外部评价器。

## 9. 验收

MVP 必须通过：

```bash
python -m compileall src tests
python -m pytest
medharness2 workflow single-case --report tests/fixtures/human_report.txt --image tests/fixtures/dummy.dcm --output outputs/mvp_result.json
```

最低成功标准：

- 输出 JSON 可解析。
- 至少包含 `human_evaluation`、`generated_reports`、`rankings`、`pairwise_comparisons`。
- mock/cloud fallback 不可用时也有明确 warning，不静默失败。
