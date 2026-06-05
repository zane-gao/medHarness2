# medHarness2 本周工作汇报

汇报周期：2026-05-30 至 2026-06-06

## 一、工作背景

本周工作围绕 medHarness2 新系统落地展开。原始设计稿由洪学长提出，设计目标是围绕医学影像报告生成与评估，建立从人工报告、影像输入、AI 报告生成、单报告评估、Top-N 排序到 human-vs-AI 成对比较的闭环。

我的工作不是重新提出一套独立方案，而是在洪学长原设计基础上进一步完善系统边界、拆分关键接口、补齐工程实现，并用本机样本数据和已就位模型资源做落地验证。

## 二、基于原设计的完善

本周主要完成了以下设计收敛和工程化调整：

1. 将系统定位从单纯 CLI 调整为“核心 Python library + 薄 CLI/API 入口”。CLI 用于最小验证和批处理，后续可继续接 Web/API 平台。
2. 将云端 LLM/VLM 调用与本地报告生成模型解耦。`LLMClient` 负责评估、结构化解释、OCR 和 fallback；`ReportGeneratorRegistry` 负责本地复现模型、历史 artifact 和旧 medHarness runner。
3. 明确 Tool/Module/Workflow 边界。Tool5 负责候选报告对参考报告的图谱对齐和错误候选生成，Tool4 负责 hazard level 与解释，Tool7 作为 modality fallback。
4. 将样本数据流程扩展为完整链路：manifest 构建、PDF OCR cache、DICOM/体数据预处理、Workflow 1/2/3、运行校验和结果文档。
5. 明确模型来源：不只依赖 API，可使用本机已就位模型、历史 artifact、旧 medHarness fresh runner 和云端 fallback，并在 JSON 中记录来源和 warning。

## 三、本周实现进展

已在 `/data/isbi/gzp/medHarness2` 建立独立仓库，并完成多轮 checkpoint commit 与 push。当前系统已经包含：

- 标准 Python 包结构、配置加载、JSON I/O、mock/OpenAI LLM client。
- Tools 1-12：Likert 评估、报告 findings 抽取、结构检查、hazard 评估、图谱对齐、modality 识别、报告生成、Top-N、模型级/风险级/统计汇总。
- Modules：单报告评估与 human-vs-AI 成对比较。
- Workflows：单病例 Workflow 1、医生 vs 模型批量 Workflow 2、科室医生组 vs AI 模型组统计 Workflow 3。
- CLI：`single-case`、`sample-data`、`sample-full`、`batch-readers`、`department`、`validate-run`、`models list`。
- FastAPI 薄入口：复用同一套 Python workflow。
- 样本数据支持：读取 `/data/isbi/gzp/medHarness/data/sample_data_2026-06-05`，生成统一 manifest、OCR cache、PNG/NIfTI/contact sheet。
- 真实 OCR 支持：新增 `local_hf_vlm`，接入本机 `/data/cyf/shared_data/hd_data/qwen3-vl-4B`，完成 52 例扫描 PDF 真实 OCR cache。

## 四、本机模型资源落地

根据 `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md` 和旧项目配置，已接入以下本机资源路线：

- CXR artifact：`chexagent`、`llava_rad`、`r2gengpt`、`radialog_proxy` 等。
- CXR fresh：`maira_2`、`chexagent_srrg_findings_full` 等。
- 腹部 CT fresh：`merlin_fresh`。
- 脑 MRI fresh：`brain_gemma3d`。

本周解决了 MAIRA-2 调用链中的两个关键问题：

- 旧配置中的 `/data/miniconda3/envs/deepseek/bin/python` 当前 transformers 已变为 `5.9.0`，与 readiness 文档所需的 `4.48.2` 不一致；medHarness2 侧改用 `/data/miniconda3/envs/deepseek_2/bin/python`。
- medHarness2 派生图像路径原本为相对路径，旧 runner 在 `/data/isbi/gzp/medHarness` 下执行时找不到文件；现已统一传入绝对路径。

同时新增 batch 级 `medharness_cli` 调用：Workflow 2 对纯 fresh 本地模型请求按模型分组，一次性写多例 input JSONL，减少重复加载大模型；混合 fresh + artifact 请求仍保留逐例路径，避免漏掉 artifact 候选。

## 五、验证结果

已完成的关键验证：

- 单元与集成测试：`python -m pytest -q` 当前为 `85 passed, 19 warnings`。
- 语法/导入检查：`python -m compileall src tests` 通过。
- 52 例 artifact-only 全链路：52 例完成，Workflow 2 失败 0 例，Workflow 3 reader 数 6。
- MAIRA-2 单例 fresh smoke：`maira_2 / medharness_cli`，生成非空报告并进入 pairwise。
- MAIRA-2 52 例 batch：11 例 `cxr/chest` 走 MAIRA-2 fresh，41 例不匹配病例 fallback，失败 0 例。
- 双 CXR fresh 模型 smoke：`maira_2` + `chexagent_srrg_findings_full`，生成 2 个候选，Top-N 和 pairwise 均正常。
- MAIRA-2 batch-readers 2 例 CXR chest：一次 batch 调用，2 例均生成 `maira_2 / medharness_cli`，失败 0 例。
- MAIRA-2 真实 OCR batch-readers 2 例 CXR chest：基于 Qwen3-VL 4B OCR cache，2 例均生成 `maira_2 / medharness_cli`，Workflow 2/3 失败 0 例。
- CXR 真实 OCR 三 fresh 模型 11 例 batch：`maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings` 共生成 33 个 fresh 候选，Workflow 2/3 失败 0 例，质量门控失败 0。
- Merlin fresh 腹部 CT smoke：`merlin_fresh / medharness_cli`，生成非空腹部 CT 报告。
- Merlin 真实 OCR 腹部 CT 2 例 batch：基于 Qwen3-VL 4B OCR cache 和派生 NIfTI，2 例均生成 `merlin_fresh / medharness_cli`，Workflow 2/3 失败 0 例。
- Merlin 真实 OCR 腹部 CT 7 例 batch：完整 CT abdomen 子集均生成 `merlin_fresh / medharness_cli`，Workflow 2/3 失败 0 例，质量门控失败 0。
- BrainGemma3D 脑 MRI 初始 smoke：接口可跑通，但因 series 选择和 prompt 适配不足，输出曾出现 hip radiograph / chest-lung 内容；质量门控正确拦截，不进入 Top-N 和 pairwise。
- BrainGemma3D 真实 OCR 脑 MRI 7 例 batch：修正 MRI brain series 选择策略和 series-aware prompt 后，完整 MRI brain 子集均生成 `brain_gemma3d / medharness_cli`，Workflow 2/3 失败 0 例，质量门控失败 0。
- CT chest 真实 OCR artifact 7 例 batch：`ct_chat` 和 `dia_llama` 均走 `artifact_reuse`，Workflow 2/3 失败 0 例；其中 `ct_chat` 7/7 通过质量门控，`dia_llama` 7/7 因部位不匹配被拦截，不进入正式排名。
- 剩余 20 例无本地 report-trained 候选样本：使用本机 Qwen3-VL 4B 作为 `local_hf_vlm` fallback 跑通 `cxr/abdomen` 9 例和 `ct/head` 11 例，Workflow 2/3 失败 0 例；18/20 通过质量门控，2 例 head CT 输出胸部内容并被拦截。
- 最终 52 例 local-routed 合并目录：将 CXR fresh、Merlin fresh、BrainGemma3D fresh、CT chest artifact 和 20 例本地 VLM fallback 子批次合并为 `outputs/sample_data_2026-06-05_final_local_routed_52_20260606`；Workflow 1 JSON 52 个，Workflow 2/3 失败 0 例，`validate-run --require-real-ocr` 通过。
- 最终 52 例分析表：新增 `analyze-run`，输出 `case_routes.csv`、`model_source_summary.csv`、`reader_summary.csv`、`modality_body_part_summary.csv`、`quality_gate_failures.csv` 和 Markdown 摘要；当前统计为 52 例、81 条生成报告、72 条排名/pairwise、9 条质量门控失败。
- 基于真实 OCR manifest 的 Workflow 2/3 smoke：52 例、0 failed cases、6 个 reader；生成侧限定为 artifact reuse 且关闭 fallback，因此该运行是工程闭环，不是最终正式模型排名。

针对 BrainGemma3D 暴露出的质量问题，新增了轻量 modality/body-part 一致性门控，并进一步修正 MRI brain DICOM series 选择：优先 FLAIR，无 FLAIR 时优先 T2，否则回退最大 series；legacy runner prompt 会根据 `selected_series_type` 使用 FLAIR、T2 或 generic brain MRI prompt。明显 off-domain 输出会保留在 JSON 中并标记 `quality_gate_failed`，但不会进入 Top-N 和 pairwise 正式比较。

## 六、当前限制与风险

当前系统仍有以下限制：

- PDF 报告 OCR 默认配置仍是 mock provider；目前已补充 `local_vlm_cli` 和 `local_hf_vlm` 两条本地 VLM OCR 入口。旧项目 `qwen25vl_7b_instruct` 软链指向的 HF snapshot 缺失，dry-run 为 `debug_asset_missing`；已进一步接入 `/data/cyf/shared_data/hd_data/qwen3-vl-4B`，完成 52 例扫描 PDF 真实 OCR，并通过 `validate-run --require-real-ocr`。
- Tool2 的 CXR rule extractor 仍是 MVP 规则版，后续需要接更稳定的结构化抽取 backend。
- Tool4 hazard 仍是 MVP 规则估计，后续需要接 evaluator 或本地 LLM，并保留 deterministic fallback。
- BrainGemma3D 已在 7 例 MRI brain 子集上跑通并通过质量门控，但 2 例只能回退到 FGR 最大 series，且 NIfTI 生成存在 non-uniform sampling 警告；后续仍需加强 MRI spacing/orientation 处理。
- 当前 batch 优化只覆盖纯 `medharness_cli` 请求，后续可继续扩展到更多模型和更细的失败恢复机制。
- `local_hf_vlm` fallback 已能补齐 CR abdomen 与 CT head 的工程空白，但它不是 report-trained 报告生成模型；正式统计时必须和 MAIRA-2、Merlin、BrainGemma3D、CT-CHAT 等本机 report-trained/artifact 路线分开标记。

## 七、下周计划

下周建议按以下顺序推进：

1. 在真实 OCR manifest 基础上扩展 CXR fresh 小批量：MAIRA-2、CheXagent SRRG、MedGemma SRRG 多模型候选池。
2. 针对 BrainGemma3D 做 MRI spacing/orientation 核查，并考虑补齐 impression section 后处理。
3. 对无本地 report-trained 模型的 CR abdomen 与 CT head，继续保留 `local_vlm_fallback` 的 debug baseline，并寻找更匹配的本地 report-trained 模型或可复现路线。
4. 强化 Tool2 structured finding extractor，统一 observation、location、measurement、certainty、negation schema。
5. 为 FastAPI 增加 run id、状态查询和结果索引，为后续平台化做准备。

总体来看，本周已经在洪学长原始设计基础上完成了从设计文稿到可运行系统的关键落地：系统骨架、核心 workflow、样本数据入口、本机模型桥接、批量统计、质量门控和多类本机模型 smoke 均已形成闭环，为下一阶段真实 OCR 和正式批量实验打下了基础。
