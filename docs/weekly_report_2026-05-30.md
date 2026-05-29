# medHarness2 本周工作汇报

汇报日期：2026-05-30

## 一、工作背景

本周工作围绕 medHarness2 新系统落地展开。原始设计稿由洪学长提出，设计目标是围绕医学影像报告生成与评估，建立从人工报告、影像输入、AI 报告生成、单报告评估、Top-N 排序到 human-vs-AI 成对比较的闭环。本周工作的重点不是重新提出一套独立方案，而是在洪学长设计基础上进行工程化完善、范围收敛、关键接口拆分和 MVP 落地实现。

## 二、基于原设计的完善

针对设计稿中尚未完全定稿的部分，本周完成了三方面调整：

1. 将系统定位从“CLI 系统”调整为“核心 Python library + 薄 CLI/API 入口”。CLI 只作为最小验证和批处理入口，后续可平滑接入 Web/API 平台。
2. 将云端 LLM/VLM 调用与本地报告生成模型解耦。`LLMClient` 负责 OpenAI/mock 等评估和 fallback；`ReportGeneratorRegistry` 负责本地复现模型和旧 medHarness 生成入口。
3. 收敛 MVP 范围，仅保留单病例 Workflow 1 的核心闭环，将批量统计、复杂 workflow 和后续工具放到后续版本。

同时，对 Tool/Module/Workflow 边界做了进一步澄清：Tool5 负责候选报告与参考报告的图谱对齐及错误候选生成，Tool4 负责 hazard level 与解释；Tool7 作为 modality fallback，不强制每次识别。

## 三、本周实现进展

已在 `/data/isbi/gzp/medHarness2` 建立独立仓库，并完成多轮 checkpoint commit 与 push。当前系统已经包含：

- 标准 Python 包结构、配置加载、JSON I/O、mock/OpenAI LLM client。
- MVP tools：Likert 评估、报告 findings 抽取、结构检查、hazard 评估、图谱对齐、modality 识别、报告生成、Top-N 排序。
- MVP modules：单报告评估与 human-vs-AI 成对比较。
- MVP workflow：`single-case`，可从人工报告和影像路径出发生成 AI 报告、评估、排序并输出 nested JSON。
- CLI 入口：`medharness2 workflow single-case`。
- 工程化入口：`make test`、`make smoke`、`make smoke-legacy-cxr`、`make smoke-maira2`。
- FastAPI 薄入口：`POST /workflow/single-case`，复用同一套 Python workflow。

在本地模型衔接方面，已完成两条路径：

- `chexagent` artifact 复用：作为默认快速 smoke 路径，读取已有 generation JSONL，避免每次加载大模型。
- `maira_2` fresh adapter：通过旧项目 `/data/isbi/gzp/medHarness/scripts/run_report_generation.py` 调用真实生成流程，实现 medHarness2 到旧 medHarness 模型资源的桥接。

## 四、验证结果

本周完成了以下验证：

- 默认 CLI smoke：`generated_reports=1`，`pairwise=1`。
- 旧 medHarness CXR manifest artifact smoke：`generated_reports=1`，`pairwise=1`。
- `maira_2` fresh smoke：完整运行 1 例 CXR 样例，退出码 `0`，耗时 `48` 秒，生成报告 1 份，完成 pairwise comparison 1 次。
- 单元与集成测试：当前 `make test` 覆盖语法检查和 pytest，最近一次结果为 `26 passed`。
- API 测试：FastAPI TestClient 可跑通 `/workflow/single-case`，缺少报告输入时返回 4xx。

本周还修正了 Tool5 对齐语义：现在明确以 candidate report 对 reference/human report 对齐，candidate-only 记为 `false_finding`，reference-only 记为 `omission_finding`，precision/recall 分母也按 candidate/reference 语义修正，避免后续实验和论文解释混乱。

## 五、当前状态与风险

当前 MVP 已能形成核心闭环，但仍有以下风险需要后续继续处理：

- Tool2 的 `cxr_rule` 仍是规则抽取器，只适合 MVP 和 CXR smoke；后续需要接入更稳定的结构化抽取 backend。
- Tool4 hazard 目前是 MVP 规则估计，后续需要接 OpenAI evaluator 或本地 LLM evaluator，并保留 deterministic fallback。
- `maira_2` fresh smoke 已跑通 1 例，但还不是批量稳定性验证；后续需在更多病例上评估失败率、耗时和显存占用。
- FastAPI 当前是薄入口，尚未加入任务队列、运行状态管理、权限控制和 Web UI。

## 六、下周计划

下周建议按以下顺序推进：

1. 扩展本地模型 registry，将旧项目 readiness 文档中已就绪的 1-2 个稳定模型接入 medHarness2。
2. 强化 Tool2 findings extractor，优先固定 observation、location、measurement、certainty、negation 的 schema。
3. 将 `maira_2` fresh smoke 扩展到小批量病例，记录运行耗时、失败原因和输出质量摘要。
4. 为 FastAPI 增加 run id、结果文件索引和基础状态查询接口，为后续平台化做准备。
5. 整理一版面向论文复现的实验 manifest 与结果汇总格式，支持后续模型间比较。

总体来看，本周已经完成了从设计稿到可运行 MVP 的关键跨越：在洪学长原始设计的基础上，完成了设计收敛、系统骨架、核心 workflow、旧模型资源桥接、真实 smoke 验证和 API 入口，为后续批量实验和平台化奠定了基础。
