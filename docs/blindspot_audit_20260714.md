# medHarness2 盲区扫描报告（2026-07-14，2026-07-15 修复增量）

> 本文档是 2026-07-14 的历史审计快照，后续增量记录当前修复状态；原始发现保留用于追溯，不应直接当作当前代码事实。

> **2026-07-15 执行增量**：已完成 OCR 逐页管线、可注入的 audit-only 多模态 verifier、三模态软部位路由、Likert 归一化、统计白名单/小样本区间、并列百分位、鲁棒 JSON 解析、fallback/mock 统计过滤、参考图 recall、seed/cache、Retry-After 和非 CXR observation slug 规范化。北川数据集按当前工程约定直接作为金标准数据源；API/敏感产物硬化按用户指示暂不作为本轮阻塞。以下清单仍保留原始审计事实，已修复项以当前代码和测试为准。

> **修复状态**：H5、H9、H10、H11、H12、H14、H15、H17、M1、M2、M3、M6 已有代码与回归测试证据；Tool1 显式 mock judge 现在也标记 `fallback_used=true`，不会进入正式统计。H7 已完成小样本 t 区间；H8 已接入正式 benchmark summary 的 Welch+Holm 统计，但真实冻结结果仍需执行。H13 已把 seed/route 纳入 checkpoint 输入，并明确 checkpoint reuse 不等于重复实验；仍需真实重复运行验证。M7 已支持 hazard reviewer 的配置化重测摘要（原始 reviewer 保留、重测次数与一致率入合约并进入 checkpoint 指纹）；M10 的 hazardwise 汇总现在也过滤 fallback/mock hazard 行。M12 已提供 gated live judge smoke，但当前因缺少 `DMX_API_KEY` 返回 `blocked`；C1/H1-H4 按用户指示暂缓。

> **2026-07-16 增量**：M4（Tool2 宽泛异常）、M5（报告文本 prompt 边界）、M9（失败病例分母）、M10/M11/M13（fallback provenance）和 M7 的 Tool1 重测记录已补代码与测试。H8 新增 Welch 近似比较与 Holm 校正 API，并已接入正式 benchmark summary；样本不足的比较标为 blocked。H6 的排名 cutoff 近似并列候选现在会一并保留并标记 `near_cutoff`；此外，batch/reevaluate/merge 三条 reader 聚合路径已统一使用 `(likert-1)/4`，不再与排名口径漂移；真实分析仍必须在冻结数据上运行并记录方法。

> **当前未完成门禁**：真实北川 OCR 候选 benchmark、真实多模态 verifier smoke、临床 pilot10 标注、在真实冻结结果上执行的统计分析和 gated live judge smoke。当前环境的 `live-smoke` 因 `DMX_API_KEY` 缺失返回 `blocked`；OCR benchmark 对缺失 manifest 也返回 `blocked`，因此不能标记为已完成。

> **门禁实现增量（2026-07-16）**：新增 `medharness2 ocr-benchmark` 和 `medharness2 live-smoke`。前者在 gold/candidate 缺失时返回 `blocked`，后者在凭据缺失时返回 `blocked`；两者都不会把缺失、mock 或 fallback 计为成功。
> **2026-07-16 收尾增量**：`tool11_hazardwise` 统一过滤 `fallback_used`、`mock`、`debug_fallback`、`mock_fallback`、`fallback` 和 `local_vlm_fallback` 来源，避免低证据 hazard 行进入加权汇总；旧 finding graph 迁移缺失观察内容时改为显式 `unparsed_legacy_finding`，对齐层拒绝其作为真实观察配对；全量回归测试为 385 passed。
> **2026-07-16 后续增量**：OCR preflight 现在识别 `chat_completions`/DMX 等 OpenAI 兼容 provider，并在凭据存在时报告为可执行，而不再误报 `unsupported_llm_provider_for_ocr`；OCR `require_real` 缓存门禁和核心执行路径都只接受明确支持的真实 provider，未知 provider metadata 或直接调用都不能绕过门禁；OCR 现在跳过确定性全白页、保留稀疏有效页并记录页级墨量/跳过原因；OCR verifier 失败/非法响应只记录审计警告，不会改写或拖垮主 OCR；Tool4 hazard 的 observation/location 已与对齐层统一优先 canonical code；这只是能力门禁，不代表真实 OCR 质量已验证。全量回归测试更新为 391 passed。
> **2026-07-16 后续增量**：`dmx_strong.yaml` 已提供 Doubao Seed 候选主 OCR（`ocr_primary`）和独立 Qwen OCR verifier（`ocr_verifier`）路由；两者只作为冻结 benchmark 候选，不能据模型名称直接宣布 winner。多页 OCR verifier 现在按原始 PDF 页码逐页抽查，保留页级审计结果及 verifier provider/model/role provenance；`validate-run --require-real-ocr` 与 OCR 核心统一真实 provider 白名单，未知 provider 不再被误计为真实 OCR；Tool1 增加解释 grounding 诊断字段，但不自动改分。全量回归测试为 401 passed、18 warnings。
> **2026-07-16 OCR 评测收尾增量**：OCR provenance 新增 `source_page_count`/`retained_page_count`，保留旧 `page_count` 兼容；候选 benchmark 现在拒绝不等覆盖、重复 case-model 行后再选 provisional winner。旧 OCR sidecar 缓存仍可兼容复用，专用 OCR role 继续严格校验模型路由；preflight 现在透传 role 模型到本地 CLI/HF 能力检查。
> **2026-07-16 抽取收尾增量**：规则抽取去重不再把缺失/非法 measurement 隐式转换为 `0.0`；未知 measurement 与明确 `0 mm` 保持可区分，新增 CXR 回归测试覆盖该边界。该修复不改变既有 finding schema 或路由接口。
> **2026-07-16 聚合输入收尾增量**：显式提供空的 workflow2 `cases`/`failed_cases` 或 workflow3 `reader_percentiles` 时，不再被历史兼容默认值绕过一致性校验；manifest 中合法但非对象的 JSONL 行现在保留真实行号并 fail-closed。全量回归测试为 504 passed、18 warnings。
> **2026-07-16 统计分母收尾增量**：department、analyze-run 和实验摘要现在保留显式 `0` 的 source/success/failure/reader 计数，不再使用 `or` 把合法零值误判为缺失并回退到病例行数。全量回归测试为 509 passed、18 warnings。
> **2026-07-16 validation 收尾增量**：`validate_sample_run` 现在保留显式 `summary.case_count=0`，与非空 manifest 的冲突会明确记录，不再被 `or len(manifest_rows)` 覆盖。全量回归测试为 509 passed、18 warnings。
> **2026-07-16 实验摘要收尾增量**：image-to-text 实验摘要保留上游显式 `generated_report_model_counts`，即使值为 0 也不再被 CSV 行数覆盖；全量回归测试为 510 passed、18 warnings。
> **2026-07-16 模态摘要收尾增量**：实验模态识别摘要保留显式空 `modality_counts`，不再从病例行自动推导并掩盖“无上游证据”的状态；全量回归测试为 512 passed、18 warnings。
> **2026-07-16 legacy provenance 收尾增量**：旧版本地报告生成器现在透传调用方的 `case_id` 到 legacy input overlay，不再把不同病例统一写成 `medharness2_single_case`；新增集成断言覆盖该 provenance 绑定。
> **2026-07-16 OCR benchmark 键规范化增量**：候选 benchmark 的 coverage 检查现在与评测主循环统一清理 model key 两端空白，避免同一模型因 manifest 格式差异被误报为覆盖不一致；全量回归测试为 512 passed、18 warnings。
> **2026-07-16 OCR 就绪/截断语义增量**：兼容模式 preflight 在真实 OCR 未就绪时保留 `passed=true` 但新增 `ocr_not_ready:<blocker>` warning，避免被误读为全链路 ready；主 OCR 截断检测与 benchmark 的终止标点语义对齐，完整中文报告不再因缺少英文栏目名被误报截断。真实 52 例 preflight 复跑为路由 52/52、fallback 0，同时明确 `ocr_not_ready:missing_llm_api_key`。全量回归测试为 516 passed、18 warnings。
> **2026-07-16 validation 一致性增量**：`validate_sample_run` 的 workflow2/workflow3 计数一致性检查保留显式零值，不再用 `or 0` 改写缺失与合法零的区别；全量回归测试仍为 514 passed、18 warnings。
> **2026-07-16 dashboard 统计一致性增量**：控制面板摘要和最终 KPI 渲染层现在保留显式 `case_count`、`reader_count`、`experiment_count`、`figure_count` 和质量计数的零值，不再被 stale analysis 或旧图表列表覆盖；全量回归测试为 516 passed、18 warnings。
> **2026-07-16 formal benchmark 统计一致性增量**：正式 benchmark 的 T5 adjudication 与 T4 hazard agreement summary 现在保留显式 0 计数，不再把 0 次比较/同意错误推导成 hazard error 数量；全量回归测试为 517 passed、18 warnings。
> **2026-07-16 验证账本收尾增量**：补充显式空聚合数组/百分位映射的失败测试，并为多个非对象 manifest 行保留实际 JSONL 行号；当前全量回归为 516 passed、18 warnings。该收尾只强化本地验证边界，不改变外部真实证据门禁状态。
> **2026-07-16 评委输入边界增量**：Tool1/Tool2 对外部评委 prompt 的报告文本增加长度上限、头尾保留和明确的 quoted-data 边界；Tool2 prompt/stage 版本升级为 `tool2-hybrid-v3`，避免 checkpoint 将新旧提示词混用。全量回归测试为 410 passed、18 warnings。
> **2026-07-16 统计汇总增量**：Tool12 纳入 reader-level `overall_score`；Workflow3 department 输出补齐 source/success/failure 分母及成功率、失败率，避免 reader 统计只呈现分数而丢失失败病例分母。全量回归测试为 412 passed、18 warnings。
> **2026-07-16 排名语义增量**：Tool9 近 cutoff 候选仍保留供复核，但不再把它们标成正式 `selected_top_n`；新增 `near_cutoff_review` 区分复核候选，避免 analyze/education 下游误把不确定候选纳入正式 Top-N。
> **2026-07-16 verifier/门禁增量**：OCR verifier 对非 JSON object 响应统一记为 audit warning，不影响主 OCR；`validate-run` 增加 OCR case/hash/截断 provenance 回归覆盖。全量回归测试为 416 passed、18 warnings。
> **2026-07-16 严格缺失数据增量**：带源 PDF 的 OCR 验证现在区分 VLM 页级质量与合法 `pdf_text_layer`；batch/reevaluate 对真实缺失报告不再生成伪造占位文本，非严格 mock 流程仅保留显式“Report text unavailable”工程占位；LLM 非可重试 HTTP 错误不再盲目重试。全量回归测试为 418 passed、18 warnings。
> **2026-07-16 OCR role 占位隔离增量**：batch reader 仅在顶层 mock 且未配置 `ocr_primary` 时允许工程占位；一旦存在专用真实 OCR role，缺失报告会明确失败，不会被占位文本掩盖。全量回归测试为 419 passed、18 warnings。
> **2026-07-16 重测一致性增量**：Tool4 hazard reviewer 现在保留每次重测的 provider/model/role/fallback provenance；任一重测走 fallback 时一致性统计明确标记 `debug_fallback`/`blocked`，不再把兜底结果当作真实稳定性证据。全量回归测试为 422 passed、18 warnings。
> **2026-07-16 聚合合约增量**：新增 workflow2/workflow3 聚合结果的兼容型 Pydantic 合约，并接入 `validate_sample_run`；reader、denominator、percentile 和计数字段畸形时明确失败，同时允许历史分析字段增量扩展。版本化 schema 已重新导出。全量回归测试为 423 passed、18 warnings。
> **2026-07-16 聚合一致性增量**：聚合合约进一步校验成功/失败分母、成功率/失败率、病例行数与读者 percentile 数量的一致性，避免“类型正确但统计自相矛盾”的结果进入分析。全量回归测试为 424 passed、18 warnings。
> **2026-07-16 pilot10 验收增量**：新增 `medharness2 annotation validate`，逐病例校验 annotation contract、manifest 对齐、reader_a/reader_b/adjudication 顺序和真实完成状态；前端改用 validator 结果计算完成数。当前 `annotation/pilot10` 实测为 `not_started`，0/10 完成，不再仅信任 manifest 声明。全量回归测试为 429 passed、18 warnings。
> **2026-07-16 标注 CLI 门禁增量**：`annotation validate` 退出码现在区分完整（0）、未完成（1）和结构/状态阻断（2）；自动化任务不会再把 `not_started` 当成成功校验。
> **2026-07-16 统计缺失值增量**：department/analyze reader 汇总不再把缺失或非法 `overall_score` 默认填成 0；此类 reader 从统计群体排除并写入 `excluded_readers`，CSV 保留空值。全量回归测试为 431 passed、18 warnings。
> **2026-07-16 OCR/ranking/annotation 深度门禁增量**：OCR sidecar 现在绑定 `case_id`；Tool9 缺失配置指标的候选不再按 0 分排名，而是排除并等待完整指标；pilot10 validator 增加路径越界、重复/未列出文件、候选数和“未开始但已有内容”检查。全量回归测试为 435 passed、18 warnings。
> **2026-07-16 教育/兼容性增量**：教育反馈优先使用 reader 统计，缺失时从病例级 `human_metrics` 重建；没有可用统计才 blocked，不再用 0 伪造同行基线。pilot 包重建会清理 stale 病例文件；legacy 单行 artifact 无 case_id 时保持兼容，多行歧义则阻断；损坏 pilot manifest 在前端显示 blocked。全量回归测试为 441 passed、18 warnings。
> **2026-07-16 教育 Likert 增量**：Workflow 4 报告级教育反馈不再把缺失、空值或非法 Likert 分数当作 0；部分有效分数只基于有效项计算，完全缺失时返回 `blocked_insufficient_data`，避免虚构最低弱项和总分。新增缺失/非法输入回归测试。
> **2026-07-16 面板证据增量**：后端已排除缺失 `overall_score` 的 reader 后，发现控制面板模板仍会用 `Number(value) || 0` 把缺失分数显示为 0。现已统一保留 `null`，并让 reader 表格和图表只展示有效分数；真实 0 分仍保留。新增 dashboard 回归测试；当前全量回归为 449 passed、18 warnings。
> **2026-07-16 百分位展示增量**：继续发现有效综合分但缺失 `percentile` 时会被模板渲染为 `P0`。现已改为显示不可用标记，真实百分位（包括真实 0）仍保留，新增回归测试。
> **2026-07-16 pilot 输入增量**：`build_pilot_annotation_package` 现在严格校验 `workflow2.json` 中每个 `workflow1_output` 引用：缺失文件或非法 JSON 会带病例 ID 和路径明确失败，不再静默跳过或冒泡无上下文解析异常。全量回归测试为 452 passed、18 warnings。
> **2026-07-16 legacy 面板增量**：旧版 `web/legacy/control_panel.html` 也统一修正 reader 的缺失分数/百分位展示，避免历史入口继续把缺失值渲染成 0 或 P0；新增静态回归测试。
> **2026-07-16 OCR benchmark 输入增量**：冻结 OCR manifest 中若 `gold_text` 或 candidate 声明了文件路径但文件不存在/不可读，现在会记录 `missing_gold:*` 或 `missing_candidate:*` 并将 benchmark 标记为 `blocked`；内联文本仍按文本处理。补充 4 个回归场景，全量回归测试为 457 passed、18 warnings。
> **2026-07-16 OCR/标注/面板闭环增量**：pilot10 现在拒绝缺失、不可读或空的临床参考报告，不再用 finding graph 片段替代参考文本；OCR sidecar 统一按 case/source/provider/model/role 绑定，模型变更必须重新 OCR；盲区解析器兼容当前“修复进度与剩余优先级”标题及 MEDIUM 列表格式。全量回归测试为 462 passed、18 warnings。
> **2026-07-16 OCR cache 语义增量**：进一步锁定 cache 合约：同一 case/source/provider/model/role 才可复用，模型切换必须重新 OCR；新增模型变更回归测试，修复了旧 default cache 兼容逻辑过宽导致的 stale OCR 风险。全量回归测试为 463 passed、18 warnings。
> **2026-07-16 pilot 候选完整性增量**：pilot10 构建器和 validator 现在拒绝没有任何 `generated_reports`/`candidate_reports` 的病例；空候选任务不再被包装成可开始的临床标注包，前端会显示 `blocked`。全量回归测试为 464 passed、18 warnings。
> **2026-07-16 pilot 文本完整性增量**：validator 进一步拒绝空的 `reference_report` 和空的 candidate `report_text`，避免手工/历史包把没有真实阅读材料的任务误计为 `not_started`。全量回归测试为 465 passed、18 warnings。
> **2026-07-16 pilot 标识完整性增量**：validator 现在拒绝重复的 `candidate_id` 或 `blinded_model_id`，避免读者 hazard 归属和后续统计出现歧义。全量回归测试为 466 passed、18 warnings。
> **2026-07-16 pilot provenance 增量**：`source_case_sha256` 现在对 canonical source case payload（稳定 JSON）计算，而不是只对病例 ID 计算；同一 ID 的源内容变化会产生新 hash，新增 source-drift 回归测试。全量回归测试为 467 passed、18 warnings。
> **2026-07-16 reader 统计收尾增量**：batch/reevaluate/merge 的 reader 聚合继续过滤 fallback/mock 证据；Workflow3/API 额外保留完成 reader 总数与统计有效 reader 数，避免 mock 测试或失败证据被纳入均值时误报“没有 reader”。全量回归测试为 468 passed、18 warnings。
> **2026-07-16 合约收尾增量**：`workflow3_aggregate` schema 现在显式包含 `reader_total_count`，并校验其不小于统计有效 reader 数；单病例入口同时保留显式 `case_id` 到产物与 input 的绑定，避免输出文件名意外覆盖病例身份。相关验证已补回归测试。
> **2026-07-16 隐私/OCR 收尾增量**：annotation 候选文本继续统一走临床脱敏；结构化 `source_case_sha256` 由公共隐私扫描器作为不透明 provenance 元数据处理，避免哈希数字片段被误判为手机号/身份证；OCR sidecar 缺少 `case_id` 时不再复用缓存。全量回归测试为 473 passed、18 warnings。
> **2026-07-16 最终验证增量**：补齐 API 与单病例入口的显式 `case_id` 传递、旧第四位置 `report_text` 兼容回归，并校验 reader 总数/有效统计数合约；最终全量回归为 474 passed、18 warnings。
> **2026-07-16 路由与门禁收尾增量**：`default_models: ["*"]` 现在会真正展开三模态兼容候选；完整 52 例 `dmx_strong` preflight 验证 52/52 本地候选、0 fallback。live-smoke 拒绝 mock/deterministic/fallback provider，即使存在 API key 也不发起调用；损坏 UTF-8 OCR manifest 明确 blocked；CLI single-case 显式 `case_id` 参数已补齐。全量回归测试为 479 passed、18 warnings。
> **2026-07-16 统计鲁棒性增量**：Tool9/Tool10/Tool12 以及 Welch/Holm 统计路径现在过滤 NaN、正负无穷和非法 p 值；非有限观测不再污染排名、均值、比较或多重校正。当前全量回归测试为 494 passed、18 warnings。
> **2026-07-16 OCR manifest 完整性增量**：OCR candidate benchmark 现在拒绝空白 model key；sidecar 的 case/model provenance、损坏编码和缺失路径均明确阻断，不会产生可误读的 succeeded/winner。当前全量回归测试为 499 passed、18 warnings。
> **2026-07-16 hazard/OCR 最终门禁增量**：Tool11 hazard 加权汇总同步过滤 NaN、正负无穷指标；OCR sidecar provenance 现在同时校验 `case_id` 与 `model_key/model/model_name`。全量回归测试保持 499 passed、18 warnings；当前本地 52 例 `dmx_strong` 路由 preflight 为 52/52 有兼容候选、0 fallback，但真实 OCR/DMX 凭据缺失仍保持 blocked。
> **2026-07-16 reader provenance 增量**：reader `overall_score` 现在复用 Tool 12 的 fallback/mock provenance gate；全 fallback reader 返回 `null`，Workflow 3 记录 `excluded_readers`，不再把兜底结果或 0 分伪装成可比较的 reader 百分位。reader 等权 pooled mean 与 Tool 9 的 `0.4/0.3/0.3` 候选排名权重仍明确区分。
> **2026-07-16 reader 计数增量**：department 输出的 `reader_count` 现在只统计有有效 `overall_score` 的 reader，并单独记录 `excluded_reader_count`，避免 reader 总数与 percentile/统计群体不一致。
> **2026-07-16 兼容/标注安全增量**：恢复 `run_single_case` 历史第四个位置参数作为 `report_text` 的兼容语义；pilot 包重建在已有标注或无效包时拒绝删除旧病例文件；损坏 manifest 继续以 blocked 状态展示。全量回归测试为 443 passed、18 warnings。
> **2026-07-16 hazard 聚合增量**：`tool11_hazardwise` 不再把缺失 `error_type`/`hazard_level` 的记录默认成未知权重或最低风险；不完整记录会被排除并等待补齐。全量回归测试为 444 passed、18 warnings。
> 方法：8 维度并行代码审计（62 个 agent）+ **对抗性验证**（每条发现派独立"怀疑者"读真实代码反驳），关键项由主审人逐行复核。
> 统计口径：原始 54 条发现 → 验证后 **1 CRITICAL / 17 HIGH（去重后）/ 13 MEDIUM / 6 LOW**，另有 **4 条已核实为非缺陷**、**4 条被驳倒删除**。
> 严重度以对抗性验证的 `adjusted_severity` 为准——**比"直觉严重度"低**是因为验证者反复确认：多数缺陷真实存在，但**只在 benchmark 之外的路径 / mock 配置 / 误配下触发**，不影响那次权威跑。

---

## 0. 一句话结论

跑 `config/dmx_strong.yaml` 的**权威 benchmark 那次跑是干净的**——`workflows/benchmark_evaluation.py` 的
`_validate_role_routes`（7 个角色必须全是真实、非 mock、带凭证）+ `verify_real_llm_case_evaluation`
（拒绝任何 `fallback_used=True`、mock provider、校验 SHA-256 链）双重硬门禁，把下面所有 mock/fallback 泄漏路径都挡住了。

**但除它以外的所有工作流**（`reevaluate-run` / `single-case` / `department` / 任何用 `config/default.yaml`
或缺 model_roles 的配置）**没有这层门禁**，能让伪造分数冒充真评委。该历史问题的统计聚合部分已修复：当前 batch/reevaluate/merge/tool9/tool10/tool12 路径会过滤 fallback/mock provenance；非 benchmark 工作流仍可能使用 mock 配置，因此结果不能自动升级为正式模型质量结论。
问题不在"流程能不能跑通"，而在"benchmark 之外跑出来的数字能不能作为模型质量结论"。截至 2026-07-16，统计聚合已过滤 fallback/mock 行，单样本 CI 不再伪装为零宽区间；教育工作流也已明确区分真实 LLM、mock judge 与 deterministic fallback。剩余问题仍需按下方门禁继续处理。

---

## 1. 先纠正 4 个已过时 / 错误的既有认知

经对抗性验证，这些旧说法**已不成立**，避免按错误前提决策：

| 旧说法 | 实际情况 | 证据 |
|---|---|---|
| `llm_client` 只支持 OpenAI Responses API | 早已实现 `chat_completions`，codex/DMX 代理走这条，多模态 + per-call 换 key/model，且有单测 | `llm_client.py:106-183`；`tests/test_llm_client.py:45-159` |
| LLMClient 会静默 fallback 到 mock | **不会**。provider 'mock' 仅在显式配置时用；所有真 provider 失败一律 raise `LLMClientError`。fallback 逻辑在 tools 层且受 `allow_fallback` 控制 | `llm_client.py:44-45,104,153` |
| `docs/pat.txt` 是"提交进仓库的密钥" | **从未提交**（在 `.gitignore`，`git log --all` 查无记录）。真实风险是**明文密钥躺在组内可读的共享 NFS 上** | `git ls-files docs/pat.txt` 为空 |
| mock 评委污染了权威 11-case 跑 | 那次 `"fallback_used": true` 出现 **0 次**。风险是**潜伏的**（工具默认值 + 统计不过滤），非那次已发生 | `outputs/benchmarks/cxr_chest_qwen3vl8b_11_v1_20260711/` grep |

> "54 处 `print()` 应改 logging"也是**误报**：所有 `print()` 都在 `cli.py` 面向用户输出（错误走 stderr），
> `tools/` `workflows/` `modules/` 评测核心 0 处 `print()`。

---

## 2. 🔴 CRITICAL（1 条）

### C1. FastAPI 全部端点无鉴权 + 任意文件读写（路径穿越）
- **位置**：`api.py:33`（`app=FastAPI` 无 auth）、`:223-251`（single_case）、`:498-530`（education）
- **缺陷**：所有路由零 `Depends`/`Security`/`HTTPBearer`/中间件（三个文件 grep 全空）。
  `SingleCaseRequest` 收调用方传的 `report_path`（任意读，:229 → `single_case.py:42` 无约束 `read_text`）
  与 `output_path`（任意写，:232-241 → `utils/io.py:27-30` `mkdir(parents=True)`+`write_text`），无 `project_root` 白名单。
- **失败场景**：未鉴权客户端可
  (a) `report_path=/etc/passwd`/PHI 文件 → 内容进 HTTP 响应 `result`（api.py:250）外泄；
  (b) 任意写文件；(c) 触发外部 LLM 烧代理 key + 把 PHI 推给第三方；(d) 伪造 `results.json`/registry。
- **验证**：CONFIRMED，无任何 guard 反驳。**且 `README.md:208` 与 `docs/mvp_usage.md:86` 都指示
  `uvicorn ... --host 0.0.0.0`**——文档本身就规定了这个可达配置。是唯一保住 CRITICAL 的条目。

---

## 3. 🟠 HIGH（去重后 17 条）

> 去重说明：CI z=1.96（原 5 个维度都点名）合并为 H7 一条；mock/fallback 伪造分（多维度重复）合并为 H9/H10 两条。

### —— 安全 / 隐私（4 条，全部 confirmed）——

**H1. 原始放射报告（含 PHI）明文发第三方代理，评测链路零去标识**
`tool1_likert.py:44-50`、`tool2_extract.py`、`tool6_structure_diff.py`，由 `single_report.py` 驱动。
`deidentify_clinical_text()` 在评测路径**从未被调用**（仅 benchmark_generation / annotation 用）。
OCR 缓存（`ocr.py:65`）落盘原文实测含"报告医生：楚辰辰 / 审核医生：王小波 / 住院号 / 床号"。
每次 judge/extract/structure-diff 都把带名病历发去 `DMXAPI.cn`。
> 验证降级注记：finder 原评 CRITICAL，验证者降为 HIGH——因为它取决于 `enforce_external:false` 这个配置选择（见 H2），而非无条件发生。但结合 H2 已确认权威跑正是在门禁关闭下进行，PHI 确实被送出。

**H2. 所有 "strong" 配置关掉隐私门禁** `dmx_strong.yaml:16` 等 7 个配置
`enforce_external:false` + `block_external_images:false`。`llm_client.call`（:35）仅当 `enforce_external=True`
才调 `validate_external`（唯一发送前 PHI 扫描）。**产生可发表数字的正是这些配置**，运行时无任何 PHI 未外发保证。

**H3. 隐私策略自相矛盾：门禁开则真评测全崩，门禁关则 PHI 裸奔**
`privacy.py:73-82` vs `config.py:89-91` vs 核心工具的 `classification="raw_clinical_text"`。
默认白名单不含 `raw_clinical_text` → `enforce_external=true` 时第一次真评委就 `PrivacyViolation`。
**不存在"真评测 + 被扫描/去标识"的配置态**（无人在调用前去标识 raw_clinical_text）。运营方被迫翻 false，隐私保护实际提供零保护。

**H4. PHI 产物 + 明文密钥在共享 NFS 上组/世界可读**
`outputs/`（`drwxrwxr-x`，1087 个文件含 住院号/报告医生/审核医生，`ocr.py:65` + `manifest.raw.jsonl` 存真实医生姓名）；
`docs/pat.txt`（`-rw-rw-r--`，4 个 LLM key + GitHub PAT + HF + Kaggle）。128 核共享机上任何同租户可读，无加密、无脱敏/留存策略。

### —— 统计有效性（历史发现；当前代码已修复，真实冻结结果仍待执行）——

**H5. 排序把"最差分"当"最好分" + x/5 归一化整体错标** `tools/tool9_rank.py:34`
`float(v)/5.0 if v>1 else v`：likert_mean=**1.0（1–5 最差）** 时 `1.0>1` 假 → 原样 1.0 → 与满分 5.0（5/5=1.0）**相同**；断崖 1.0→1.0 vs 1.01→0.202。
> 验证降级注记：完全反转需恰好落在边界 1.0（罕见），故降为 HIGH。但验证者补充：**x/5 对 1–5 量表本身就是错的**（应为 (x-1)/4），把所有 Likert 压进 0.2–1.0，**即使不在边界，排序也被系统性扭曲**——这条比"边界 bug"更普遍。主审人已逐行复核。

**H6. `select_top_k` 只按点估计均值硬切，无方差/CI/并列处理** `tools/tool9_rank.py:21`
N=11 下 0.72 vs 0.71（差在抽样噪声内）被严格排序，0.72 进 pairwise、0.71 丢。`tool12` 的 CI 代码存在但**从不被 tool9 调用**。从噪声造确定性赢家。

**H7. 置信区间的小样本与单样本语义**（原 5 维度重复，合并）`tools/tool12_statistics.py:16-17`
历史实现对所有 N 使用固定 z=1.96，且 `n==1` 时把 CI 写成均值本身。当前代码已改为小样本保守 t 临界值，并在 `n=1` 时输出 `ci_lower/ci_upper=null`；正式结果仍需确保下游展示层正确解释 null。

**H8.（当前已接入，真实冻结结果仍待执行）正式汇总尚未消费显著性检验与多重比较校正** `tools/tool12_statistics.py:84-114`
正式 benchmark summary 已调用 Welch 近似比较与 Holm 校正；样本不足时写入 `blocked_reasons`。当前仍缺真实冻结结果，因此不能把已有代码输出升级为最终临床统计结论。

### —— mock/fallback 泄漏（2 条，confirmed）——

**H9.（历史发现，当前已修复标记）mock/确定性 Likert 冒充"非 fallback 判断"漏进所有非 benchmark 工作流**
`tool1_likert.py:38,61-62,78-117`（+ `tool4` DEFAULT_HAZARD `:20-27`，+ `allow_fallback=True` 默认 `tool1:30`/`tool4:57`）
`default.yaml` 是 `provider: mock` 无 model_roles → `require_llm=False`。`_deterministic_likert` 纯启发式
（base 3；≥20 词 +1；同含 finding+impression 再 +1），25 词垃圾报告带俩标题 = 5/5 全维。历史版本曾把 mock 标为 `fallback_used=False`；当前 Tool1 显式 mock judge 已标记 `fallback_used=true`，并被正式统计过滤。
CLI `reevaluate-run`/`single-case` 不带 `--config` 默认吃 `default.yaml`（`cli.py:666`）。**权威 benchmark 因双重门禁免疫，其余工作流无门禁。**

**H10.（历史发现，当前已修复聚合部分）聚合层丢弃 provenance，fallback/mock 行与真 LLM 行同等平均，benchmark 外无 `fallback_count`**
`tool12/tool10/tool9 的 _numeric_metrics` 只留数值，丢 `_metadata`/`fallback_used`；`batch_readers.py:76`/`merge_batches.py:171`
无 `evidence_tier=='debug_fallback'` 过滤。`single_report.py:122-131` 把 likert 降成裸 float，fallback 标记只留在嵌套 dict，**不进统计**。全 fallback 的 reader 也照样和真分算 percentile。

### —— 科学有效性（1 条，历史发现；排名口径已修复）——

**H11.（历史实现，当前已修复）`finding_coverage` = 发现数/本体大小，不是召回，却占排序/质量分约 1/3** `tools/tool2_extract.py:294-296`
抽取器仍会保留 `finding_graph.coverage` / `template_coverage.coverage_rate` 作为“模板覆盖诊断”字段，便于解释规则抽取质量；但这些字段不再进入模型排名。`single_case.py` 会在候选与北川参考 finding graph 对齐后，将 `composite_inputs.finding_coverage` 设置为 reference recall，因此排名口径不再是本体大小分母。
3 发现简洁正确报告=3/26≈0.115；提 10 类（对错不论）冗长报告≈0.385。**系统性奖励啰嗦、惩罚简洁准确**，且幻觉发现类别也计数。
> 我第一版误标 MEDIUM，验证结论为 HIGH——因为它直接进 `select_top_k`（权重 0.3）与 overall_score，扭曲排名和 reader percentile。

### —— 复现性（2 条，confirmed）——

**H12.（历史发现，当前已修复传输层）LLM 请求从不传 `seed`——temperature=0 单独不保证可复现** `llm_client.py:116-126`
当前 Responses API 与 Chat Completions 路径都会在配置提供时传递 `seed`，并纳入 checkpoint route fingerprint；但 provider 仍可能不承诺比特级确定性，因此仍需真实重复运行验证。

**H13. checkpoint reuse 不是独立重复实验**（已缓解但仍需外部验证）
当前 checkpoint 输入已包含 route、temperature、seed、schema/config 指纹，且支持 `--no-resume` 强制重跑。它能保证同一输入下的缓存完整性，但不能证明模型在独立调用中的随机稳定性；删缓存或关闭 resume 后仍需真实重复运行并报告差异。

### —— LLM 集成（2 条，confirmed）——

**H14.（历史发现，当前默认配置已修复）`hazard_reviewer` 省略 temperature → 非确定性 reviewer 污染它本要测的一致率**
`dmx_strong.yaml:43`（`omit_temperature:true`）+ `llm_client.py:120-121`。
primary=gpt-5.6-terra@temp0，reviewer=claude-opus 走默认 ~1.0。`review_hazards` 算的 agreement 混了模型家族差异 + 温度差异 + 真噪声。
重跑同一 benchmark 得到不同 `agreement_summary`。
> 当前 `config/dmx_strong.yaml` 已明确配置 reviewer 的 `temperature: 0.0` 与 `seed: 0`；仍需真实 provider smoke 验证该模型对这些参数的兼容性，并记录必要的参数省略。

**H15.（历史发现，当前已修复）`parse_json_object` 只能剥"整段就是围栏"的 JSON** `utils/io.py:33-44`
当前解析器在标准 JSON/Markdown fence 失败时会切片首个 `{` 到末个 `}` 再重试，并有对应回归测试；真实模型仍需通过 gated smoke 验证。

### —— 测试覆盖（1 条，confirmed）——

**H16.（当前已补行为回归测试）Tool7 模态识别曾缺少真实行为测试** `tools/tool7_modality.py:10-27`
现已覆盖 DICOM header 优先、常见图像后缀、VLM MRI/空回复归一化，并继续保留未知模态为 `unknown` 的显式行为。

### —— 数据/schema 一致性（1 条，confirmed，第一版整个维度漏了）——

**H17.（当前已修复规范化）`observation_code` 对非 CXR 是原始 LLM 自由文本，却被当精确匹配 join 键**
producer `tool2_extract.py:508` → consumer `alignment/scoring.py:11`。
v2 里 `finding_pair_score` 要求 `observation` 字符串完全相等才允许配对，且优先取 `observation_code`。
当前 Tool2 对所有非 CXR 模态也生成稳定 lowercase slug（空格/连字符归一化），解决同一文本因大小写/标点导致 join 失败的路径。不同语义词（如 `hepatic_cyst` 与 `liver_cyst`）仍需 ontology 或临床标注确认，不能仅靠 slug 解决同义词映射。

---

## 4. 🟡 MEDIUM（13 条）

- **M1.（当前已修复）`model_count` 注入指标字典污染 `calculate_statistics`** `tool10_modelwise.py:17`→`tool12:38`。
  modelwise dict 无 metrics/composite_inputs 键 → 兜底吃整行 → "这个 case 有几个模型"被算出 mean/CI 摆在真指标旁。
  （注：tool10 自己的 `_numeric_metrics` 有 skip-set，tool12 没有。）
- **M2.（历史发现，当前已修复）`percentile_rank` 用 `<=` 含自身，小样本上偏** `tool12:33`。当前使用 midrank 口径。
- **M3.（历史发现，当前已修复）`calculate_statistics` 缺 metric 白名单** `tool12:38`。当前仅消费明确的统计指标键。
- **M4.（当前已修复）tool2 的异常捕获曾过宽** `tool2_extract.py:111`。
  当前仅捕获 LLMClientError、ValueError、TypeError 和 JSON 解码错误；KeyError/AttributeError 等代码 bug 不再被静默当作评委瞬时错误。
- **M5.（当前部分修复）被评报告文本嵌进评委 prompt，仅靠一句"treat as data"防注入**（partly）`tool1_likert.py:143-154`。
  json 编码和不可信数据边界防住基础指令注入；现在每个解释附带诊断性的报告词汇覆盖率与 `ungrounded_explanation` 标记，供审计发现脱离报告的解释，但不自动改分。临床 grounding 仍需真实评委与冻结数据验证。
- **M6.（当前已部分修复）传输重试曾忽略 `Retry-After` / 限流信号** `llm_client.py:131-153,94-104`。
  当前 429 会读取 `Retry-After`，传输异常会安全使用指数退避；正式运行仍需记录重试与最终失败分母。
  > 注："accounts exhausted"作 HTTP≥400 或 200-body-error **能被正确 surface** 并抛 LLMClientError，**无静默 mock 替换**——弱点仅在退避策略。
- **M7.（历史发现，当前已支持配置化重测）单样本评委，全项目无自一致/多数投票**（partly）`tool1_likert.py:41-71`、`tool4:80-102`。
  每个指标是 n=1 抽样，方差从不采样。（`max_retries=1` 时一次调用一抽样。）
- **M8.（历史配置风险，当前 strong 配置已修复；默认配置仍明确是 mock）顶层 `provider: mock` 是 strong 配置的隐患** `dmx_strong.yaml:5`。
  当前 `config/dmx_strong.yaml` 顶层 provider 已是 `chat_completions`，并由 `DMX_API_KEY` 门禁；`config/default.yaml` 仍保留 mock 作为本地离线开发默认值，调用方必须显式选择 strong 配置或 `require_llm`，不能把默认 mock 结果当正式质量结论。
- **M9.（当前已修复汇总可观测性）失败 case 被踢出统计造成幸存者偏差** `reevaluate_run.py:73`、`batch_readers.py:65`。
  batch/reevaluate 保留 manifest/source 分母、成功率和失败列表；`analyze_run` 现在进一步输出 `source_case_count`、`successful_case_count`、`success_rate` 和 `failure_rate`，并写入分析 Markdown。成功病例均值仍只描述成功子集，失败率必须作为独立 endpoint 一并报告。
- **M10.（当前已修复 provenance；模板本身仍是低证据 fallback）Hazard 回退到硬编码 DEFAULT_HAZARD 常量却标非 fallback** `tool4_hazard.py:20-27,435-457`。
  无 hazard_primary 角色或评委失败时仍会使用模板等级，但结果明确标记 `implementation_type=deterministic_fallback` 与 `fallback_used=true`，不会进入正式统计；模板等级本身不能替代临床验证。
- **M11.（当前已修复 provenance，仍需真实 smoke）Workflow4 education 的 LLM 路径曾无法区分 LLM/模板** `education.py:64,103,108-120`。
  当前结果已用 `llm_judge`、`mock_judge`、`deterministic_fallback` 区分来源；真实 provider smoke 仍未执行。
- **M12.（当前有 gated smoke，真实调用仍 blocked）无真实评委调用的测试，坏评委能过 CI 绿灯** `tests/test_tools.py:1487-1527`。
  常规 CI 仍使用 stub，不主动访问外网；但 `live-smoke` 已提供真实 provider/JSON 门禁。当前缺少 `DMX_API_KEY`，所以该 smoke 只能返回 blocked，不能宣称真实评委连通性已验证。
- **M13.（当前已修复评估门禁）mock fallback 产出可打分的伪报告而非拒绝** `tool8_generate.py:53-64`。
  产物仍保留用于诊断并明确标记 `evidence_tier=mock`；质量门禁现在把 fallback generation 标为失败，Tool9/Tool10 也排除 `mock`/`mock_fallback` 行，不再进入排名或模型汇总。

---

## 5. 🔵 LOW（6 条，均 partly——机制真实但影响被验证者判为轻微）

- **L1. Placeholder/无发现的 provenance 警告在 LLM 修正后被抹掉** `tool2_extract.py:303-308`。
  但 `metadata.llm_correction.candidate_backend='placeholder'` 仍保留（信号被搬走非删除），故降 LOW。
- **L2. Hazard 一致率跨模型跨温度对比**（大部分被驳倒）`tool4_hazard.py:188-196`。
  机制真实（见 H14），但"被当可靠性/复现性汇报"被驳倒：字段诚实叫 `agreement`、下游无人消费、真实复现数字来自 T1 test-retest（`decision_log.md:76-77`）。仅温度不对称的轻微噪声，只会**过度触发** adjudication（安全方向）。
- **L3.（当前已修复）`fallback_count` 在评测总结里硬编码 0** `benchmark_evaluation.py:888,524`。
  当前 summary 从每个成功结果的 `llm_verification.fallback_count` 汇总，单个验证 artifact 也从实际 provenance 计算；若未来出现 fallback，会进入 summary 而不是被硬编码掩盖。
- **L4.（当前已修复）旧 finding graph 迁移曾把缺失观察内容伪造成 `reported_finding`** `contracts/migrations.py:230-251`。
  现在缺失观察内容会显式标记 `unparsed_legacy_finding`、写入 `migration_metadata.observation_unparsed` 和 `legacy_finding_missing_observation` 警告；对齐层拒绝该占位作为真实观察配对，相关回归测试已覆盖。
- **L5.（当前已修复）字段偏好不对称：确定性匹配器用 `*_code`，LLM hazard 评委曾看 `*_text`** `scoring.py:58-73` vs `tool4_hazard.py:577-580`。
  Tool4 现在与对齐层统一优先 `observation_code`/`anatomy_code`，最终 hazard 结果也会回填 canonical 字段；原始 finding/candidate/reference 仍保留用于追溯。
- **L6. 死掉的 v1 字段兜底（observation/location/measurement/id）** `scoring.py:61,70,117`、`audit.py:260,263`、`education.py:318,326`。
  对已校验 v2 数据是永不触发的死代码。"掩盖 schema 漂移"被驳倒——所有路径先过 `FindingGraph.model_validate`（`extra='forbid'`），杂散 v1 键会在上游 raise。纯清理性死代码，不会污染数字。

---

## 6. ✅ 已核实的"非缺陷"（severity=none，避免误伤）

| 项 | 结论 | 证据 |
|---|---|---|
| 权威 benchmark 路径 | **未被 mock/fallback 污染**，硬门禁完备 | `_validate_role_routes`(:585-633) + `verify_real_llm_case_evaluation`(:349-531) 双重 gate；两信号（implementation_type + fallback_used）独立校验 |
| LLMClient chat_completions | **完整实现且有单测**，无静默 mock | `llm_client.py:49,106-183`；`test_llm_client.py:45-159`（端点覆盖/超时/温度省略/403 结构化错误/key 不泄漏） |
| tool12 除零/空组 | **安全**，无崩溃 | `stdev` 有 `len>1` 守卫、`ci` 有 `if values`、`percentile_rank` 有 `if not population`、`tool10:16` 有 `totals>0`、`tool9:12` 有 `sum(weights) or 1.0` |
| GPT 角色 temperature=0 | **确实生效** | `config.py:64-82` 放行 0.0，`llm_client.py:120-121` 发送；seed、reviewer 温度配置已落地，仍需真实 provider 验证兼容性 |

---

## 7. ❌ 被对抗性验证驳倒 / 删除的 4 条（不要当作待办）

- **~~Raw medical images base64 上传外部代理~~**：被驳倒/合并——图像外发受 `block_external_images` + `enforce_external` 控制，与 H1/H2 同源，不单列。
- **~~`_count_workflow1` 静默吞掉读不了的文件~~**（`merge_batches.py:147`）：**我第一版曾列为 HIGH（旧 H11），已删除**——对抗性验证找到守卫，判为不成立。
- **~~迁移从不读旧 `source` 字段丢失 v1 source 文本~~**：被驳倒。
- 一条 chat_completions 的重复 stale 纠正：并入第 1 节，不单列。

---

## 8. 修复进度与剩余优先级（截至 2026-07-16）

### 2026-07-16 增量：面板显式区分验证通过与 OCR 就绪

- `src/medharness2/dashboard.py::_render_health_strip` 新增 OCR readiness chip：优先展示 preflight 提供的 `validation.ocr.status/blocker`；没有 provider 级证据时，仅在 `require_real_ocr=true` 且逐例计数为全真实、无 mock/unknown 时显示“运行证据 ready”，其余显示“OCR 就绪状态未知”。
- 新增 `tests/test_web_panel.py` 回归，覆盖 `validate-run passed` 不得伪装 OCR ready，以及 `missing_api_key` 阻断原因必须可见。
- 该改动只改善证据呈现，不改变 OCR 主链、路由结果或任何统计值。

### 2026-07-16 增量：修正项目账本工作树状态

- `docs/project_status.yaml::baseline.dirty_worktree` 与实际 Git tracked 状态重新对齐为 `false`；`.serena/` 仍作为用户已有未跟踪目录保留，不纳入仓库发布。
- `tests/test_project_metadata.py` 增加该状态契约，避免前端长期显示已提交代码仍处于 dirty 的误导信息。
- `web/build_panel.py` 现在忽略其自身的 `web/index.html` 生成差异后再判断 dirty，避免正常重建页面造成自引用的脏状态；其他 tracked 文件改动仍会被报告。

### 2026-07-16 增量：preflight 拒绝空病例输入

- `workflow preflight` 现在对“目录存在但没有可发现病例”的输入返回 `passed=false`，并记录 `no_cases_discovered`；此前空目录可能被误报为 `passed=true, cases=0`。
- 新增 `tests/test_preflight.py::test_preflight_blocks_existing_but_empty_sample_root`，确保输入路径错误或空数据集不会被当作路由通过。

### 2026-07-16 增量：空白凭据不再伪装为已就绪

- OCR preflight 与 `live-smoke` 的凭据判断现在会对环境变量做 `strip()`；仅由空格、换行或制表符组成的值按缺失处理。
- 新增 preflight/live-smoke 回归测试，避免状态先显示 ready、随后真实调用才失败的门禁漂移。
- 正式 benchmark 的 role route gate 与 `LLMClient` 两个实际调用入口也同步拒绝空白凭据，避免门禁层和传输层判断不一致。

### 2026-07-16 增量：batch-readers 拒绝空 manifest

- `workflow batch-readers` 对空 `manifest.jsonl` 现在写入 `errors=["no_cases_discovered"]`，CLI 返回退出码 1；此前会输出 `cases=0 readers=0` 并返回 0。
- 有病例但全部病例处理失败仍保留 `failed_case_count` 和失败分母，不与空输入混淆。
- 新增 workflow 层和 CLI 层回归测试，避免“未发现输入”被当作成功运行。

### 2026-07-16 增量：benchmark run 退出码跟随结果状态

- `benchmark run` 不再无条件返回 0；探索性 benchmark 的 `failed` 或 `completed_with_failures` 现在返回退出码 1，只有 `succeeded` 返回 0。
- 新增空 manifest CLI 回归，避免没有任何 benchmark 结果时 CI/自动化任务误判为成功。

### 2026-07-16 增量：department 拒绝空 batch

- `workflow department` 对 `case_count=0` 且 `failed_case_count=0` 的空 workflow2 产物现在写入 `errors=["no_cases_discovered"]` 并返回 CLI 退出码 1。
- 有病例但读者统计为空仍保留原有统计结果，不会被误判为无输入。
- 新增 workflow 层和 CLI 层回归测试。

### 2026-07-16 增量：analyze-run 拒绝空工作流输入

- `workflow analyze-run` 对 workflow2/workflow3 都为零病例且没有失败病例的输入，现在在分析 JSON 中记录 `errors=["no_cases_discovered"]`，CLI 返回退出码 1。
- 正常有病例的分析结果不变；新增空输入 CLI 回归测试，避免全零分析被误当成成功运行。

### 2026-07-16 增量：education blocked 状态传播到 CLI

- `workflow education` 遇到 `blocked`/`blocked_insufficient_data` 时现在返回退出码 1；正常生成建议仍返回 0。
- 新增缺失 reader 统计的 CLI 回归，避免“没有可生成建议”被自动化任务误判为成功。

### 2026-07-16 增量：reevaluate/merge 空输入 fail-closed

- `workflow reevaluate-run` 对源 workflow2 没有任何病例且没有失败病例的情况，现在在 `run_summary.json` 与 CLI 汇总中记录 `errors=["no_cases_discovered"]`，并返回退出码 1；此前仅检查失败病例数，空源运行会被误报为成功。
- `workflow merge-batches` 的空 batch 回归已补齐：即使能生成空 workflow2，验证层也必须阻断，不允许 `cases=0` 的产物进入通过状态。
- `validate_sample_run` 对存在 workflow2 且 `case_count=0, failed_case_count=0` 的运行统一增加 `no_cases_discovered` 错误；合法的显式零值统计仍不受影响。
- 新增 CLI 回归测试；本轮全量回归为 `534 passed, 18 warnings`。

### 2026-07-16 增量：sample-data/sample-full 空源 fail-closed

- `workflow sample-data` 对不存在或没有可发现病例的样本根目录现在生成空 manifest 但返回退出码 1，并在 registry 中标记 failed；不再让 `cases=0` 的数据准备任务伪装成功。
- `workflow sample-full --dry-run` 对同类输入写入 `errors=["no_cases_discovered"]`，路由计划和 registry 均标记失败，CLI 返回退出码 1。
- 样本清单构建器统一处理“不存在目录”和“存在但为空”两类输入，避免底层 `FileNotFoundError` 绕过统一门禁。

### 2026-07-16 增量：single-case 无生成候选 fail-closed

- `workflow single-case` 在没有任何生成器、且关闭 cloud fallback 时，不再把空报告占位当成成功结果；case artifact 写入 `errors=["no_generated_reports"]`。
- CLI 与 run registry 对该状态统一返回/记录失败；启用合法 fallback 或存在有效候选的既有路径保持不变。
- 新增单病例 CLI 回归；本轮全量回归为 `537 passed, 18 warnings`。

### 2026-07-16 增量：experiments run 缺少源运行阻断

- `experiments run` 对不存在的源运行目录或缺少 `workflow2.json` 的输入现在写入明确错误（`run_dir_not_found` / `workflow2_not_found`），并以非零退出码结束。
- 有效源运行但实验仍处于 pilot/not_ready 的情况保持原有协议展示语义，不会因为“尚未达到正式研究门禁”而误报为执行错误。
- 新增 CLI 回归；本轮全量回归为 `538 passed, 18 warnings`。

### 2026-07-16 增量：benchmark plan 未就绪状态传播

- `benchmark plan` 现在仅在计划状态为 `ready` 时返回 0；`not_ready`（例如无正式候选、输入资产缺失或病例覆盖不足）返回非零。
- 计划 JSON 仍完整保留 blocking violations，便于诊断和后续修复；本改动只修正自动化退出码语义。
- 新增 CLI 回归；本轮全量回归为 `539 passed, 18 warnings`。

### 2026-07-16 增量：annotation build-pilot 空源阻断

- `annotation build-pilot` 对不存在的源运行目录或没有可发现病例的目录现在明确失败（`run_dir_not_found` / `no_cases_discovered`），不会生成空 pilot 包并返回成功。
- 已有标注包重建保护、隐私扫描和 `annotation validate` 状态语义保持不变。
- 新增 CLI 回归；本轮全量回归为 `540 passed, 18 warnings`。

### 2026-07-16 增量：API 状态与 registry 对齐

- `/workflow/single-case` 现在在没有生成候选时返回摘要错误 `no_generated_reports`，并将对应 registry 条目标记为 `failed`；HTTP 请求格式仍保持 200，便于调用方读取结构化业务结果。
- `/experiments/run` 对缺少源运行目录或 `workflow2.json` 的结果同步返回错误摘要，并将输出目录与源目录的 registry 条目标记为 `failed`，不再固定写成 passed。
- 新增 API 回归；本轮全量回归为 `542 passed, 18 warnings`。

### 2026-07-16 增量：API 工作流摘要补齐阻断状态

- `/workflow/sample-data`、`sample-full`、`batch-readers`、`department`、`merge-batches`、`analyze-run` 和 `preflight` 的响应摘要现在统一暴露 `errors`/`blockers`，调用方无需再深入读取产物才能判断空输入或验证失败。
- `/workflow/education` 的 `blocked` / `blocked_insufficient_data` 状态现在在响应中明确返回，并将 registry 条目标记为 failed；正常建议生成仍保持 passed。
- 新增字段只补充状态可见性，不改变 HTTP 请求兼容性或既有成功数据结构。

### 2026-07-16 增量：图表/仪表盘源输入门禁

- `figures build` 对不存在的实验目录或缺少 `results.json` 的输入现在返回明确错误并写入 failed registry，不再让底层异常或空图表流程被误判为成功。
- `dashboard build` 对不存在的运行目录统一返回非零并记录失败；summary 与 HTML 生成都在输入可用后才执行。
- 新增 CLI 回归；本轮全量回归为 `544 passed, 18 warnings`。

### 2026-07-16 增量：schema 迁移空源阻断

- `schemas migrate-run` 对不存在的源运行目录或空 `workflow2_cases` 现在写入 `source_run_dir_not_found` / `no_cases_discovered`，迁移报告 `error_count` 非零，CLI 返回失败。
- 迁移仍保留逐病例错误和已成功迁移的产物；只有真实发现并处理病例时才会被视为成功迁移。
- 新增迁移回归；本轮全量回归为 `545 passed, 18 warnings`。

### 2026-07-16 增量：reader 聚合拒绝非有限指标

- `batch_readers`、`merge_batches` 和 `reevaluate_run` 的 reader `overall_score` 现在与 Tool12 统计层统一：NaN、正无穷和负无穷指标会被跳过，不会污染均值或百分位输入。
- 合法的有限显式零值仍会保留；如果一行只包含非有限指标，则不会被伪造为 0 分。
- 新增三条聚合路径回归；本轮全量回归为 `546 passed, 18 warnings`。

### 2026-07-16 增量：department reader 分数非有限值阻断

- `workflow department` 现在排除 NaN、正无穷和负无穷的 `overall_score`，并记录 `non_finite_overall_score`；这些值不会进入 reader 百分位或科室统计。
- 有限显式零值、缺失值和普通非法字符串仍按各自既有语义区分，不会被统一改写成 0。
- 新增科室聚合回归；本轮全量回归为 `547 passed, 18 warnings`。

### 2026-07-16 增量：percentile_rank 非有限值阻断

- Tool12 的公开 `percentile_rank` 现在会过滤 population 中的 NaN/±Inf；查询值本身非有限时返回 0，不再产生不可解释的百分位。
- 该规则与 `calculate_statistics`、department 聚合和 reader overall score 门禁保持一致。
- 新增百分位回归；本轮全量回归为 `550 passed, 18 warnings`。

### 2026-07-16 增量：OCR 文本层读取释放 PDF 资源

- OCR 直接文本层路径现在使用上下文管理器关闭 PyMuPDF 文档，避免批量病例处理时积累文件句柄。
- 文本层输出、方法标记和缓存契约保持不变；新增文本层回归测试。
- 本轮全量回归为 `551 passed, 18 warnings`。

### 2026-07-16 增量：OCR 逐页渲染释放 PDF 资源

- OCR 逐页 300 DPI 渲染现在也使用上下文管理器关闭 PyMuPDF 文档，避免扫描 PDF 批量处理时累积文件句柄。
- 页序、渲染 hash、空白页跳过和逐页 provenance 行为保持不变；本轮完整回归仍为 `551 passed, 18 warnings`。

### 2026-07-16 增量：本地 VLM 输入资源释放

- `LLMClient` 的本地 Hugging Face VLM PDF 渲染改为使用上下文管理器关闭 PyMuPDF 文档；逐张加载图片时也在上下文内完成 RGB 转换并复制像素，返回对象不再持有源文件句柄。
- 该修复覆盖本地 VLM 的 PDF 与图片输入路径，不改变 prompt、页数限制、模型调用或输出解析契约。
- 已执行针对性回归及全量测试；当前全量结果为 `551 passed, 18 warnings`。

### 2026-07-16 增量：正式 benchmark 汇总过滤非有限指标

- generation benchmark summary 现在对 `candidate_likert_mean` 和 `alignment_f1` 过滤 NaN、正无穷、负无穷及布尔值；非法指标不会污染均值、最小值、最大值或正式比较输入。
- 新增回归覆盖“同一批结果中混入非有限指标”的汇总边界；合法有限零值和普通有限值保持原语义。
- 本轮全量回归为 `552 passed, 18 warnings`。

### 2026-07-16 增量：生成 benchmark 延迟汇总过滤非有限值

- generation benchmark 的 `latency_sec` 与 `batch_latency_sec` 汇总现在只纳入有限数值；NaN、正无穷和负无穷不会污染计数、均值、最小值和最大值。
- 新增延迟汇总回归，并复跑批处理 benchmark 测试；本轮全量回归为 `553 passed, 18 warnings`。

### 2026-07-16 增量：OCR benchmark 聚合过滤非有限指标

- OCR 候选聚合现在只纳入 CER、数字 token accuracy、否定词 token accuracy 均为有限数值的病例行；异常行不会污染模型均值、病例计数或截断统计。
- 新增 OCR 聚合回归，保证 NaN/±Inf 产物不会影响候选选择所依据的统计量。
- 本轮全量回归为 `554 passed, 18 warnings`。

### 2026-07-16 增量：正式 benchmark 比较输入有限值回归

- Welch/Holm 正式比较入口继续保持有限值过滤：NaN、±Inf 不进入模型组样本数、均值或 p 值计算。
- 新增回归覆盖一组混入 NaN 的模型比较，防止统计入口重构时重新把异常数值纳入正式结论。
- 本轮全量回归为 `555 passed, 18 warnings`。

### 2026-07-16 增量：重评估缺失 manifest 时阻断验证

- `workflow reevaluate-run` 在输出目录无法提供 `manifest.jsonl` 时不再写入 `validation.passed=true`；现在明确记录 `manifest_not_available_for_validation` 并将验证标记为失败。
- 正常存在 manifest 的重评估路径和源运行的真实 OCR 策略传播保持不变。
- 新增缺失 manifest 回归；本轮全量回归为 `556 passed, 18 warnings`。

### 2026-07-16 增量：重评估验证失败传播到 CLI registry

- `workflow reevaluate-run` 现在同时读取 `run_summary.validation`：验证失败会让 CLI 返回非零，并将 registry 条目标记为 `failed`，不再只检查顶层病例错误。
- 有 manifest 的正常重评估路径保持成功；缺失 manifest 的路径现在在 workflow、CLI 返回码和 registry 三层一致失败。
- 新增两条状态传播回归；本轮全量回归为 `557 passed, 18 warnings`。

### 2026-07-16 增量：科室 workflow registry 状态一致性

- `workflow department` 在空输入或其他 workflow 错误时，现在会把 registry 状态写为 `failed`；之前虽然 CLI 返回非零，registry 却使用默认 `passed`。
- 正常科室聚合仍登记 `passed`；新增空输入 registry 回归覆盖返回码与登记状态的一致性。

### 2026-07-16 增量：教育 workflow 阻断状态登记一致性

- `workflow education` 对 `blocked` / `blocked_insufficient_data` 结果现在显式写入 registry `failed`；CLI 返回码与 registry 状态一致。
- 正常教育建议生成继续登记 `passed`；新增阻断回归覆盖两层状态。

### 2026-07-16 增量：分析 workflow 错误状态登记一致性

- `workflow analyze-run` 遇到 `no_cases_discovered` 等结果错误时，现在将 registry 状态写为 `failed`；CLI 返回码与分析摘要、registry 三层一致。
- 正常分析仍登记 `passed`；新增空输入回归覆盖错误状态传播。

### 2026-07-16 增量：实验 workflow 双 registry 状态一致性

- `experiments run` 现在把失败状态同时传播到输出目录和源运行目录的 registry；此前源目录的第二条记录使用默认 `passed`。
- 正常实验运行继续登记 `passed`；新增缺失源运行回归覆盖两处登记状态。

### 2026-07-16 增量：API dashboard 异常状态登记

- `/dashboard/build` 现在先完成 HTML 构建，再写成功 registry；渲染异常会写入 `failed`、返回 HTTP 500，并保留异常类型提示。
- 正常 dashboard 构建仍登记 `passed`；新增 API 异常回归覆盖渲染失败路径。
- 本轮全量回归为 `558 passed, 18 warnings`。

### 2026-07-16 增量：API figures 异常状态登记

- `/figures/build` 现在捕获图表构建异常，写入输出目录 `failed` registry 并返回 HTTP 500；正常构建仍登记 `passed`。
- 新增 API 图表渲染失败回归；本轮全量回归为 `559 passed, 18 warnings`。

### 2026-07-16 增量：API sample-data 状态与异常闭环

- `/workflow/sample-data` 现在写入 run registry：空样本登记 `failed`，正常样本登记 `passed`；底层异常返回 HTTP 500 并写入失败原因。
- 原有响应字段 `manifest_path`、`case_count`、`errors` 和 `warnings` 保持兼容；新增 registry 仅补充可追踪性。
- 本轮全量回归为 `560 passed, 18 warnings`。

### 2026-07-16 增量：API sample-full registry 可追踪性

- `/workflow/sample-full` 的 dry-run 与正式运行现在都会写入 registry；dry-run 根据路由计划是否发现病例登记，正式运行根据 validation 状态登记。
- 原有响应摘要保持兼容，新增 registry 记录补齐 API 与 CLI 的运行账本一致性。

### 2026-07-16 增量：API batch/department/analyze registry 可追踪性

- `/workflow/batch-readers`、`/workflow/department`、`/workflow/analyze-run` 现在写入 registry，并按错误/失败病例状态登记 `failed`，正常结果登记 `passed`。
- 原有 API 摘要和结果结构保持兼容；新增记录用于和 CLI、前端运行账本对齐。

### 2026-07-16 增量：API merge-batches 状态与异常闭环

- `/workflow/merge-batches` 现在根据 validation 状态写入 registry；合并或验证异常返回 HTTP 500 并记录失败原因。
- 正常合并仍返回原有 validation 摘要并登记 `passed`，失败验证登记 `failed`。

### 2026-07-16 增量：API validate/preflight registry 可追踪性

- `/workflow/validate-run` 和 `/workflow/preflight` 现在写入 registry，并按验证/门禁结果登记 `passed` 或 `failed`。
- 阻断项仍通过原有响应摘要返回；新增 registry 仅补充运行账本和前端可追踪性。

### 2026-07-16 增量：API preflight 缺失输入异常闭环

- `/workflow/preflight` 对不存在的样本根目录现在返回结构化 HTTP 500，并写入失败 registry；正常门禁阻断仍保持 200 + blockers 摘要。
- 新增缺失样本根目录回归；本轮全量回归为 `561 passed, 18 warnings`。

### 2026-07-16 增量：其余 workflow API 异常闭环

- `/workflow/batch-readers`、`/workflow/department`、`/workflow/analyze-run`、`/workflow/validate-run`、`/workflow/education` 现在捕获底层运行异常，写入 `failed` registry，并返回结构化 HTTP 500（保留异常类型前缀）。
- 新增统一回归覆盖 5 条异常路径；API 测试为 `20 passed`，随后全量回归为 `562 passed, 18 warnings`。
- 正常业务返回和原有摘要字段保持兼容；仅将此前会直接抛出未登记异常的路径纳入运行账本。

### 2026-07-16 增量：核心入口 API 异常闭环

- `/workflow/single-case`、`/experiments/run`、`/workflow/sample-full` 现在也会捕获配置加载或底层工作流异常，写入失败 registry，并返回结构化 HTTP 500。
- 新增 3 条回归覆盖核心入口；API 测试为 `21 passed`，全量回归为 `563 passed, 18 warnings`。dry-run 与正式 sample-full 的正常返回结构保持不变。

### 本轮已落地

- **H9/H10（统计侧）**：`tool12.calculate_statistics` 现在过滤 `fallback_used`、`debug_fallback`、`mock` 和 fallback source；聚合层不会再把这些行混入均值。`tool9/tool10` 原有过滤继续保留。
- **H7（单样本边界）**：`n=1` 的 CI 上下界现在输出 `null`，明确表示无法估计不确定性；不再输出与均值重合的伪 CI。
- **M11**：教育结果 provenance 现在明确标记 `llm_judge`、`mock_judge` 或 `deterministic_fallback`，并同步 `fallback_used`。
- 回归测试持续新增；2026-07-16 本轮最终全量验证为 `532 passed, 18 warnings`，并已通过 `compileall` 与 `git diff --check`。M9 失败分母已接入 `analyze_run` JSON/Markdown 汇总，workflow2/workflow3 聚合边界及内部一致性也已纳入合约验证；pilot10 标注状态已有可执行验收门禁；面板构建器还会忽略自身 `web/index.html` 的生成差异，避免正常重建误报 dirty。

### 仍需处理

**第一梯队 —— 真实证据门禁（当前代码已具备，尚缺外部证据）**
1. **H8** 正式 benchmark summary 已接入 Welch+Holm；仍需在冻结结果上执行并保存统计产物。
2. **H6** 排名已保留 cutoff 近似并列候选；仍需在冻结结果上报告不确定性。
3. **H12/H13** seed、route fingerprint 和 `--no-resume` 已落地；仍需真实重复运行验证。
4. **M12** `live-smoke` 已提供；当前缺少 `DMX_API_KEY`，必须保持 blocked。

**第二梯队 —— 合规红线（动真实病人数据前必须）**
5. **H1 / H2 / H3** 评测链路强制去标识 + 给出"真评测 + 扫描"的配置态
6. **H4** 收紧 `outputs/` 权限 + `docs/pat.txt` 移出组内可读位置
7. **C1** API 鉴权 + 路径白名单

**第三梯队 —— 仍需外部或产品决策的事项**
8. **H14 / M7** reviewer 参数兼容性与真实自一致率仍需云端重复调用验证。
9. **H15/H16/H17** 本地解析、Tool7 行为测试和非 CXR slug 规范化已落地；真实模型/同义词质量仍需冻结集确认。
10. **L4** 旧 finding graph 迁移不再伪造 `reported_finding`：缺观察内容会显式标记 `unparsed_legacy_finding` 并写入迁移警告，且对齐层拒绝将其当作真实观察配对。
11. **OCR/临床**：北川 10 例 OCR 冻结集、双次候选比较、多模态 verifier、pilot10 双读者标注尚未就位。
12. 安全/隐私与 API 鉴权按用户明确要求暂缓，不作为本轮阻塞。

---

*本文档由 8 维并行审计（62 agent）+ 对抗性验证生成，严重度以验证后 `adjusted_severity` 为准，关键项经主审人逐行复核。所有 file:line 为 2026-07-14 快照，动手前请对当前代码复验。*
