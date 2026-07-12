# medHarness2 Production and Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 medHarness2 从可运行的研究 MVP 升级为可审计、可复跑、可扩展、具备医生金标准验证和论文级实验产物的放射报告评价与教育系统。

**Architecture:** 保留现有 Tool -> Module -> Workflow 分层，新增版本化数据契约、模型角色路由、去标识化边界、任务控制平面、实验注册与统计分析层。确定性能力由代码实现，报告生成和医学语义抽取优先使用本地医学专用模型，复杂评价与教育文本优先使用经金标准验证的 DMX 强模型；所有模型输出均经过 schema 校验和 provenance 记录。兼容路径可显式 fallback，正式角色在失败时必须中止，不能用 fallback 冒充真实模型结果。

**Tech Stack:** Python 3.10+、FastAPI、Pydantic v2、SQLAlchemy/Alembic、Redis/RQ、React/TypeScript/Vite、PyTorch/Transformers、DMX OpenAI-compatible API、pandas/scipy/statsmodels、matplotlib/seaborn、pytest。

---

## 1. 当前基线与完成定义

### 1.1 已验证基线

- 当前代码量约为 `src=8011 LOC`、`tests=4333 LOC`。
- 自动化验证：当前全量回归为 `268 passed, 17 warnings`；最终计数以 `docs/project_status.yaml` 为准。
- 当前能力目录：12 个 Tool、16 个 workflow/产物阶段、7 个强模型角色。
- 当前真实 run：52 cases、6 readers、81 generated reports、0 failed cases。
- 当前 52 例结果只定义为 **pilot engineering run**：可验证链路和产物，不用于证明临床有效性。
- Tool 2 已有 CXR/CT/MRI 模态规则候选和 strict LLM 校正；医学有效性仍待 gold set。
- Tool 4 已具备 deterministic prior、strict 主 judge、独立 reviewer 和 disagreement artifact；完整链路只完成无患者数据 synthetic smoke。
- 控制面板目前是静态 HTML，不具备任务提交、实时状态、日志、重试和结果版本管理。

### 1.2 最终 Definition of Done

只有以下证据全部存在，项目才可称为“生产级研究系统完成”：

1. **数据契约**：所有输入输出都有版本化 schema、兼容性测试和迁移策略。
2. **隐私边界**：外部 API 永不接收原始 DICOM、PDF、PHI 或自由文本报告；病例衍生结构化数据须经过批准的数据策略和自动扫描。
3. **工具质量**：每个 Tool 有 unit/golden/property/failure tests，医学工具有医生 gold-set 指标。
4. **模型质量**：每个 modality/body-part 的正式报告模型均为 fresh inference；artifact/fallback/debug 路线不混入正式比较。
5. **评价可靠性**：自动评价与医生评分的相关性、一致性、校准和置信区间达到预注册阈值。
6. **实验完整性**：Notion 六项实验均有冻结数据、实验 manifest、随机种子、统计方案、原始结果、表格和图。
7. **控制平面**：可创建、取消、重试和查看 run；可查看每一步输入输出 schema、实际 provider/model/version、日志、耗时和错误。
8. **可复现性**：从空 output 目录执行一条命令可重建正式结果；产物带 git SHA、config hash、dataset hash、model hash 和环境信息。
9. **验证**：全量测试、端到端测试、安全扫描、数据泄漏扫描和固定正式 run verifier 全部通过。
10. **医学边界**：文档和 UI 明确系统用于研究评价与教育，不替代临床诊断；正式结论由医生 adjudication 支撑。

---

## 2. Tool / Model / API 决策矩阵

| 能力 | 正式实现 | DMX | 本地医学模型 | 确定性代码 | 选择理由 | 正式验收 |
|---|---|---:|---:|---:|---|---|
| 报告 OCR | 本地 OCR/VLM + cache | 禁止发送原始 PDF | 首选 | 辅助 | 原始报告可能含 PHI | 字符错误率、字段完整率、52 例人工抽查 |
| Modality/body part | DICOM header + series rules | 仅无法解析的去标识化图像研究可选 | 可选 | 首选 | 元数据问题无需 LLM | accuracy、unknown rate、冲突率 |
| Section parsing | parser | 不使用 | 不使用 | 必须 | 可重复、可解释 | section-level F1 |
| Finding extraction | modality plugin：规则 + 医学模型 | 强通用模型作为候选/复核 | 首选候选 | measurement/negation 辅助 | CT/MRI 语义需要医学模型；规则保证基础稳定性 | entity/relation micro/macro F1 |
| Finding normalization | ontology + deterministic mapper | 仅 unresolved concept 复核 | 可选 | 首选 | 术语映射需稳定 ID | concept accuracy、unmapped rate |
| Graph alignment | 最大权重二分匹配为主 + LLM 只读审计 | 审计候选 | 可选审计 | 必须 | 主匹配必须可重复；LLM 只发现语义错配 | pair-level precision/recall/F1、audit precision |
| Likert/rubric scoring | 双 judge + deterministic validation | 主 judge/reviewer 候选 | 医学 judge 候选 | schema/fallback | 需要高阶语言判断但必须金标准选型 | Spearman、ICC、MAE、校准 |
| Hazard scoring | DMX 主 judge + reviewer disagreement | 优先 | 可做第三候选 | template prior | `gpt-5.6-terra`/`claude-opus-4-8` 已通过 synthetic integration；仍需医生验证 | weighted kappa、macro F1、critical recall |
| Report generation | modality-specific registry | 只作显式 cloud baseline | 必须优先 | route/quality gate | 生成是医学专用任务 | 医生盲评、error count、RadGraph/CheXbert 等辅助指标 |
| Quality gate | clinical rules + learned validator | 可做复核 | 可选 | 首选 | 明显越域错误应稳定拦截 | false-block / missed-block rate |
| Ranking/statistics | frozen formula + statistical code | 不使用 | 不使用 | 必须 | 避免模型随意改变排序 | deterministic snapshot、bootstrap CI |
| Education feedback | evidence-grounded generation | 优先强模型 | 医学模型候选 | template fallback | 需要自然语言建议，但必须引用证据 | 医生 helpfulness/actionability/safety |
| 图表与表格 | Python plotting pipeline | 不使用 | 不使用 | 必须 | 可复现论文产物 | manifest、pixel/内容检查、数据一致性 |

### 2.1 DMX 正式策略

- 当前强候选：`general_judge/finding_extractor/alignment_auditor/hazard_primary/structure_auditor/education -> gpt-5.6-terra`。
- 独立 reviewer：`hazard_reviewer -> claude-opus-4-8`，调用时省略 temperature。
- DMX 仍是首选 provider；`config/yunwu_strong.yaml` 只作为显式备用，不自动 failover。
- 这些名称仅表示 DMX 模型 ID；正式实验记录 endpoint、模型 ID、调用日期和响应 fingerprint，不推断其真实上游厂商。
- 任一角色是否进入正式结果，由 gold-set benchmark 决定，而不是仅凭“模型更强”或 synthetic smoke。
- 模型分歧必须作为结构化产物保存；无医生 adjudication 时不得自动多数投票替换主结果。
- 所有 API prompt 必须由 `ExternalPayloadPolicy` 生成，业务代码不得直接拼接原始病例文本。

### 2.2 Tool 1-12 实施映射

| Tool | 正式职责 | 主要任务 | 核心证据 |
|---|---|---|---|
| Tool 1 | Likert/rubric judge | Task 2.4 | 医生评分相关性、ICC、MAE、prompt stability |
| Tool 2 | modality-specific finding extraction | Task 2.2 | finding/entity/relation gold-set F1 |
| Tool 3 | section structure parser | Task 2.5 | 中英文 section-level F1 |
| Tool 4 | clinical hazard judge | Task 2.4、Task 5.3、E3 | weighted kappa、critical recall、calibration |
| Tool 5 | finding graph alignment | Task 2.3 | pair matching F1、critical omission recall |
| Tool 6 | report structure difference | Task 2.6 | metric definition、golden aggregate、determinism |
| Tool 7 | modality/body-part recognition | Task 2.5、E6 | accuracy、macro F1、unknown/routing error rate |
| Tool 8 | image-to-text report generation | Task 3.1-3.3、E5 | fresh-only model benchmark、医生盲评 |
| Tool 9 | Top-K ranking | Task 2.6 | contribution audit、tie-break、rank stability |
| Tool 10 | modelwise aggregation | Task 2.6 | denominator/missingness、golden aggregates |
| Tool 11 | hazardwise weighted metrics | Task 2.6 | versioned hazard weights、numeric stability |
| Tool 12 | statistics | Task 2.6、Task 6.2 | estimator tests、cluster CI、assumption report |

控制面板必须从同一映射和 capability catalog 读取状态，不能维护另一份手工列表。

---

## 3. 执行顺序与里程碑

| Wave | 目标 | 进入条件 | 退出证据 |
|---|---|---|---|
| W0 | 冻结基线与实施治理 | 当前工作树可测试 | baseline manifest、风险清单、正式 plan |
| W1 | 数据契约、隐私、provenance | W0 完成 | schema v2、redaction tests、artifact validator |
| W2 | Tool 1-7 生产化 | W1 完成 | gold sets、医学指标、失败测试 |
| W3 | 报告生成模型正式矩阵 | W1 完成，可与 W2 后半并行 | fresh-only benchmark、正式模型白名单 |
| W4 | Workflow 1-4 与异步控制平面 | W2/W3 接口冻结 | 可恢复 run、实时面板、审计日志 |
| W5 | 医生标注与 judge 校准 | W2 完成 | frozen gold labels、模型选择报告 |
| W6 | Notion 六项正式实验 | W3/W5 完成 | results bundle、统计报告、消融 |
| W7 | 论文图表、复现包与发布门禁 | W6 完成 | figures/tables、reproduction report、release candidate |

---

## 4. W0：基线冻结与项目治理

### Task 0.1：建立唯一实施状态文件

**Files:**
- Create: `docs/project_status.yaml`
- Create: `docs/decision_log.md`
- Modify: `docs/research_v1_implementation_handoff.md`
- Test: `tests/test_project_metadata.py`

- [x] **Step 1: 写失败测试，要求状态文件包含固定字段**

```python
def test_project_status_has_required_release_fields():
    payload = yaml.safe_load(Path("docs/project_status.yaml").read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["current_phase"]
    assert payload["baseline"]["pytest_passed"] >= 146
    assert set(payload["workstreams"]) >= {
        "contracts", "tools", "generation", "control_plane", "clinical_validation", "experiments", "figures"
    }
```

- [x] **Step 2: 记录当前基线，不把 pilot 标为正式结果**

`project_status.yaml` 必须记录：git SHA、dirty 状态、当前 test baseline、52-case pilot 路径、每个 workstream 的 `not_started/in_progress/validated/blocked`、owner、证据路径和下一 gate。

- [x] **Step 3: 建立决策日志**

首批 ADR：DMX-first 但 gold-set 决定正式模型；raw PHI 不外发；52 例是 pilot；artifact/fallback 不得进入 fresh model 正式比较；统计方案在 test set 解盲前冻结。

- [x] **Step 4: 验证**

```bash
PYTHONPATH=src python -m pytest tests/test_project_metadata.py -q
```

**Gate:** 状态文件能由控制面板读取；不存在“完成”但没有 evidence path 的项目。

### Task 0.2：冻结基线 run manifest

**Files:**
- Create: `src/medharness2/reproducibility.py`
- Create: `tests/test_reproducibility.py`
- Create: `outputs/baselines/2026-07-10-pilot52/baseline_manifest.json`

- [ ] **Step 1: 定义 manifest schema**

```json
{
  "schema_version": "1.0",
  "run_kind": "pilot",
  "git_sha": "<sha>",
  "config_sha256": "<hash>",
  "dataset_manifest_sha256": "<hash>",
  "source_run": "outputs/..._reeval_tool2_v1",
  "expected": {"case_count": 52, "reader_count": 6, "generated_report_count": 81},
  "artifacts": [{"path": "workflow2.json", "sha256": "<hash>"}]
}
```

- [ ] **Step 2: 实现 `build_repro_manifest()` 与 `verify_repro_manifest()`**

不得把绝对敏感路径、API key 或 prompt 原文写入 manifest。

- [ ] **Step 3: 验证固定 run**

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1 \
  --expected-cases 52 --require-real-ocr
PYTHONPATH=src python -m pytest tests/test_reproducibility.py -q
```

**Gate:** 修改任一受控 artifact 后 verifier 必须失败并指出文件。

---

## 5. W1：版本化数据契约、隐私和审计

### Task 1.1：引入 Pydantic artifact contracts

**Files:**
- Create: `src/medharness2/contracts/__init__.py`
- Create: `src/medharness2/contracts/case.py`
- Create: `src/medharness2/contracts/evaluation.py`
- Create: `src/medharness2/contracts/run.py`
- Create: `src/medharness2/contracts/migrations.py`
- Modify: `src/medharness2/schema.py`
- Modify: `pyproject.toml`
- Test: `tests/contracts/test_contracts.py`
- Test: `tests/contracts/test_migrations.py`

- [x] **Step 1: 为 Case、Finding、Error、Judge、GeneratedReport、Run 定义 `schema_version`**

核心类型必须包括：

```python
class Finding(BaseModel):
    finding_id: str
    observation_code: str | None
    observation_text: str
    anatomy_code: str | None
    location_text: str | None
    laterality: Literal["left", "right", "bilateral", "midline", "unknown"]
    certainty: Literal["present", "absent", "uncertain"]
    severity: str | None
    measurements: list[Measurement]
    source_span: TextSpan | None
    extractor: ModelProvenance
```

- [x] **Step 2: 保持 v1 JSON 可读，所有新写出产物使用 v2**

迁移函数必须显式记录 `migration_warnings`，不得静默丢字段。

- [x] **Step 3: 输出 JSON Schema**

```bash
PYTHONPATH=src python -m medharness2.cli schemas export --output-dir docs/schemas
```

- [x] **Step 4: 验证 round-trip、旧产物迁移和非法值拒绝**

```bash
PYTHONPATH=src python -m pytest tests/contracts -q
```

**Gate:** 当前 52 例所有 case JSON 均能迁移；迁移报告中无 silent drop。

### Task 1.2：外部 API 数据最小化策略

**Files:**
- Create: `src/medharness2/privacy.py`
- Create: `config/privacy/default.yaml`
- Modify: `src/medharness2/llm_client.py`
- Modify: `src/medharness2/tools/tool1_likert.py`
- Modify: `src/medharness2/tools/tool4_hazard.py`
- Modify: `src/medharness2/workflows/education.py`
- Test: `tests/test_privacy.py`
- Test: `tests/test_external_payloads.py`

- [ ] **Step 1: 实现统一 payload policy**

```python
class ExternalPayloadPolicy:
    def build(self, role: str, artifact: BaseModel) -> SanitizedPayload: ...
    def scan(self, payload: str) -> PrivacyScanResult: ...
```

阻断字段：姓名、身份证/住院号/门诊号、电话、日期组合、报告原文、绝对路径、DICOM UID、PDF/影像 bytes。

- [ ] **Step 2: 所有 DMX 调用必须经过 policy**

`LLMClient.call()` 增加 `payload_classification` 和 `privacy_scan_id`；缺失时 production profile 拒绝调用。

- [ ] **Step 3: 建立 canary 泄漏测试**

测试向各 workflow 注入 `PATIENT_CANARY_9271`，断言 mock transport 捕获的请求中不存在该字符串。

- [ ] **Step 4: 验证**

```bash
PYTHONPATH=src python -m pytest tests/test_privacy.py tests/test_external_payloads.py -q
```

**Gate:** 任何未经分类的外部调用 hard fail；扫描日志不保存敏感原文。

### Task 1.3：统一 provenance 和错误分类

**Files:**
- Create: `src/medharness2/provenance.py`
- Create: `src/medharness2/errors.py`
- Modify: `src/medharness2/run_registry.py`
- Modify: `src/medharness2/catalog.py`
- Test: `tests/test_provenance.py`

- [ ] **Step 1: 标准化每一步 provenance**

必须包含：implementation type、provider、model ID、model hash/version、prompt version、code git SHA、config hash、started/finished UTC、latency、attempts、fallback、input/output hashes。

- [ ] **Step 2: 标准化错误类别**

`validation_error / privacy_block / provider_auth / provider_rate_limit / provider_timeout / model_oom / schema_error / data_error / internal_error / cancelled`。

- [ ] **Step 3: 验证 registry 永不记录 key 或完整 prompt**

```bash
PYTHONPATH=src python -m pytest tests/test_provenance.py tests/test_catalog_and_registry.py -q
```

---

## 6. W2：Tool 1-7 生产化

### Task 2.1：建立医生 gold-set 标注格式与工具

**Files:**
- Create: `annotation/guidelines/finding_annotation.md`
- Create: `annotation/guidelines/hazard_annotation.md`
- Create: `annotation/schemas/annotation.schema.json`
- Create: `src/medharness2/annotation/export.py`
- Create: `src/medharness2/annotation/importer.py`
- Create: `src/medharness2/annotation/adjudication.py`
- Test: `tests/annotation/test_annotation_io.py`

- [ ] **Step 1: 定义双盲标注和 adjudication schema**

每例至少支持两个独立 reader、一名 adjudicator；保存 finding、关系、错误类型、hazard 1-5、置信度和理由，但不保存自由 CoT。

- [ ] **Step 2: 建立分层抽样**

按 modality、body part、报告来源、错误类型和质量门结果分层；pilot gold set 不少于每个主要 strata 20 个有效样本，正式样本量由 power analysis 决定。

- [ ] **Step 3: 验证 inter-rater 输出**

导出 Cohen/Fleiss kappa、weighted kappa、ICC 和 disagreement queue。

**Gate:** 标注指南经至少一名放射科医生审阅；10 例试标完成并修订指南后才能冻结正式 gold set。

### Task 2.2：Tool 2 modality extractor plugin

**Files:**
- Create: `src/medharness2/extractors/base.py`
- Create: `src/medharness2/extractors/cxr.py`
- Create: `src/medharness2/extractors/ct.py`
- Create: `src/medharness2/extractors/mri.py`
- Create: `src/medharness2/extractors/registry.py`
- Create: `src/medharness2/extractors/normalization.py`
- Modify: `src/medharness2/tools/tool2_extract.py`
- Modify: `config/default.yaml`
- Test: `tests/extractors/test_cxr.py`
- Test: `tests/extractors/test_ct.py`
- Test: `tests/extractors/test_mri.py`
- Test: `tests/extractors/test_goldset.py`

- [ ] **Step 1: 先冻结 extractor interface**

```python
class FindingExtractor(Protocol):
    def extract(self, report: SanitizedReport, context: ExtractionContext) -> FindingGraph: ...
```

- [ ] **Step 2: 将现有 CXR 规则迁移为 plugin，不改变当前行为**

- [ ] **Step 3: CT/MRI 实现双候选路线**

路线 A：本地医学模型；路线 B：强 API 模型结构化抽取，当前候选为 DMX `gpt-5.6-terra`。两者都经过 schema validator、evidence grounding 和 ontology normalization。

- [ ] **Step 4: 用 dev gold set 选每个 modality 的正式 backend**

主要指标：finding micro F1、macro F1、negation F1、laterality accuracy、measurement exact/within-tolerance accuracy、relation F1。

- [ ] **Step 5: 固定最低门槛**

正式 test set 建议门槛：micro F1 >= 0.85、negation F1 >= 0.95、laterality accuracy >= 0.95；若数据难度导致门槛不可达，必须由医生委员会在解盲前修订，不得事后降阈值。

### Task 2.3：Tool 5 临床图谱对齐

**Files:**
- Create: `src/medharness2/alignment/scoring.py`
- Create: `src/medharness2/alignment/matcher.py`
- Modify: `src/medharness2/tools/tool5_align.py`
- Test: `tests/alignment/test_matcher.py`
- Test: `tests/alignment/test_goldset.py`

- [ ] **Step 1: 用最大权重二分匹配替换 observation-key 贪心**

权重由 concept、anatomy、laterality、certainty、severity 和 measurement 组成；阈值由 dev set 冻结。

- [ ] **Step 2: 增加 contradiction、temporal change、uncertain-vs-present 分类**

- [ ] **Step 3: 建立对称性、排列不变性、单位归一化 property tests**

```bash
PYTHONPATH=src python -m pytest tests/alignment -q
```

**Gate:** pair matching F1 >= 0.90；critical omission recall >= 0.95。

### Task 2.4：Tool 1 / Tool 4 judge benchmark harness

**Files:**
- Create: `src/medharness2/judges/base.py`
- Create: `src/medharness2/judges/registry.py`
- Create: `src/medharness2/judges/benchmark.py`
- Create: `config/judges/candidates.yaml`
- Modify: `src/medharness2/tools/tool1_likert.py`
- Modify: `src/medharness2/tools/tool4_hazard.py`
- Test: `tests/judges/test_benchmark.py`
- Test: `tests/judges/test_reliability.py`

- [ ] **Step 1: 统一 judge contract**

保存最终短 rationale，不保存私有 chain-of-thought；输出必须有 criterion scores、confidence、evidence IDs、abstain 和 provenance。

- [ ] **Step 2: 候选至少包含**

DMX `gpt-5.6-terra`、DMX `claude-opus-4-8`、一个可用本地医学模型、deterministic baseline；保留 `gpt-5.5` 作为历史对照候选。

- [ ] **Step 3: 运行 prompt stability**

每个模型至少 3 个等价 prompt 版本、重复 3 次；比较 schema success、test-retest、排序稳定性和成本/延迟。

- [ ] **Step 4: 预注册正式选择规则**

Hazard：weighted kappa 优先，其次 critical recall、macro F1、schema success。Likert：ICC/Spearman 优先，其次 MAE 和 calibration。模型 ID 强弱不参与最终排序。

- [ ] **Step 5: reviewer 只生成 disagreement artifact**

输出 `judge_primary.jsonl`、`judge_reviewer.jsonl`、`judge_disagreements.jsonl`；只有医生 adjudication 可写 `judge_resolved.jsonl`。

### Task 2.5：Tool 3 / 7 和 quality gate 金标准化

**Files:**
- Modify: `src/medharness2/tools/tool3_structure.py`
- Modify: `src/medharness2/tools/tool7_modality.py`
- Modify: `src/medharness2/tools/quality_gate.py`
- Create: `tests/gold/test_structure_gold.py`
- Create: `tests/gold/test_modality_gold.py`
- Create: `tests/gold/test_quality_gate_gold.py`

- [ ] **Step 1: 支持中英文标准 section aliases 和无 header 报告**
- [ ] **Step 2: modality 同时输出 source、confidence 和 conflict warnings**
- [ ] **Step 3: quality gate 分成 hard-block 与 review-warning**
- [ ] **Step 4: 验证门槛**

Structure section F1 >= 0.98；modality accuracy >= 0.99；hard-block precision >= 0.95，且所有 false block 进入人工复核队列。

### Task 2.6：Tool 6、9、10、11、12 的确定性公式冻结

**Files:**
- Modify: `src/medharness2/tools/tool6_structure_diff.py`
- Modify: `src/medharness2/tools/tool9_rank.py`
- Modify: `src/medharness2/tools/tool10_modelwise.py`
- Modify: `src/medharness2/tools/tool11_hazardwise.py`
- Modify: `src/medharness2/tools/tool12_statistics.py`
- Create: `docs/metrics/metric_definitions.yaml`
- Create: `tests/metrics/test_metric_definitions.py`
- Create: `tests/metrics/test_numeric_stability.py`
- Create: `tests/metrics/test_golden_aggregates.py`

- [ ] **Step 1: 为每个指标冻结名称、公式、方向、范围、缺失值和分母策略**

`metric_definitions.yaml` 必须明确：高/低是否更好、归一化方法、权重来源、空集合行为、NaN/inf 行为、是否允许跨 modality 聚合。

- [x] **Step 2: Tool 6 输出 section presence、length、ordering 和 score delta**

保留现有字段兼容性，新增字段只进入 schema v2；中英文 section 使用 Tool 3 的同一 normalization，不允许两套规则漂移。

- [ ] **Step 3: Tool 9 排名使用冻结配置并报告敏感性**

输出原始指标、归一化值、权重、贡献项、tie-break reason 和 rank stability；缺少关键指标的候选不得通过默认零值获得优势。

- [ ] **Step 4: Tool 10/11 聚合保存有效分母和 missingness**

Hazard 权重必须来自版本化配置；任何权重变化产生新 metric version，不覆盖旧结果。

- [ ] **Step 5: Tool 12 使用经过测试的统计实现**

明确样本标准差、cluster bootstrap、percentile 定义和 CI 方法；小样本时输出 warning，不伪造精确 CI。

- [ ] **Step 6: golden 和 property tests**

```bash
PYTHONPATH=src python -m pytest tests/metrics -q
```

测试包括：输入排列不影响结果、重复样本按预期改变权重、全缺失/单样本/极值不崩溃、手工可计算 fixture 与结果一致。

**Gate:** 所有论文表格只能引用带 `metric_version` 的输出；同一冻结输入重复运行 hash 一致。

---

## 7. W3：报告生成模型正式矩阵

### Task 3.1：同步 medHarness readiness registry

**Files:**
- Create: `src/medharness2/generators/readiness_sync.py`
- Modify: `src/medharness2/generators/registry.py`
- Create: `config/models/formal_benchmark.yaml`
- Test: `tests/generators/test_readiness_sync.py`

- [ ] **Step 1: 从 medHarness registry/配置读取机器可读状态**

不得继续从 Markdown 文本正则推断 readiness；Markdown 仅作人类审计材料。

- [ ] **Step 2: 模型状态分层**

`formal_candidate / smoke_only / source_audit_only / artifact_baseline / debug_fallback / unavailable`。

- [ ] **Step 3: 正式候选最低要求**

fresh inference、模型权重 hash、固定 preprocessing、非空且非噪声 smoke、modality/body-part 匹配、许可证和来源记录。

### Task 3.2：构建 modality × model benchmark

**Files:**
- Create: `src/medharness2/workflows/benchmark_generation.py`
- Create: `src/medharness2/metrics/report_metrics.py`
- Create: `src/medharness2/metrics/clinical_errors.py`
- Create: `tests/workflows/test_benchmark_generation.py`

- [ ] **Step 1: 冻结 benchmark manifest**

至少分开 CXR chest、CR abdomen、CT chest、CT abdomen、CT head、MRI brain；不得用 reference report 作为生成 prompt。

- [ ] **Step 2: 每个模型执行 fresh inference**

保存输入 hash、preprocessing、GPU、dtype、seed、generation parameters、latency、peak memory 和原始输出。

- [ ] **Step 3: 计算自动指标但不单独决定胜负**

包括 finding precision/recall、hazard-weighted error、structure、RadGraph/CheXbert 类指标（适用时）、长度和重复率。

- [ ] **Step 4: 医生盲评**

隐藏模型名和生成顺序；主要终点为 clinically significant error count 与 overall preference；使用 mixed-effects model 控制 case 和 reader。

- [ ] **Step 5: 输出正式白名单**

每个 modality/body part 选主模型和备用模型；无法达到门槛的 strata 明确标记 unsupported，不用通用 fallback 冒充正式模型。

### Task 3.3：隔离 artifact/debug/fallback 结果

**Files:**
- Modify: `src/medharness2/tools/tool8_generate.py`
- Modify: `src/medharness2/workflows/sample_full.py`
- Modify: `src/medharness2/workflows/analyze_run.py`
- Test: `tests/test_source_isolation.py`

- [ ] **Step 1: 每份报告写 `evidence_tier`**

`formal_fresh / exploratory_fresh / artifact / debug_fallback / mock`。

- [ ] **Step 2: 正式实验默认只接受 `formal_fresh`**

出现其它 tier 时 formal run verifier hard fail；pilot run 允许但必须分层统计。

---

## 8. W4：Workflow 1-4 与动态控制平面

### Task 4.1：持久化 run/job/stage 数据模型

**Files:**
- Create: `src/medharness2/db/base.py`
- Create: `src/medharness2/db/models.py`
- Create: `src/medharness2/db/repository.py`
- Create: `alembic.ini`
- Create: `alembic/versions/0001_run_control.py`
- Modify: `pyproject.toml`
- Test: `tests/db/test_run_repository.py`

- [ ] **Step 1: 建立 Run、StageAttempt、Artifact、ModelInvocation、Experiment 表**

Run 状态只能按状态机变化：`queued -> running -> succeeded|failed|cancelled`；stage 支持 retry attempt 和 heartbeat。

- [ ] **Step 2: artifact 只保存路径、hash、schema version 和 MIME，不把大文件塞数据库**

- [ ] **Step 3: 支持 SQLite WAL 开发 profile 和 PostgreSQL production profile**

### Task 4.2：可靠任务执行器

**Files:**
- Create: `src/medharness2/tasks/base.py`
- Create: `src/medharness2/tasks/local.py`
- Create: `src/medharness2/tasks/redis_queue.py`
- Create: `src/medharness2/tasks/worker.py`
- Test: `tests/tasks/test_lifecycle.py`
- Test: `tests/tasks/test_recovery.py`

- [ ] **Step 1: 所有长流程通过 task backend 执行**
- [ ] **Step 2: 支持取消、超时、heartbeat、lease、幂等 retry 和断点恢复**
- [ ] **Step 3: GPU 任务按 device/model memory class 排队，禁止两个高显存任务意外争用同卡**
- [ ] **Step 4: worker 崩溃测试必须把过期 running job 恢复为 retryable**

### Task 4.3：扩展 FastAPI 控制 API

**Files:**
- Modify: `src/medharness2/api.py`
- Create: `src/medharness2/api_routes/runs.py`
- Create: `src/medharness2/api_routes/artifacts.py`
- Create: `src/medharness2/api_routes/catalog.py`
- Create: `src/medharness2/api_routes/experiments.py`
- Test: `tests/api/test_runs.py`
- Test: `tests/api/test_artifacts.py`

- [ ] **Step 1: 提供正式 endpoints**

`POST /runs`、`GET /runs`、`GET /runs/{id}`、`POST /runs/{id}/cancel`、`POST /runs/{id}/retry`、`GET /runs/{id}/stages`、`GET /runs/{id}/artifacts`、`GET /catalog/tools`、`GET /catalog/model-roles`、`GET /experiments`。

- [ ] **Step 2: 增加 SSE/WebSocket 日志流**

日志只允许结构化事件，不回显 API key、prompt 全文或患者文本。

- [ ] **Step 3: OpenAPI contract tests**

```bash
PYTHONPATH=src python -m pytest tests/api -q
```

### Task 4.4：构建实际可用的 React 控制面板

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/src/app.tsx`
- Create: `frontend/src/pages/runs.tsx`
- Create: `frontend/src/pages/run-detail.tsx`
- Create: `frontend/src/pages/tools.tsx`
- Create: `frontend/src/pages/experiments.tsx`
- Create: `frontend/src/components/artifact-viewer.tsx`
- Create: `frontend/src/components/provenance-panel.tsx`
- Test: `frontend/src/**/*.test.tsx`
- Test: `tests/e2e/test_control_panel.py`

- [ ] **Step 1: 第一屏是运行控制台，不做营销 landing page**

- [ ] **Step 2: Run detail 显示 DAG/stages、实时日志、输入输出 schema、artifact 链接、provider/model、耗时、fallback 和错误**

- [ ] **Step 3: Tool 页面显示每个 tool 的实现类别**

必须明确 `code / local medical model / DMX API / template / hybrid`，并显示选择理由、版本和验证状态。

- [ ] **Step 4: Experiment 页面显示 protocol gate**

状态至少包括 `pilot / awaiting_gold / ready / running / analyzed / frozen`；没有 gold labels 时 UI 不允许显示“validated”。

- [ ] **Step 5: 桌面和移动端 Playwright 验收**

检查无重叠、表格可横向查看、错误状态可读、SSE 更新不造成 layout shift。

### Task 4.5：完成 Workflow 4 evidence-grounded education

**Files:**
- Modify: `src/medharness2/workflows/education.py`
- Modify: `designs/revised-designs/workflow4-implementation-spec.md`
- Create: `tests/education/test_schema.py`
- Create: `tests/education/test_grounding.py`
- Create: `tests/education/test_bias_controls.py`

- [ ] **Step 1: 使用 `education` 模型角色，不再读取全局 LLM 默认值**
- [ ] **Step 2: 每条建议必须引用 finding/error/metric evidence ID**
- [ ] **Step 3: 输出短理由而非私有 CoT；修订旧规格中要求保存 CoT 的条款**
- [ ] **Step 4: 增加风格同质化、过度自信、越权诊断和无证据建议测试**
- [ ] **Step 5: API 失败使用模板 fallback，并显式标记 `fallback_used=true`**

---

## 9. W5：医生 gold labels 与模型校准

### Task 5.1：数据冻结与样本量

**Files:**
- Create: `experiments/protocols/data_split.yaml`
- Create: `experiments/protocols/power_analysis.py`
- Create: `experiments/manifests/dev.jsonl`
- Create: `experiments/manifests/test_blinded.jsonl`
- Test: `tests/experiments/test_split_integrity.py`

- [ ] **Step 1: 按患者而非图像/报告拆分，防止同一患者跨 split**
- [ ] **Step 2: stratify modality/body part/pathology/source，不使用 test labels 调参**
- [ ] **Step 3: power analysis 针对每个主要终点生成所需 case/reader 数**
- [ ] **Step 4: 生成并冻结 split hash；test set 解盲前统计计划签名**

### Task 5.2：医生标注执行与一致性门槛

**Files:**
- Create: `experiments/annotations/annotation_manifest.json`
- Create: `src/medharness2/workflows/analyze_annotations.py`
- Create: `tests/experiments/test_annotation_analysis.py`

- [ ] **Step 1: 双 reader 独立标注，模型输出和模型名均盲化**
- [ ] **Step 2: disagreement 由第三名医生 adjudicate**
- [ ] **Step 3: 标注一致性门槛**

Finding categorical kappa >= 0.70；hazard weighted kappa >= 0.65。低于门槛时先修订指南并重标 pilot，不直接进入模型比较。

### Task 5.3：DMX 和本地 judge 校准报告

**Files:**
- Create: `src/medharness2/workflows/calibrate_judges.py`
- Create: `experiments/results/judge_calibration/README.md`
- Test: `tests/workflows/test_calibrate_judges.py`

- [ ] **Step 1: 在 dev set 上完成候选比较和 prompt 选择**
- [ ] **Step 2: 在 frozen test set 一次性评估**
- [ ] **Step 3: 输出置信区间、混淆矩阵、校准曲线、分 strata 指标和 disagreement cases**
- [ ] **Step 4: 只有达到预注册阈值的角色写入 `config/production.yaml`**

---

## 10. W6：Notion 六项正式实验

所有实验共享以下输出：

```text
experiments/formal/<experiment_id>/<run_id>/
  protocol.yaml
  manifest.jsonl
  environment.json
  raw_results.jsonl
  analysis.json
  tables/*.csv
  figures/*.svg
  figures/*.png
  statistical_report.md
  artifact_manifest.json
```

### Experiment E1：Radiologist Evaluation Study

**Primary question:** 自动综合评价能否与医生总体质量评价一致，并稳定区分 reader/case 质量？

**Design:** 多 reader、多 case、盲法交叉评分；自动评分与医生评分均不接触对方结果。

**Primary endpoints:** Spearman correlation、ICC(2,k)、MAE；reader ranking bootstrap stability。

**Statistics:** case/reader 双层 bootstrap；mixed-effects model；95% CI；预注册 subgroup analysis。

**Deliverables:** correlation plot、Bland-Altman、reader forest plot、ranking stability heatmap。

**Pass gate:** Spearman >= 0.70、ICC >= 0.70，且主要 strata 无明显系统偏差。

### Experiment E2：Radiologist Finding Extraction Study

**Primary question:** modality-specific extractor 是否准确恢复 finding、否定、位置、测量和关系？

**Baselines:** 当前 CXR rules、DMX strong extractor、本地医学模型、hybrid。

**Primary endpoints:** entity/relation micro/macro F1；negation/laterality/measurement accuracy。

**Ablations:** 去掉 ontology、去掉 deterministic measurement parser、单模型 vs hybrid。

**Deliverables:** per-modality metric table、error taxonomy、confusion matrix、case graph examples。

### Experiment E3：Radiologist Error Hazard Evaluation Study

**Primary question:** 自动 judge 是否能复现医生 hazard 分级并召回高风险错误？

**Candidates:** deterministic baseline、DMX `gpt-5.5`、DMX `claude-opus-4-6`、本地医学 judge、双模型 disagreement workflow。

**Primary endpoints:** weighted kappa、macro F1、hazard 4-5 recall、MAE、calibration error。

**Ablations:** prompt variants、是否提供 modality/body part、是否提供 structured evidence、是否 reviewer。

**Deliverables:** confusion matrix、calibration plot、disagreement Sankey、critical misses table。

**Safety gate:** hazard 4-5 recall 未达到 0.90 时不得用于自动过滤或排序，只能作 review aid。

### Experiment E4：Radiologist Educational Study

**Primary question:** evidence-grounded feedback 是否提高报告质量且不引入新的临床错误？

**Design:** 随机交叉 pre/post reader study；washout；反馈条件与 control 条件平衡顺序。

**Primary endpoint:** 医生 adjudicated clinically significant error change。

**Secondary endpoints:** completion time、建议采纳率、helpfulness、actionability、trust、style preservation。

**Safety endpoints:** 新增错误数、越权诊断建议、无证据建议率。

**Statistics:** mixed-effects model，reader 和 case 为随机效应；报告效应量与 95% CI。

### Experiment E5：Validation of Image-to-text AI Models

**Primary question:** 各 modality 的 fresh report-generation 模型在临床错误、完整性和效率上如何比较？

**Rules:** 正式分析只含 `formal_fresh`；artifact/debug 单独补充表。

**Primary endpoint:** 每报告 clinically significant error count。

**Secondary endpoints:** omission/false finding、structure、preference、latency、GPU memory。

**Statistics:** paired case-level comparison；mixed-effects count model；多重比较使用 BH-FDR。

**Deliverables:** model forest plot、error composition、Pareto quality-latency、per-modality table。

### Experiment E6：Modality Recognition Study

**Primary question:** DICOM/series-first modality 和 body-part 路由是否足够可靠，VLM fallback 是否真正增加价值？

**Baselines:** suffix only、DICOM metadata、metadata+series rules、metadata+VLM fallback。

**Primary endpoints:** modality accuracy、body-part macro F1、unknown rate、routing error rate。

**Ablations:** 删除 DICOM tags、混合 series、非标准文件名、缺失 metadata。

**Deliverables:** confusion matrix、failure cases、fallback value plot、routing impact table。

### Task 6.1：将协议编码为可执行 experiment specs

**Files:**
- Create: `experiments/protocols/e1_radiologist_evaluation.yaml`
- Create: `experiments/protocols/e2_finding_extraction.yaml`
- Create: `experiments/protocols/e3_hazard_evaluation.yaml`
- Create: `experiments/protocols/e4_educational_study.yaml`
- Create: `experiments/protocols/e5_image_to_text.yaml`
- Create: `experiments/protocols/e6_modality.yaml`
- Modify: `src/medharness2/workflows/experiments.py`
- Test: `tests/experiments/test_protocols.py`

- [ ] **Step 1: 每份 YAML 固定 question、cohort、blinding、endpoints、statistics、figures、gates**
- [ ] **Step 2: `experiments run` 读取 YAML，不再把 protocol 硬编码在 Python dict**
- [ ] **Step 3: 缺少 gold labels 或 formal model 时状态为 `not_ready`，不得伪造结果**

### Task 6.2：实现统一统计分析层

**Files:**
- Create: `src/medharness2/statistics/bootstrap.py`
- Create: `src/medharness2/statistics/agreement.py`
- Create: `src/medharness2/statistics/mixed_effects.py`
- Create: `src/medharness2/statistics/multiplicity.py`
- Test: `tests/statistics/`

- [ ] **Step 1: 每个 estimator 返回 estimate、SE、CI、n、missingness 和 assumptions**
- [ ] **Step 2: 固定随机种子，bootstrap 以 case/reader cluster 为单位**
- [ ] **Step 3: synthetic data tests 验证已知效应和无效应情形**

---

## 11. W7：论文图表、结果冻结和发布

### Task 7.1：论文级 Figure pipeline

**Files:**
- Create: `src/medharness2/publication/figures.py`
- Create: `src/medharness2/publication/tables.py`
- Create: `config/publication.yaml`
- Modify: `src/medharness2/figures.py`
- Test: `tests/publication/test_figures.py`

- [ ] **Step 1: 映射 Notion 图表规划**

主文至少生成：系统总览、单例 evidence chain、finding graph alignment、反馈卡、judge validity、model comparison、reader distribution、education effect；另生成 dataset 和 metric taxonomy 表。

- [ ] **Step 2: 所有图从 frozen analysis JSON/CSV 读取**

禁止在绘图脚本中重新计算不同口径指标。

- [ ] **Step 3: 同时导出 SVG/PDF/300-dpi PNG 和 figure manifest**

- [ ] **Step 4: 自动检查空图、标签截断、颜色可辨性、样本数与 source table 一致**

### Task 7.2：一键正式复现

**Files:**
- Create: `Makefile.production`
- Create: `scripts/reproduce_formal_results.sh`
- Create: `scripts/verify_release.py`
- Create: `docs/reproduction.md`
- Test: `tests/test_release_verifier.py`

- [ ] **Step 1: 提供阶段化命令**

```bash
make -f Makefile.production preflight
make -f Makefile.production gold-validate
make -f Makefile.production benchmark
make -f Makefile.production experiments
make -f Makefile.production figures
make -f Makefile.production verify-release
```

- [ ] **Step 2: release verifier 检查所有 Definition of Done 证据**

缺少任一协议、gold labels、formal result、CI、figure manifest、hash 或安全扫描时返回非零。

### Task 7.3：最终质量门

- [ ] **Step 1: 代码验证**

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
ruff check src tests
mypy src/medharness2
```

- [ ] **Step 2: 前端验证**

```bash
cd frontend
npm ci
npm run lint
npm run test
npm run build
```

- [ ] **Step 3: 系统和安全验证**

```bash
python scripts/verify_release.py --release-dir outputs/formal_release
pytest tests/e2e -q
```

- [ ] **Step 4: fresh environment 复现**

在新环境或容器中从 frozen manifests 重建统计和图表；对比 artifact hashes，并生成 `reproduction_report.md`。

---

## 12. 测试金字塔和不可妥协规则

### 12.1 测试层级

1. Unit：纯函数、parser、normalizer、统计量。
2. Contract：每个 artifact schema、API OpenAPI、模型 JSON schema。
3. Golden：医生 gold labels、固定病例、固定模型 response fixtures。
4. Property：单位换算、alignment permutation、统计 estimator。
5. Integration：local model adapters、DMX synthetic requests、DB/task lifecycle。
6. End-to-end：从 manifest 到 workflow、experiment、figure、dashboard。
7. Release：正式 run hash、隐私扫描、fresh-only source policy、全产物完整性。

### 12.2 不可妥协规则

- 不把 mock、artifact reuse、debug fallback 写成 fresh model 结果。
- 不把 synthetic API smoke 写成医学有效性证据。
- 不在 test set 解盲后改主要终点、阈值或模型选择规则。
- 不向外部 API 发送原始患者数据。
- 不用单一自动指标宣称模型优于医生或另一模型。
- 不保存或展示模型私有 chain-of-thought；仅保存短、可审计 rationale 与 evidence IDs。
- 不在没有医生 gold labels 时把实验标为 validated。
- 不允许失败病例静默丢弃；必须进入 failure manifest 和 denominator。

---

## 13. 风险、缓解和升级条件

| 风险 | 早期信号 | 缓解 | 升级条件 |
|---|---|---|---|
| 医生标注不足 | kappa 低、缺 strata | 试标、修订指南、第三人 adjudication | 两轮试标仍低于门槛时暂停正式实验 |
| DMX 不稳定/模型漂移 | schema/评分变化 | response fixtures、日期/model ID、双 judge、fallback | schema success <99% 或 test-retest 降低 |
| PHI 外发 | canary 命中 | central privacy policy、hard block | 任一泄漏立即停用外部 role 并审计日志 |
| CT/MRI extractor 低质 | F1 未达门槛 | modality-specific medical model/hybrid | 无候选达标则标记 unsupported |
| 正式模型覆盖缺口 | 仍需 debug fallback | 扩充本地模型或缩小正式 claim | formal run 出现非 formal_fresh 即失败 |
| GPU 资源冲突 | OOM/长排队 | scheduler、memory class、checkpoint | 重复 OOM 进入模型 quarantine |
| 教育建议有害 | 新增错误/无证据 | evidence grounding、医生 review、template fallback | safety endpoint 超阈值即停用自动建议 |
| 统计功效不足 | CI 过宽 | power analysis、扩大 case/reader | 未达到预注册 n 不发表 superiority claim |

---

## 14. 推荐首轮执行批次

首轮只执行能够解除后续阻塞的任务，顺序如下：

1. Task 0.1 项目状态与决策日志。
2. Task 0.2 baseline manifest 与 verifier。
3. Task 1.1 Pydantic artifact contracts。
4. Task 1.2 外部 API privacy policy。
5. Task 2.1 gold-set annotation schema 和试标材料。
6. Task 2.2 extractor plugin interface，先迁移 CXR，再并行 CT/MRI。
7. Task 6.1 把六项实验协议从 Python 硬编码迁移到 YAML，并正确显示 readiness gate。

这七项完成后，报告生成 benchmark、judge 校准、动态控制面板可以并行推进；在此之前直接扩大模型调用或制作最终图表会放大数据口径和医学有效性风险。

### 14.1 并行工作流与预估周期

以下是以 2 名工程研发、1 名算法研发、至少 2 名放射科医生可间歇参与为假设的规划；医生招募和正式标注量决定实际关键路径。

| 周期 | 工程主线 A | 算法主线 B | 医学/研究主线 C | 阶段产物 |
|---|---|---|---|---|
| Week 1-2 | W0、contracts、privacy | extractor interface、metric definitions | 标注指南和 10 例试标 | baseline、schema v2 draft、pilot annotation report |
| Week 3-4 | provenance、run DB、local task backend | CXR/CT/MRI extractor candidates | 修订指南、冻结 dev/test split | extractor benchmark v1、privacy gate |
| Week 5-6 | FastAPI run control、Redis/RQ | alignment、judge benchmark | finding/hazard gold labeling | judge calibration dev report |
| Week 7-8 | React control panel、SSE、artifact viewer | report-generation formal benchmark | 模型盲评和 adjudication | formal model whitelist draft |
| Week 9-10 | workflow recovery、release verifier | education workflow、statistics | 教育研究 pilot | six executable protocols、pilot results |
| Week 11-12 | E2E hardening、deployment profile | frozen formal analyses | 正式实验执行/补标 | formal result bundles |
| Week 13-14 | reproduction run、文档 | publication figures/tables | 结果解读和医学审阅 | release candidate、论文图表 |

可并行项：W3 模型 benchmark 可在 W2 extractor 后半执行；控制面板可在 DB contract 冻结后并行；图表模板可提前开发，但正式数字只能读取 W6 frozen outputs。

关键路径：privacy/contracts -> gold annotation -> extractor/judge validation -> formal experiments -> frozen figures。任何工程并行都不能绕过这条研究质量链。

---

## 15. 计划覆盖审计

| 用户要求 | 对应章节 | 完成证据 |
|---|---|---|
| 从 demo 提升到高质量完整项目 | 1、3-12 | release verifier 全部通过 |
| 每个 tool 追求最佳实现 | 2、6 | tool gold metrics + benchmark report |
| 优先 DMX、API 用强模型 | 2.1、6.4、9.3 | DMX candidate benchmark 和 production route |
| 判断哪些用 API/医学模型/通用模型/代码 | 2 | 决策矩阵和 catalog/UI 展示 |
| 控制面板显示进度、I/O、tool 实现 | 8.1-8.4 | 动态控制面板 E2E tests |
| 完成 Notion 实验 | 10 | 六个 formal results bundle |
| 得出结果并可视化 | 10-11 | statistical reports、figures、tables |
| 本地报告生成模型 | 7 | readiness sync、fresh benchmark、formal whitelist |
| 可审计、可复跑 | 4-5、11 | hashes、registry、reproduction report |
| 医学安全和数据治理 | 5、9、12-13 | privacy scan、gold labels、safety endpoints |

本计划不把当前已通过的工程 smoke 当作最终研究结论；正式完成以第 1.2 节的十项证据为唯一口径。
