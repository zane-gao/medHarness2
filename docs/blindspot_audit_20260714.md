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
> **2026-07-16 评委输入边界增量**：Tool1/Tool2 对外部评委 prompt 的报告文本增加长度上限、头尾保留和明确的 quoted-data 边界；Tool2 prompt/stage 版本升级为 `tool2-hybrid-v3`，避免 checkpoint 将新旧提示词混用。全量回归测试为 410 passed、18 warnings。
> **2026-07-16 统计汇总增量**：Tool12 纳入 reader-level `overall_score`；Workflow3 department 输出补齐 source/success/failure 分母及成功率、失败率，避免 reader 统计只呈现分数而丢失失败病例分母。全量回归测试为 412 passed、18 warnings。
> **2026-07-16 排名语义增量**：Tool9 近 cutoff 候选仍保留供复核，但不再把它们标成正式 `selected_top_n`；新增 `near_cutoff_review` 区分复核候选，避免 analyze/education 下游误把不确定候选纳入正式 Top-N。
> **2026-07-16 verifier/门禁增量**：OCR verifier 对非 JSON object 响应统一记为 audit warning，不影响主 OCR；`validate-run` 增加 OCR case/hash/截断 provenance 回归覆盖。全量回归测试为 416 passed、18 warnings。
> **2026-07-16 严格缺失数据增量**：带源 PDF 的 OCR 验证现在区分 VLM 页级质量与合法 `pdf_text_layer`；batch/reevaluate 对真实缺失报告不再生成伪造占位文本，非严格 mock 流程仅保留显式“Report text unavailable”工程占位；LLM 非可重试 HTTP 错误不再盲目重试。全量回归测试为 418 passed、18 warnings。
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

### 本轮已落地

- **H9/H10（统计侧）**：`tool12.calculate_statistics` 现在过滤 `fallback_used`、`debug_fallback`、`mock` 和 fallback source；聚合层不会再把这些行混入均值。`tool9/tool10` 原有过滤继续保留。
- **H7（单样本边界）**：`n=1` 的 CI 上下界现在输出 `null`，明确表示无法估计不确定性；不再输出与均值重合的伪 CI。
- **M11**：教育结果 provenance 现在明确标记 `llm_judge`、`mock_judge` 或 `deterministic_fallback`，并同步 `fallback_used`。
- 回归测试持续新增；2026-07-16 本轮全量验证为 `418 passed, 18 warnings`，并已通过 `compileall` 与 `git diff --check`。M9 失败分母已接入 `analyze_run` JSON/Markdown 汇总。

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
