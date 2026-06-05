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

- 单元与集成测试：`python -m pytest -q` 当前为 `69 passed`。
- 语法/导入检查：`python -m compileall src tests` 通过。
- 52 例 artifact-only 全链路：52 例完成，Workflow 2 失败 0 例，Workflow 3 reader 数 6。
- MAIRA-2 单例 fresh smoke：`maira_2 / medharness_cli`，生成非空报告并进入 pairwise。
- MAIRA-2 52 例 batch：11 例 `cxr/chest` 走 MAIRA-2 fresh，41 例不匹配病例 fallback，失败 0 例。
- 双 CXR fresh 模型 smoke：`maira_2` + `chexagent_srrg_findings_full`，生成 2 个候选，Top-N 和 pairwise 均正常。
- MAIRA-2 batch-readers 2 例 CXR chest：一次 batch 调用，2 例均生成 `maira_2 / medharness_cli`，失败 0 例。
- Merlin fresh 腹部 CT smoke：`merlin_fresh / medharness_cli`，生成非空腹部 CT 报告。
- BrainGemma3D 脑 MRI smoke：接口可跑通，但输出出现 hip radiograph 内容，已标记为接口 smoke，不作为正式质量结果。

针对 BrainGemma3D 暴露出的质量问题，新增了轻量 modality/body-part 一致性门控。明显 off-domain 输出会保留在 JSON 中并标记 `quality_gate_failed`，但不会进入 Top-N 和 pairwise 正式比较。

## 六、当前限制与风险

当前系统仍有以下限制：

- PDF 报告 OCR 默认仍使用 mock provider 缓存；目前已补充 `local_vlm_cli` 本地 VLM OCR 入口，可调用旧项目中的本地 VLM adapter。当前 `qwen25vl_7b_instruct` 软链指向的 HF snapshot 缺失，dry-run 为 `debug_asset_missing`，因此正式评测前仍需恢复本地 VLM 权重或改用云端 VLM，并通过 `validate-run --require-real-ocr`。
- Tool2 的 CXR rule extractor 仍是 MVP 规则版，后续需要接更稳定的结构化抽取 backend。
- Tool4 hazard 仍是 MVP 规则估计，后续需要接 evaluator 或本地 LLM，并保留 deterministic fallback。
- BrainGemma3D 虽然接口可跑通，但本批样本输出存在部位语义跑偏，需要进一步核对真实输入预处理、模型适配和质量门控。
- 当前 batch 优化只覆盖纯 `medharness_cli` 请求，后续可继续扩展到更多模型和更细的失败恢复机制。

## 七、下周计划

下周建议按以下顺序推进：

1. 先修复 `qwen25vl_7b_instruct` 本地权重路径，或配置云端 VLM；随后完成真实 OCR，重跑 52 例样本并通过 `--require-real-ocr` 校验。
2. 扩展 CXR fresh 小批量：MAIRA-2、CheXagent SRRG、MedGemma SRRG 多模型候选池。
3. 对 Merlin fresh 扩展腹部 CT 小批量，记录耗时、失败率和输出质量。
4. 针对 BrainGemma3D 做输入预处理核查和质量门控增强，决定是否进入正式候选池。
5. 强化 Tool2 structured finding extractor，统一 observation、location、measurement、certainty、negation schema。
6. 为 FastAPI 增加 run id、状态查询和结果索引，为后续平台化做准备。

总体来看，本周已经在洪学长原始设计基础上完成了从设计文稿到可运行系统的关键落地：系统骨架、核心 workflow、样本数据入口、本机模型桥接、批量统计、质量门控和多类本机模型 smoke 均已形成闭环，为下一阶段真实 OCR 和正式批量实验打下了基础。
