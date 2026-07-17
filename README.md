# medHarness2

medHarness2 是一个用于评估放射学报告的研究型工具集。当前仍处于 pilot 阶段，默认配置适合
离线开发和结构验证；真实外部模型、临床标注和正式论文结果必须经过各自的证据门禁。

当前 MVP 实现了单病例工作流：

```text
人工报告 + 影像路径
  -> 生成 AI 报告
  -> 评估报告
  -> 对生成报告进行排序并选出 Top-N
  -> 将人工报告与 Top-N 报告进行比较
  -> 写入 JSON 结果
```

项目核心是 Python 库，CLI 覆盖单病例、样例数据、模型路由、批处理、OCR benchmark、临床标注
交接、实验和 dashboard 构建等入口。

主要工作流包括样例数据导入、逐页 VLM OCR、DICOM 资源准备、批量阅片者评估、科室级统计分析，
以及研究 manifest 和论文证据门禁。

报告生成可复用 `/data/isbi/gzp/medHarness`（A40 当前挂载点也可为
`/nfsdata_a40/isbi/gzp/medHarness`）下已经准备好的本地资源。medHarness2 会自动发现旧版
报告生成模型；云端 API、VLM 和本地产物均通过配置显式选择，不会在一次实验中静默切换 provider。

## 安装

```bash
cd /path/to/medHarness2
python -m pip install -e ".[test]"
```

样例数据的 DICOM/PDF 处理需要额外安装 `data` 依赖；单独部署 API 时可安装 `api` 依赖：

```bash
python -m pip install -e ".[test,data]"  # 样例数据与完整测试
python -m pip install -e ".[api]"         # FastAPI/uvicorn
```

文档中的 `/data/isbi/gzp/...` 是项目既有的数据与模型路径约定。如果部署环境的挂载点不同，
请在本地配置文件或命令行参数中替换为实际路径，不要将私有环境路径或凭据提交到仓库。

## 快速冒烟测试

```bash
cd /path/to/medHarness2
make smoke
```

默认情况下，MVP 使用 `config/default.yaml` 中配置的 `chexagent` 产物。这条快速冒烟路径会复用
已有的生成结果 JSONL，不会重新执行 GPU 推理。

如需测试旧版 medHarness 的即时生成适配器，请显式指定模型：

```bash
make smoke-maira2
```

如果当前机器使用 A40 的 NFS 挂载点，请把 Make 变量指向实际清单（`smoke-legacy-cxr` 同理）：

```bash
LEGACY_CXR_MANIFEST=/nfsdata_a40/isbi/gzp/medHarness/resources/smoke_data/cxr/manifest.jsonl make smoke-maira2
```

该流程会使用 `/data/isbi/gzp/medHarness/configs/reportgen_models.yaml` 中的模型设置，调用
`/data/isbi/gzp/medHarness/scripts/run_report_generation.py`。与默认的产物复用流程相比，
它可能需要更多 GPU 显存，运行时间也会明显更长。

## 样例数据流水线

医院样例数据运行器会生成清单、准备 DICOM 衍生资源、通过配置的 VLM/OCR 服务提取扫描版
PDF 报告文本，并将所有产物写入 `outputs/`。扫描 PDF 采用逐页管线，缓存带有来源和质量状态：

```bash
PYTHONPATH=src medharness2 workflow sample-data \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05
```

如只需低成本检查数据结构，可保留默认的 `llm.provider: mock`，或添加 `--skip-ocr`。
真实 OCR 可使用 OpenAI Responses、`chat_completions` 或本地 VLM；研究 OCR manifest 另提供可选
PaddleOCR-VL baseline adapter。云端凭据必须由环境变量提供。
PaddleOCR-VL 需要额外安装项目的 `ocr-paddle` extra，并按硬件安装匹配的 PaddlePaddle runtime：

```bash
python -m pip install -e ".[ocr-paddle]"
```
模拟 OCR 结果会带有 `mock_ocr_used` 标记；准备正式评估数据时应使用 `--require-real-ocr`，
避免把模拟文本误认为真实提取结果。只有现有 `.ocr.json` 缓存的来源信息与当前模式兼容时，
系统才会复用缓存；如需明确刷新报告文本缓存，请添加 `--force-ocr`。

基于生成的清单运行批量工作流和科室工作流：

```bash
PYTHONPATH=src medharness2 workflow batch-readers \
  --manifest outputs/sample_data_2026-06-05/manifest.jsonl \
  --output outputs/sample_data_2026-06-05/workflow2.json

PYTHONPATH=src medharness2 workflow department \
  --batch-result outputs/sample_data_2026-06-05/workflow2.json \
  --output outputs/sample_data_2026-06-05/workflow3.json
```

也可以用一条命令运行完整的样例数据流程：

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

该命令会写入 `manifest.jsonl`、`workflow2.json`、`workflow3.json` 和 `run_summary.json`，
随后执行验证门禁。

模型路由首先按三种主要成像模态（`cxr`、`ct`、`mri`）筛选本地生成器；`body_part` 只用于
候选排序，不会单独阻断模态兼容模型。不受支持的病例会使用配置的备用服务，
可以是本地 VLM、云端 VLM/API 或模拟服务。生成的 JSON 会记录准确的 `source` 和警告信息，
例如 `local_vlm_fallback_used`、`cloud_fallback_used` 或 `mock_fallback_used`。

运行前可查看兼容的本地生成器：

```bash
PYTHONPATH=src medharness2 models list --modality cxr --body-part chest
PYTHONPATH=src medharness2 models list --modality ct --body-part abdomen
PYTHONPATH=src medharness2 models list --modality mri --body-part brain
```

如需预览整个样例数据集的本地模型覆盖情况，同时避免运行 OCR、DICOM 转换或模型推理：

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local_route_plan \
  --dry-run \
  --all-compatible-local-models
```

如需避免启动 GPU 开销较大的即时生成模型，可将本地模型池限制为可复用产物：

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_artifact_only \
  --expected-cases 52 \
  --all-compatible-local-models \
  --model-source artifact_reuse
```

可以重复使用 `--model` 显式选择多个本地模型，例如：

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local \
  --expected-cases 52 \
  --model maira_2 \
  --model chexagent_srrg_findings_full \
  --model medgemma_srrg_findings \
  --model merlin \
  --model brain_gemma3d
```

在将样例数据运行结果用于评估前，请先完成验证：

```bash
PYTHONPATH=src medharness2 workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

正式的非模拟评估应添加 `--require-real-ocr`。该选项会检查每份报告文本缓存是否包含明确的
OCR 来源信息，并拒绝模拟或来源未知的 OCR 输出。

如果高成本的本地批处理按模态或身体部位拆分运行，可将通过验证的批次输出合并成一份可审计的
52 病例结果，无需重新运行模型：

```bash
PYTHONPATH=src medharness2 workflow merge-batches \
  --manifest outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr \
  --batch-result outputs/cxr_real_ocr_three_fresh_11_20260606/workflow2.json \
  --batch-result outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow2.json \
  --batch-result outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow2.json \
  --batch-result outputs/ct_chest_real_ocr_artifact_7_20260606/workflow2.json \
  --batch-result outputs/local_hf_fallback_remaining_20_qualityfix_20260606/workflow2.json
```

合并流程会写入 `workflow2.json`、`workflow3.json` 和 `run_summary.json`，并在
`workflow2_cases/` 下为每个病例复制一份工作流 1 JSON。

可从已完成的运行结果生成用于报告的 CSV 和 Markdown 摘要：

```bash
PYTHONPATH=src medharness2 workflow analyze-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --analysis-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
```

该命令不会重新运行 OCR 或报告生成，而是输出病例路由、模型与来源、阅片者、模态与身体部位，
以及质量门禁失败记录等表格。

也可以使用以下命令重复执行最终验证和分析：

```bash
make final-sample-check
```

历史设计到实现检查清单及 52 病例证据见
`docs/design_implementation_audit_20260606.md`；当前研究 gate、探索性结果和下一步以
`docs/research_pipeline_status_20260717.md` 为准。

启动高成本运行前可先做路由和 OCR provider preflight：

```bash
PYTHONPATH=src medharness2 workflow preflight \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output outputs/preflight.json \
  --all-compatible-local-models \
  --require-real-ocr \
  --config config/dmx_strong.yaml
```

preflight 会报告病例数、`cxr/ct/mri` 路由覆盖和 OCR primary/verifier readiness；缺少真实凭据或
运行时会返回 blocker，不会把 mock 配置当作 real OCR 就绪。

## 配置

`config/default.yaml` 将服务提供方的选择与代码分离：

- `llm.provider: mock`：默认使用，结果确定且可复现。
- `llm.provider: openai`：使用 `OPENAI_API_KEY` 调用 OpenAI Responses API；OpenAI 兼容代理使用
  `chat_completions`，本地路线可使用 `local_vlm_cli` 或 `local_hf_vlm`。
- `extractor.backend: auto`：按模态选择当前 CXR/CT/MRI 规则提取器；未知模态才回退到
  `placeholder`。
- `generator.local_models`：定义本地产物和即时 medHarness 适配器。

创建本地实验配置时，可复制 `config/example.yaml` 作为模板。

不要提交 API 密钥、GitHub 令牌、模型凭据或不应共享的私有路径。`docs/pat.txt` 已被有意忽略。

## 当前研究状态

截至 2026-07-17，项目仍是 `pilot_only`，当前状态以
`docs/research_pipeline_status_20260717.md` 和 `docs/project_status.yaml` 为准：

- 已从 52 例确定性筛选 10 例，`annotation/pilot10/` 已准备好 reader A/B 隔离交付；真实 reader 标注尚未开始（`0/10`）。
- 已用 Yunwu 的 Qwen VL 完成 MRI、CXR、CT 各 1 例探索性全链路；结果标记为 `exploratory_fresh`，不进入正式 benchmark 或论文统计。
- OCR winner 仍为 `blocked`：需要可用的真实 OCR provider、完整候选覆盖、两次重复运行和质量/一致性门禁；不能仅凭模型名称宣布 winner。
- 论文 formal gate 仍为 `blocked`；临床双读、OCR winner freeze 和 validated experiment 三类证据必须同时通过。

## 临床标注与 OCR 研究命令

先从已准备的 pilot 包交付隔离 reader 副本：

```bash
PYTHONPATH=src medharness2 annotation export-reader \
  --package-dir annotation/pilot10 \
  --output-dir /path/to/reader_a_package \
  --reader reader_a
```

管理员回收后运行校验和分析：

```bash
PYTHONPATH=src medharness2 annotation import-reader \
  --package-dir annotation/pilot10 \
  --reader-package-dir /path/to/reader_a_package \
  --reader reader_a
PYTHONPATH=src medharness2 annotation validate --package-dir annotation/pilot10
PYTHONPATH=src medharness2 annotation analyze \
  --package-dir annotation/pilot10 \
  --output outputs/research/20260717/pilot_annotation_analysis.json
```

生成 10 例研究 manifest 并执行两次 OCR 研究运行：

```bash
PYTHONPATH=src medharness2 research prepare-manifests \
  --pilot-dir annotation/pilot10 \
  --output-dir outputs/research/20260717
PYTHONPATH=src medharness2 research run-ocr \
  --pilot-dir annotation/pilot10 \
  --research-dir outputs/research/20260717 \
  --config config/dmx_strong.yaml
```

研究运行缺少真实 provider、源文件或质量证据时会明确保持 `blocked` 并返回非零；这不是成功的
OCR 结果。两次 benchmark 均完成且候选一致后，才执行 winner freeze：

```bash
PYTHONPATH=src medharness2 research freeze-ocr-winner \
  --research-dir outputs/research/20260717
```

论文总门禁会汇总 reader、OCR 和正式实验三类证据：

```bash
PYTHONPATH=src medharness2 research paper-gate \
  --research-dir outputs/research/20260717 \
  --annotation-analysis outputs/research/20260717/pilot_annotation_analysis.json \
  --experiment-results <validated-run>/experiments/results.json \
  --output outputs/research/20260717/paper_evidence_gate.json
```

`paper-gate` 或 `freeze-ocr-winner` 被阻断时不得绕过门禁生成正式结论。

## API 冒烟测试

```bash
PYTHONPATH=src uvicorn medharness2.api:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/workflow/single-case \
  -H 'Content-Type: application/json' \
  -d '{
    "report_text": "FINDINGS: No pneumothorax. IMPRESSION: No acute disease.",
    "image_path": "tests/fixtures/dummy.dcm",
    "output_path": "outputs/api_result.json",
    "modality": "cxr",
    "top_n": 1
  }'
```

## 验证

```bash
make test
```

前端静态页面的 Playwright 回归测试使用仓库锁定的 Node 依赖：

```bash
npm ci
npm run test:web
```
