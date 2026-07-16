# medHarness2 实现细节文档：工具实现 + Workflow 结果落点

> 本文基于 `src/medharness2/` 实际源码逐一核对（不是设计稿转述），用于回答两个问题：
> **① 每个工具具体是怎么实现的；② 每个 workflow 的最终结果写在哪里。**
> 配套：可视化概览见 `web/index.html`，讲稿见 `web/demo_talk_script.md`，设计稿见 `designs/`，
> 设计→实现审计见 `docs/design_implementation_audit_20260606.md`。

---

## 0. 总览：分层与调用关系

```
Workflow (端到端 + 文件 I/O)
  └─ Module (纯编排，无文件 I/O)
       └─ Tool (原子能力，纯函数)
            └─ 基础设施 (LLMClient / registry / io / config)
```

| 层 | 文件 | 是否写文件 |
| --- | --- | --- |
| 工具 Tool 1–12 + quality_gate | `src/medharness2/tools/*.py` | 否（纯函数，返回 dict/list） |
| 模块 Module 1/2 | `src/medharness2/modules/*.py` | 否 |
| 工作流 Workflow 1/2/3 + merge/analyze | `src/medharness2/workflows/*.py` | **是**（统一经 `utils/io.write_json`） |
| 产物生成入口 catalog/experiments/figures/dashboard/registry | `catalog.py`、`figures.py`、`dashboard.py`、`run_registry.py` | **是**（生成 JSON / SVG / HTML / run_registry） |
| 统一写盘 | `src/medharness2/utils/io.py` → `write_json()` | `json.dumps(ensure_ascii=False, indent=2)` |

关键事实：**Tool/Module 层不落盘**，workflow 和产物生成入口负责写文件。所有 JSON 都是 UTF-8、缩进 2、保留中文。

---

## 1. 工具实现细节（Tool 1–12 + 质量门控）

> 每个工具给出：源文件 · 入口签名 · 实现方式 · 输出结构 · MVP 边界。

### Tool 1 · Likert 量表评估 — `tools/tool1_likert.py`

- **入口**：`evaluate_likert(..., max_retries=1, model_role="", judge_options=None, require_llm=False, allow_fallback=True) -> dict`
- **正式实现**：按固定 rubric 真实调用角色 LLM；五个维度必须全部存在，每项必须是 1–5 整数且有非空 evidence-based explanation。无图像时 prompt 明确禁止声称 image-grounded accuracy。
- **失败语义**：JSON/字段/分数/解释不合法会把错误反馈给下一次 schema retry；`require_llm=True` 拒绝 mock，`allow_fallback=False` 在重试耗尽后抛 `LLMClientError`。
- **兼容路径**：未配置正式角色时仍可使用 mock 或显式 deterministic fallback，但 `_metadata.backend/fallback_used/provider/model/role/attempt_count` 会如实标记，不能冒充正式结果。
- **5 个固定维度**：`Completeness and Accuracy / Conciseness and Clarity / Terminological Accuracy / Structure and Style / Overall Writing Quality`。
- **输出**：`{维度: {score:int1-5, explanation:str}, _metadata, [warning]}`；辅助函数 `likert_mean()` 忽略元数据并计算 composite 输入。
- **路由**：Module 1 发现 `model_roles.general_judge` 后自动启用 strict/no-fallback；当前 DMX 强候选是 `gpt-5.6-terra`。

### Tool 2 · 实体-关系病灶提取 — `tools/tool2_extract.py`

- **入口**：`extract_findings(..., llm_client=None, extractor_options=None, model_role="", max_retries=1, require_llm=False, allow_fallback=True) -> dict`
- **模板候选**：`ExtractorRegistry` 先按 modality 选择 CXR/CT/MRI 中英规则插件，抽取 observation、anatomy、laterality、negation/certainty、severity、measurement、source span；未知模态才使用显式 placeholder。
- **LLM 校正**：配置 `finding_extractor` 后，将规则图作为 fallible candidate 交给强模型返回完整最终 finding 列表。LLM 可保留、修改、添加或删除候选，但每项必须提供原报告中的连续 evidence quote。
- **确定性防线**：代码定位 evidence/source span，验证测量值确实出现在 evidence、laterality 与 location 不冲突、relation index 有效，再构造 IDs/nodes/provenance，最后由 Pydantic `FindingGraph` 统一验证。
- **输出**：成功时 `backend=template_llm`；每个 finding 的 extractor 标为 `template_llm_correction`，`metadata.llm_correction` 记录 candidate backend、provider/model/role/attempt/error/fallback。兼容回退会保留模板图并添加 `llm_extraction_fallback` warning。
- **正式语义**：Module 1/2 仅在配置 `finding_extractor` 时调用 LLM，并自动启用 strict/no-fallback；未配置时保留确定性插件行为。

### Tool 3 · 层级结构检查 — `tools/tool3_structure.py`

- **入口**：`check_structure(report_text) -> dict`
- **实现**：纯 deterministic，无 LLM。
  - `split_sections` 用同一 alias 表解析中英文 `findings/impression/clinical_history/other`，包括 `检查所见/影像所见/所见/诊断意见/印象/结论/临床资料/病史`；重复 section 按源顺序拼接，不再覆盖。
  - `section_order` 与 Tool 6 共享同一 parser；无任何 header 时整段仍算 findings。
  - 按固定权重 `findings 0.55 / impression 0.35 / clinical_history 0.10` 算加权分（段存在=1）。
- **输出**：`{sections{}, section_scores{}, score, warnings[]}`；缺 findings/impression 各加一条 warning（`missing_impression_section` 在真实样本里很常见，因为很多 OCR 报告只有 findings）。

### Tool 4 · 错误危害评估 — `tools/tool4_hazard.py`

- **入口**：`evaluate_hazards(..., require_llm=False, allow_fallback=True) -> HazardResult`；独立复核入口为 `review_hazards(primary_result, error_candidates, ...) -> HazardReviewArtifact`。
- **模板 + 主 LLM**：`DEFAULT_HAZARD` 作为可见的 deterministic prior；主模型必须独立输出 1–5 level、短理由、处置建议、confidence、abstain 和对应 evidence ID。正式模式严格检查数量、顺序、error type、枚举与范围。
- **最小化输入**：judge 仅接收 error type 与 observation/location/severity/measurement/certainty、evidence ID、模板先验；报告原文、路径和嵌套 source text 不发送。LLM 结果再与本地完整 error candidate 合并。
- **独立 reviewer**：reviewer 不读取主答案，只读取同一份结构化 evidence。输出保存 reviewer `HazardResult`、主结果 SHA-256、agreement summary 和逐项 disagreement；`primary_preserved=true`，无医生 adjudication 时不覆盖主分数。
- **模型路由**：DMX 主候选 `gpt-5.6-terra`，独立 reviewer `claude-opus-4-8`；后者使用 `omit_temperature=true`。正式角色失败直接报错，兼容路径的 deterministic fallback 仍显式标记。
- **边界**：真实 API 合成 smoke 已完成，但尚无医生 hazard gold labels，也未对 52 例运行本轮角色，不能声称临床有效性。

### Tool 5 · 跨报告图谱对齐 — `tools/tool5_align.py`

- **入口**：确定性主结果 `align_graphs(...) -> dict`；LLM 审计 `audit_alignment(candidate_graph, reference_graph, alignment_result, ...) -> AlignmentAuditArtifact`。
- **主实现**：以 observation 为 eligibility，用 Hungarian algorithm 做全局最大权重一对一匹配，不再使用贪心；pair score 同时考虑 anatomy/location、laterality、certainty、severity 和 measurement。每对匹配项再做严格属性比较：
  - 测量值经 `normalize_measurement_mm` 统一成 mm，差值 ≤ tolerance 视为匹配，仅数值不同记 `approximate_match`。
  - 分类：`matched / approximate_match / mismatched / candidate_only(a_only) / reference_only(b_only)`。
  - 同步产出 **ReXVal 错误候选**：candidate 无对应 → `false_finding`；reference 漏 → `omission_finding`；位置/严重度/测量不符 → `incorrect_location / incorrect_severity / mismatched_finding`。
- **LLM 审计**：只发送最小化 finding 属性、确定性配对类别和 error index；LLM 可报告 missed/incorrect match、错误类型问题等，但不能重写 alignment。所有引用 ID/index 均由代码校验。
- **输出**：主结果为五类分桶 + detection/strict metrics + `error_candidates[]`；审计产物包含 alignment SHA-256、verdict、issues、provenance、`primary_preserved=true` 和 adjudication 标志。
- **方向约定**：在 Module 2 里以 **candidate 对齐 human/reference**，使 false/omission 符合 AI-vs-human 直觉（见模块 2 注释）。

### Tool 6 · 结构差异 — `tools/tool6_structure_diff.py`

- **入口**：确定性主结果 `compare_structure(report_a, report_b) -> dict`；临床研判 `assess_structure_clinical_significance(...)-> StructureAuditArtifact`。
- **确定性实现**：复用 Tool 3 的同一中英文 parser，输出 section presence、字符/词数、顺序 index、ordering equality、weighted score 与 delta；`metric_version=tool6-structure-v2`。
- **LLM 研判**：读取两份 section 内容和确定性差异，评估缺段、顺序、内容放置、冗余、Findings/Impression 一致性是否影响临床沟通；输出 clinical impact 1–5、verdict、confidence、结构化 issues 与建议。
- **不可变性**：产物保存 structure diff SHA-256 和 `primary_preserved=true`；LLM 不能改写确定性指标。Module 2 已删除旧内联实现并统一调用 Tool 6。

### Tool 7 · 模态识别 — `tools/tool7_modality.py`

- **入口**：`recognize_modality(image_path, config=None, llm_client=None) -> str`
- **实现**：优先级 **DICOM header → 文件后缀 → VLM**。
  - `_detect_dicom_modality` 用 `pydicom.dcmread(stop_before_pixels=True)` 读 `Modality` 标签；读到就经 `config.modality_map` 映射成标准 key。
  - `.png/.jpg/.jpeg` → `xray`；都不行且给了 llm_client 才调 VLM 取首词；否则 `unknown`。
- **注**：在 workflow 里 manifest 已带 modality 时**直接用、跳过本工具**（见 single_case `modality or recognize_modality(...)`）。

### Tool 8 · 2D/3D 报告生成 — `tools/tool8_generate.py`

- **入口**：`generate_reports(image_path, modality, reference_report=None, model_keys=None, model_sources=None, body_part=None, fallback_image_path=None, ...) -> list[GeneratedReport]`
- **实现**：本地优先 + 显式 fallback
  1. `ReportGeneratorRegistry.select(modality, requested, body_part, sources)` 按模态/部位/来源筛本地模型 entry。
  2. 逐 entry `registry.generate(...)`；有文本就收，没文本记 `failed_attempts`。
  3. **本地全失败且 `cloud_fallback_enabled`** 时，调 `LLMClient.call` 走 fallback，来源由 `_fallback_source(provider)` 显式标成 `cloud_fallback / local_vlm_fallback / mock_fallback / llm_fallback`，并附 `no_compatible_local_generator` 等 warning。
  4. 连 fallback 都没有 → 返回一个 `source="none"` + `no_generation_backend_available` 的占位，**绝不静默成功**。
- **输出**：`list[GeneratedReport]`（dataclass：`model, source, report, modality, warnings[], metadata{}`）。
- **来源体系**（registry）：`medharness_cli`（本地 fresh 推理）/ `artifact_reuse`（历史产物）/ `local_vlm_fallback`（本地 VLM）/ 云端。`GeneratorEntry` 带 `report_trained`、`fresh_inference` 标志。

### Tool 9 · Top-N 排名 — `tools/tool9_rank.py`

- **入口**：`select_top_k(evaluations, weights=None, top_k=3) -> list`
- **并列/不确定性门禁**：Top-N cutoff 差值不超过 `near_cutoff_tolerance=0.01` 的候选会一并保留，并标记 `near_cutoff`。若候选提供总分 CI（`score_ci_lower/score_ci_upper` 或 `ci_lower/ci_upper`，必须已是 0–1）或提供全部排名指标的 CI，则会计算保守加权区间；其中 `likert_mean` 的 1–5 CI 会先按 `(x-1)/4` 归一化。与 cutoff 区间重叠的候选额外标记 `uncertainty_overlap` 与 `requires_review`，不把点估计差异误写成确定赢家。缺少或量纲非法的 CI 时不伪造不确定性。
- **实现**：取每份评估的 `composite_inputs`（likert_mean/structure_score/finding_coverage），`_numeric_metrics` 归一化到 [0,1]（1–5 Likert 使用 `(x-1)/4`；已经是 0–1 的值保持原值），按权重 `{likert_mean 0.4, structure 0.3, coverage 0.3}`（来自 `config.ranking.weights`）加权平均、除以权重和，降序排序，标 `rank` 与 `selected_top_n`，返回 Top-N 及 cutoff 近似并列候选。
- **输出**：`[{index, model, score, metrics{}, score_ci_lower, score_ci_upper, uncertainty_status, uncertainty_overlap, requires_review, rank, selected_top_n}]`。
- **关键**：workflow 只把**质量门控通过**的候选喂进来（见 Workflow 1）。

### OCR 地基质量状态 — `ocr.py` / `data/sample_data.py`

- 页级 OCR sidecar 记录 `quality_status`：`passed`、`review_required` 或 `blocked`。
- 空 OCR、疑似截断页或整体截断会进入 `blocked`；verifier 分歧/失败进入 `review_required`。样本准备阶段保留 warning 和审计产物，但只有 `passed` 才把缓存路径作为可用 `report_text`。
- verifier 只做 audit：disagreement、失败和非法响应进入 `review_required`，不改写 primary OCR 文本。
- `ocr-benchmark` 对带 provenance 的 gold/candidate sidecar 同样 fail-closed：`quality_status=blocked` 或 `review_required` 的文本不会进入 CER、数字和否定词统计；传统无 provenance 纯文本 manifest 保持兼容。

### Tool 10 · 按模型加权 — `tools/tool10_modelwise.py`

- **入口**：`modelwise_weighted(rows, weights=None) -> dict`
- **实现**：跨多个模型，对每个数值指标做加权均值（默认权重 1.0），丢弃非数值/bool；附 `model_count`。**保留指标维度、压缩模型维度** → 得到一份「该病例的模型代表值」。
- **用处**：Workflow 2 里把每个病例的多模型评估压成一行 `modelwise_metrics`。

### Tool 11 · 按危害加权 — `tools/tool11_hazardwise.py`

- **入口**：`hazardwise_weighted(rows, hazard_weights=None) -> list`
- **实现**：按 `error_type + hazard_level` 查权重表 `DEFAULT_HAZARD_WEIGHTS`（omission 最重，level 越高权重越大），把权重乘到该行的数值指标上，附 `hazard_weight`。**不做维度缩减**，结构与输入同形。

### Tool 12 · 统计计算 — `tools/tool12_statistics.py`

- **入口**：`calculate_statistics(rows) -> dict`；`percentile_rank(value, population) -> float`
- **实现**：对每个数值指标收集成列，算 `n / mean / std / min / max / ci_lower / ci_upper`；fallback/mock 行会被排除。小样本使用保守 t 临界值，`n=1` 时 CI 上下界为 `null`（表示无法估计，而非零不确定性）。`percentile_rank` = 群体中 ≤ value 的占比 ×100。
- **用处**：Workflow 2 reader 聚合、Workflow 3 reader 百分位与模型组统计。

### Reader `overall_score` 合约

- `overall_score` 是 reader 人工评估的探索性汇总，不是 Tool 9 的候选排名分数；Tool 9 仍使用配置中的 `0.4/0.3/0.3` 候选权重。
- 当前 reader 汇总对每个有效的 normalized metric observation（Likert 使用 `(x-1)/4`，structure/coverage 保持 `[0,1]`）做等权 pooled mean；缺失指标只贡献实际观测，不补 0。
- 汇总前复用 Tool 12 的 provenance gate：`fallback_used`、`mock`、`mock_judge`、`debug_fallback` 和明确的 fallback source 不进入 `overall_score`。若 reader 没有任何有效观测，`overall_score=null`，Workflow 3 将其列入 `excluded_readers`，不计算百分位。
- 因此该分数用于当前工程的 reader 画像和审计，不应被解读为临床金标准或与模型 Top-N 排名同一口径；正式口径仍需冻结 metric contract 后再升级。
- Workflow3 另外输出 `reader_total_count`，表示批次中出现且完成处理的 reader 总数；`reader_count` 仍表示有资格进入统计的 reader 数，二者允许不同但必须满足 `reader_total_count >= reader_count`。这样 mock/fallback 或缺失分数 reader 被排除统计时，API 与前端仍能准确反映批次处理范围。

### 质量门控 · `tools/quality_gate.py`（设计稿外的工程增强）

- **入口**：`apply_generation_quality_gate(report, *, modality, body_part)`；`check_generation_quality(text, ...) -> dict`
- **实现**：对生成文本做**部位/模态一致性**检查。`_BODY_PART_CONFLICTS`（如 chest 报告里出现 spleen/liver/brain）、`_MODALITY_CONFLICTS`（如 CT 报告里出现 MRI 词）用词边界正则匹配；中文部位词（双肺/右肺/左肺…）也覆盖。`_mask_followup_modality_mentions` 会**屏蔽「建议进一步 CT/MRI」这类随访句**，避免误判。命中即 `passed=False` + `quality_gate_failed` + `body_part_mismatch`/`modality_mismatch` warning，并把 conflicts 记进 metadata。
- **效果**：失败候选**不进 Top-N、不进成对比较**，但保留在 JSON / CSV 里可审计（52 例里 9 个失败就是这么来的：dia_llama 胸部 CT 命中腹部、qwen3-vl-4b 头部 CT 命中胸部）。

---

## 2. 模块实现（Module 1 / 2）

### Module 1 · 单报告评估 — `modules/single_report.py`

- **入口**：`evaluate_single_report(report_text, image_path=None, modality=None, ...) -> dict`
- **编排**：Tool 1（Likert）+ Tool 2（finding graph，backend 取 `config.extractor.backend`，默认 `cxr_rule`）+ Tool 3（structure）。
- **输出**（`SingleReportResult.to_json()`）：
  ```json
  {"likert":{...}, "finding_graph":{...}, "structure":{...},
   "composite_inputs":{"likert_mean":..,"structure_score":..,"finding_coverage":..}}
  ```
  `composite_inputs` 是后续排名/统计的统一数值入口。

### Module 2 · 成对报告评估 — `modules/pairwise_report.py`

- **入口**：`evaluate_pairwise(report_a, report_b, image_path=None, modality=None, ...) -> dict`
- **编排**：Tool 2 ×2（A=human、B=candidate）→ **Tool 5 对齐（candidate 对 reference）** → Tool 4 hazard → 内联 structure diff。
- **输出**：`{report_a:"human_or_reference", report_b:"candidate", graph_a, graph_b, alignment, hazards, structure_diff, warnings}`。
- **注**：MVP 里图像不参与成对比较，给了 image 会加 `image_path_unused_in_mvp_pairwise` warning。

---

## 3. Workflow 实现 + **结果落点**（重点）

> 所有 workflow 都经 `write_json` 落盘；下面逐个标出**写哪些文件、写到哪**。
> 真实 52 例最终目录（下文统一记作 `<RUN>`）：
> `outputs/sample_data_2026-06-05_final_local_routed_52_20260606/`

### Workflow 1 · 单病例 — `workflows/single_case.py`

- **入口**：`run_single_case(report_path/report_text, image_path, output_path, modality=, body_part=, top_n=, model_keys=, ...)`
- **流程**：读人工报告 → `modality or recognize_modality()`（Tool 7）→ `generate_reports()`（Tool 8）→ **逐候选过 `apply_generation_quality_gate`** → 对 human + 每个候选跑 Module 1 → **只取质量通过的**喂 `select_top_k`（Tool 9）→ 对 human vs 每个 Top-N 跑 Module 2 → 组装 → `write_json(output_path, result)`。
- **结果落点**：**单个 JSON = `output_path`**（调用方指定）。
  - 单机 smoke：`make smoke` → `outputs/mvp_result.json`。
  - 批量时由 Workflow 2 指定到 `<RUN>/workflow2_cases/<case_id>.json`。
- **JSON 顶层键**：`input` / `human_evaluation` / `generated_reports[]` / `generated_evaluations[]` / `rankings[]` / `pairwise_comparisons[]`。

### Workflow 2 · 批量医生 vs 模型 — `workflows/batch_readers.py`

- **入口**：`run_batch_readers(manifest_path, output_path, *, model_keys=, model_sources=, limit=, ...)`
- **流程**：`load_manifest` 读 manifest.jsonl → `_precompute_medharness_cli_reports` 把同一本地模型的多病例**批量推理**（省 GPU 加载）→ 逐病例调 Workflow 1（结果写进 `workflow2_cases/`）→ 抽 `composite_inputs` → `modelwise_weighted`（Tool 10）压成每病例一行 → 按 reader 聚合 `calculate_statistics`（Tool 12）+ `overall_score`。失败病例进 `failed_cases` 不中断。
- **结果落点**：
  - 主结果：**`output_path`**（约定 `<RUN>/workflow2.json`）。顶层：`manifest_path / case_count / failed_case_count / cases[] / failed_cases[] / per_reader{} / statistics{}`。
  - 每病例 Workflow 1 全量：**`<output_path 同级>/workflow2_cases/<case_id>.json`**（自动建目录）。
- **CLI**：`medharness2 workflow batch-readers --manifest … --output <RUN>/workflow2.json`。

### Workflow 3 · 科室医生组 vs 模型组 — `workflows/department.py`

- **入口**：`run_department_comparison(batch_result_path, output_path)`
- **流程**：读 Workflow 2 结果 → 取每 reader `overall_score` → `percentile_rank`（Tool 12）算百分位 → `calculate_statistics` 分别算 readers 组与 model_group 组统计。
- **结果落点**：**`output_path`**（约定 `<RUN>/workflow3.json`）。顶层：`batch_result_path / reader_count / case_count / statistics{readers, model_group} / reader_percentiles{} / comparisons{}`。
- **CLI**：`medharness2 workflow department --batch-result <RUN>/workflow2.json --output <RUN>/workflow3.json`。

### Workflow 4 · 教育建议 — `workflows/education.py`

- **入口**：`run_education_suggestions(eval_report=<wf1.json>, output_path=<education.json>)` 或 `run_education_suggestions(eval_radiologist=<wf2.json>, output_path=<education.json>)`，两种输入互斥。
- **CLI**：
  - `medharness2 workflow education --eval-report <workflow1.json> --output <education.json>`
  - `medharness2 workflow education --eval-radiologist <workflow2.json> --output <education.json>`
- **API**：`POST /workflow/education`。
- **流程**：
  - `eval_report` 模式读取 Workflow 1 JSON，使用 human Likert、finding_graph、pairwise hazards/rankings 生成病例级建议。
  - `eval_radiologist` 模式读取 Workflow 2 JSON，比较 reader 聚合指标与 peer baseline，生成医生级建议。
  - 默认 deterministic 生成结构化 suggestions；如配置真实 LLM provider，会尝试让 LLM 返回同 schema JSON，解析失败回落 deterministic。
- **结果落点**：调用方指定的 `output_path`。顶层包含 `mode`、`status`、`suggestions[]`、`general_suggestions[]` 或 `radiologist_summary`、`metadata`。
- **审计**：CLI/API 路径会在输出文件同级写 `run_registry.json`，记录 `workflow.education` stage、输入、输出和 suggestion 计数。

### 编排 / 合并 / 分析（工程闭环用）

| 命令 / 函数 | 文件 | 结果落点 |
| --- | --- | --- |
| `sample-full`（端到端一条龙） | `workflows/sample_full.py` → `run_sample_full` | 写 `<RUN>/manifest.jsonl`、`summary.json`、`workflow2.json`、`workflow3.json`、`run_summary.json`，并跑 validation |
| `sample-full --dry-run`（路由预演） | `plan_sample_full_routes` | `<RUN>/route_plan.json` + `route_plan.manifest.raw.jsonl` |
| `merge-batches`（多子批合并成 52 例） | `workflows/merge_batches.py` | `<RUN>/workflow2.json`、`workflow3.json`、`run_summary.json`、`workflow2_cases/*.json`、`manifest.jsonl`、`summary.json` |
| `analyze-run`（出报表） | `workflows/analyze_run.py` → `analyze_run` | `<RUN>/analysis/` 下 7 个产物（见下） |
| `reevaluate-run`（复用既有报告重评估） | `workflows/reevaluate_run.py` → `reevaluate_run` | `<REEVAL_RUN>/workflow2.json`、`workflow3.json`、`run_summary.json`、`workflow2_cases/*.json`；复用 source run 的 `generated_reports`，不触发报告生成模型；`run_summary.validation` 会继承 source run 的 `expected_cases` 与 `require_real_ocr` 策略并重新验证 |
| `validate-run`（验证闸门） | `validation/sample_run.py` | 递归验证 case/finding/report/hazard/可选审计合约及审计 SHA-256 绑定；控制台输出校验 JSON，并在 `<RUN>/run_registry.json` 记录通过/失败状态 |
| `schemas migrate-run`（v1→v2） | `contracts/migrations.py` | 递归迁移 legacy finding/hazard，保留未知字段和 migration provenance；输出可直接验证的 `<MIGRATED_RUN>/workflow2_cases/`、兼容 `cases/`、支持文件与 `migration_report.json` |
| `experiments run`（Notion 实验聚合 v1） | `workflows/experiments.py` → `run_experiments` | `<EXP>/results.json`、`results.md`、`experiment_summary.csv`、`experiment_protocol.json/.md/.csv`；若缺少教育产物会生成 `<RUN>/education/radiologist_summary.json`；并写 `<EXP>/run_registry.json` 与 `<RUN>/run_registry.json` |
| `figures build`（v1 SVG/表格） | `figures.py` → `build_figures` | `<FIG>/fig1_system_overview.svg`、`fig2_single_case_evidence_chain.svg`、`fig3_finding_graph_alignment.svg`、`fig4_feedback_card.svg`、`fig5_experiment_protocol.svg`、`fig6_main_results.svg`、`fig7_case_level_distribution.svg`、`fig8_error_hazard.svg`、`fig9_auxiliary_metrics.svg`、`table1_dataset_run_summary.csv/.md`、`table2_metric_taxonomy.csv/.md`、`figure_manifest.json`，并写 `<FIG>/run_registry.json` 与 `<RUN>/run_registry.json` |
| `dashboard build`（控制面板） | `dashboard.py` → `build_dashboard` | `web/control_panel.html`，展示 run summary、Workflow Development、工具实现、模型路由、实验进度、Experiment Protocol、Figure Artifacts 和 Run Registry |
| `tools catalog`（能力目录） | `catalog.py` → `build_capability_catalog` | `outputs/capability_catalog.json`，含 `tools`、`workflow_stages`、`models`、`providers`，并在输出同级写 `run_registry.json` |

CLI 长流程会自动写 append-only `run_registry.json`：`single-case`、`sample-data`、`sample-full`、`sample-full --dry-run`、`batch-readers`、`department`、`merge-batches`、`analyze-run`、`reevaluate-run`、`validate-run`、`preflight`、`education` 均记录 stage、输入、输出、指标和失败状态。

> **52 例最终结果就是 `merge-batches` 合并多个本地模型子批 + `analyze-run` 生成的**，不是一次性跑出来的（见 README「merge」段与 `run_summary.json` 的 `merge_metadata.source_batch_results`）。

---

## 4. 最终结果文件清单（`<RUN>/` 实际内容）

```
<RUN>/
├── manifest.jsonl            # 52 例输入清单（每行一例：报告/影像/模态/部位/reader）
├── summary.json              # manifest 级摘要（模态/部位计数）
├── workflow2.json            # Workflow 2 主结果（cases[] + per_reader + statistics）
├── workflow2_cases/          # 52 个 Workflow 1 全量 JSON（逐病例钻取用）
│   └── <case_id>.json        #   input/human_evaluation/generated_reports/rankings/pairwise
├── workflow3.json            # Workflow 3 科室统计（reader_percentiles + model_group）
├── run_summary.json          # 运行总账：summary + validation + merge_metadata
├── run_registry.json         # append-only 阶段账本：validate/analyze/experiments/figures/dashboard 等
└── analysis/                 # analyze-run 产物（汇报/论文统计用）
    ├── analysis_summary.json #   计数总表（机器可读）
    ├── analysis_summary.md   #   计数总表（人读，含 markdown 表）
    ├── case_routes.csv       #   52 行：每病例 → reader/模态/部位/模型/来源/质量
    ├── model_source_summary.csv      # 8 行：每模型×来源 → 报告数/质量/选入 Top-N
    ├── modality_body_part_summary.csv# 6 行：每模态×部位 → 病例/候选/来源
    ├── reader_summary.csv    #   6 行：每 reader → 病例数/overall_score/百分位
    └── quality_gate_failures.csv     # 9 行：失败候选 → 模型/来源/冲突词
```

**怎么快速定位结果：**
- 想看**整体数字** → `run_summary.json`（case_count=52、failed=0、real_ocr=52、validation.passed=true）。
- 想看**某个病例全过程** → `workflow2_cases/<case_id>.json`。
- 想在不重跑生成模型的情况下刷新评价器结果 → `workflow reevaluate-run --source-run-dir <RUN> --output-dir <REEVAL_RUN>`。
- 想看**汇报用表格** → `analysis/*.csv` 与 `analysis_summary.md`。
- 想看**医生百分位/统计** → `workflow3.json`。
- 想看**阶段审计记录** → `run_registry.json`。
- 想看**每个环节开发状态 / 输入输出形式 / 模型使用策略** → `outputs/capability_catalog.json` 的 `workflow_stages`，或打开 `web/control_panel.html` 的 Workflow Development 表。
- 想看**Notion 实验安排如何落到当前结果** → `outputs/experiments/.../experiment_protocol.json/.md/.csv`；其中每个实验都有研究问题、输入输出、实现方式、模型/API 策略、当前证据、限制和下一步。
- 想在**网页控制面板里看** → 打开 `web/control_panel.html`，其中展示 Experiment Protocol 和 Figure Artifacts 图表/表格产物表，并内嵌 `run_summary`、`catalog`（含 `workflow_stages`）、`experiments`、`experiment_protocol`、`figures` 和 `run_registry` JSON。

---

## 5. 复现命令（与 Makefile 一致）

```bash
cd /data/isbi/gzp/medHarness2
python -m pip install -e ".[test]"

# 单元/编译验证（330 passed）
make test                       # = compileall + pytest -q

# 单病例 smoke（→ outputs/mvp_result.json）
make smoke                      # 默认 chexagent artifact，快速
make smoke-maira2               # 走本地 fresh maira_2（需 GPU）

# 端到端样本（→ <SAMPLE_OUTPUT_DIR>/ 全套文件）
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/<your_run> --expected-cases 52

# 对最终 52 例：验证 + 出分析表（→ <RUN>/analysis/ 7 个产物）
make final-sample-check         # = validate-run + analyze-run + 产物存在性检查
```

最近一次验证：`pytest 330 passed, 17 warnings`、`git diff --check` 通过；当前环境未安装 `ruff`/`mypy`。重评估 run 的
`validate-run --expected-cases 52 --require-real-ocr` 为 `passed=true errors=[] real_ocr_count=52`，
`experiments=6`、`experiment_protocol=6`、`figures=11`、`dashboard cases=52 tools=12 experiments=6`。最终 52 例 run 和
`..._reeval_tool2_v1` 重评估 run 的 `run_registry.json` 会记录 `workflow.reevaluate-run`、
`workflow.validate-run`、`workflow.analyze-run`、`experiments.run`、`figures.build`、`dashboard.build` 等阶段。

---

## 6. 当前实现边界（写文档时如实标注）

- **Tool 2 / Tool 4 仍需医学质量验证**：Tool 2 已实现 CXR/CT/MRI 模态模板候选 + strict LLM 校正，Tool 4 已实现确定性先验 + strict 主 judge + 独立 reviewer；工程链路通过不等于医学有效，仍需医生 gold labels、跨 prompt/跨模型可靠性分析和冻结测试集。
- **Tool 7 多被跳过**：manifest 已带 modality 时不调用。
- **Workflow 4 是 v1 实现**：已有 deterministic/LLM-fallback 教育建议生成，但尚未经过医生验证；DMX 强模型配置模板与 Tool 4 schema retry 已落地，教育角色尚未正式接入外部模型生成链路。
- **生成来源混合**：52 例里 `medharness_cli` 47 / `artifact_reuse` 14 / `local_vlm_fallback` 20，CT chest 是历史 artifact、CR abdomen 与 CT head 用 Qwen3-VL 兜底，均非正式 report-trained 路线。
- **探索性 fresh benchmark 不等于 formal**：11 例 CXR chest 的 `qwen3vl_8b_mimic_cxr_sft` 真实 fresh inference 已完成，输入、模型、配置和输出 hash 均保留；11 份报告只有 5 个唯一文本。纯 DMX 后评估 11/11 成功且无 fallback，但重复运行的 T1 和 hazard 指标稳定性不足。因没有医生验证 ID，仍为 `exploratory_fresh`。
- **real OCR 不等于完整 OCR**：旧 Qwen3-VL 4B OCR 的 52 例缓存均有非空文本，但确定性审计发现 6 例明确截断、7 例疑似截断，全部位于 CT；正式数据门禁必须增加章节完整性和 length-truncation 检查。
- **结论口径**：当前是 **pilot engineering run**；现有 52 例三类审计计数均为 0，且生成报告为 `14 artifact + 67 debug_fallback + 0 formal_fresh`。正式医学结论必须等待医生 gold set、强角色冻结和 formal-fresh 重跑。
