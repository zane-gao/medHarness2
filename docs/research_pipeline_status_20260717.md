# 临床标注 / OCR / 论文实验准备状态（2026-07-17）

## 已完成的准备工作

- 从当前 52 例运行产物确定性筛选出 10 例，覆盖 `cxr`、`ct`、`mri` 三类模态。
- 生成盲化医生标注包：`annotation/pilot10/`。
- 标注包包含 `reader_a`、`reader_b`、`adjudication` 三个槽位，初始均为 `not_started`。
- 模型身份映射隔离于 `internal/model_blinding_map.json`，不进入读者包。
- 当前 OCR/文本 benchmark 使用北川参考报告作为工程金标准（`gold_source=beichuan_reference_report`）；真实 reader 标注单独用于临床校准。
- 生成 OCR/论文实验 manifest：`outputs/research/20260717/`（本地 outputs/ 产物，被忽略规则排除；可用命令重建）。
- 已增加 reader 隔离导出命令，真实标注可以从 `annotation/pilot10/` 生成不泄漏另一 reader 槽位的交付副本。
- 已增加 `annotation import-reader` 安全回收命令，只能更新指定 reader 槽位并拒绝身份/候选漂移。
- `import-reader` 现在还绑定参考报告与指令版本，校验 slot 身份，并以原子暂存/备份/回滚方式写回，避免多病例交付包在异常时部分合并。
- `validate_sample_run` 对 JSONL manifest 的身份、路径、warnings、图像列表和对象字段执行 fail-closed 类型门禁；损坏 manifest 只进入错误分母，不会污染 OCR/路由统计。
- 新增 `research run-ocr`：按 10 例 × 2 重复执行已冻结的 OCR 研究 manifest，逐病例写入带源 PDF hash、provider/model/role、候选键和质量状态的 sidecar，并自动生成两次 `ocr-benchmark` 结果。
- 运行器无真实凭据、源 PDF 缺失、provider 异常或质量门禁失败时只写 `blocked` / `review_required`，不写伪造文本；当前 A40 实测 10/10 pilot 均能唯一映射真实源 PDF，60 个 sidecar 中 40 个因 Doubao/Qwen 凭据缺失、20 个因 PaddleOCR-VL 运行时缺失而阻塞。
- 研究 manifest 会在执行后回写每次 sidecar 的状态、实际 model/provider/role、benchmark route provenance 和 repeat 结果；Qwen audit-only 不进入 OCR 候选排名，Paddle 运行时缺失不会被误报成仅缺 API key。
- 2026-07-17 OCR 候选 provenance 收口：`research run-ocr` 现在同时校验候选声明的 provider 和精确 model ID；例如将 Yunwu `qwen3-vl-plus` 配置到 Doubao primary role 会返回 `model_mismatch` 并写入 blocked sidecar，不再把 Qwen 文本挂在 `ocr_primary_doubao` 名下。
- 已新增 `config/yunwu_qwen_ocr_exploratory.yaml`，固定 Yunwu `qwen3-vl-plus` 主 OCR 与 `qwen-vl-max` 审计模型，仅用于直接逐页探索；它不会绕过正式 OCR manifest 的 Doubao/Paddle 候选身份门禁。
- Doubao 是当前 primary OCR 候选；Qwen 仅作为 audit-only 多模态抽查，不进入 winner 比较；PaddleOCR-VL-1.6 已接入可选 baseline adapter，按官方 `PaddleOCRVL` 完整文档解析接口读取 Markdown 结果。provider 与 `paddle` runtime 分开检查，分别记录 `paddleocr_provider_unavailable` / `paddle_runtime_unavailable`；仅配置就绪不等于质量通过，必须有真实逐页 Qwen audit 且全部 `agree`。
- 2026-07-17 Yunwu 实测模型目录确认可调用 `qwen3-vl-plus` 与 `qwen-vl-max`；当前未确认暴露可用于 OCR 的 Doubao/Volcengine 视觉模型，`doubao-seedream-*` 不作为 OCR 候选。DMX 凭据实测返回 401，不能作为当前实验 provider。
- 2026-07-17 真实逐页 OCR 复测记录：`CR2605290003`（CXR）、`CT2605300030`（CT）、`MR2605270001`（MRI）有 Yunwu `qwen3-vl-plus` exploratory sidecar；医院技术支持稀疏末页被记录为 `skip_reason=non_report_page`。按当前代码门禁，含该 warning 的结果应为 `review_required`，不能沿用旧 sidecar 的 `passed` 标记，也不改变 Doubao winner blocked 状态。
- 2026-07-17 未注册 pilot10 exploratory OCR：外部记录首轮 8/10；`pilot-002`、`pilot-004` 针对性重试为 2/2。它们未写入正式 `outputs/research/20260717` 双重复 manifest，因此只作为调试线索，不升级为正式 10/10、winner 或论文证据。
- 2026-07-17 同一未注册 pilot10 的第二次独立 Qwen 重复仅 `2/10` 直接通过、`4/10` `review_required`、`4/10` 因正文页疑似截断而 `blocked`。其中 `review_required` 来自探索脚本未传 verifier client；`blocked` 是正文输出不完整的真实失败证据。该重复结果进一步证明 Qwen 当前不能升级为稳定 OCR winner。
- 2026-07-17 修复短英文技术页元话术（包括 `There is`）与“注释+审核时间”尾部的截断误报后，重新执行同一 10 例 Yunwu Qwen 小批次：10/10 均不再出现正文截断，第二页均记录为 `skip_reason=non_report_page`；但由于技术页 warning，当前门禁仍统一为 `review_required`，其中 1 例 verifier 返回非法 JSON。该结果只证明工程误报下降，不构成 OCR winner 或正式 benchmark 证据。
- 2026-07-17 在确认技术页为非报告页且所有保留报告页 verifier 均 `agree` 时放宽门禁：第三轮同一 10 例复测得到 `3/10 passed`、`7/10 review_required`、`0/10 blocked`。7 例 review 的分歧均来自手写签名不可可靠转写、空字段被填充或页脚版式合并；没有正文截断。该规则不把 disagreement/invalid verifier 放行，也不改变正式 winner 门禁。
- 2026-07-17 路由误判收尾：Tool 7 不再把任意 PNG/JPG/JPEG 直接当作 CXR；CT/MRI 的 `contact_sheet.png` 现在会交给 VLM 识别，无 VLM 或无可信文件名提示时返回 `unknown`。DICOM header 和显式病例 modality 仍优先，三模态 body_part 软排序语义不变。

## 当前证据状态

### 2026-07-17 运行复核

- `workflow preflight` 在真实数据路径 `/nfsdata_a40/isbi/gzp/medHarness/data/sample_data_2026-06-05` 上发现 52 例，模态计数为 `cxr/ct/mri=20/25/7`；使用 `config/dmx_strong.yaml --require-real-ocr` 时按预期以非零退出，阻断原因为 `missing_llm_api_key` 与 `real_ocr_verifier_unavailable`。
- `research run-ocr` 在 pilot10 上生成 60 个 sidecar，当前无外部凭据/本地 PaddleOCR-VL runtime 时保持 `blocked`；未把阻断结果计入 CER、winner 或论文统计。
- `research prepare-manifests` 是准备阶段命令，即使生成的 OCR/论文 gate 初始为 `blocked/pending` 也返回 0；只有实际执行命令在证据缺失时返回非零，避免自动化把“清单已生成”误判成“执行失败”。
- `annotation validate --package-dir annotation/pilot10` 返回 `not_started`、`0/10`，并以非零退出；没有把空标注包误报为完成。
- 新增 `annotation analyze`：真实 reader 回收后自动生成完成数、双读 exact-set agreement、finding/hazard presence Cohen κ 和分歧队列；当前 pilot10 实测为 `blocked`、`0/10`，不生成虚假 ICC 或 formal claim。
- 新增 `research paper-gate`：统一检查临床双读/OCR winner/正式实验三类证据；任一缺失都返回 `blocked`，只有三类均 validated 才允许 `formal_claim_allowed=true`。
- 新增 `research freeze-ocr-winner`：真实 OCR 两次 benchmark 完成后，要求全量运行质量通过、两次 winner 一致、覆盖完整，再把冻结模型和证据 hash 写回 OCR manifest；当前因 manifest 仍为 `blocked` 而按预期拒绝。
- PaddleOCR baseline 现要求 `PaddleOCRVL` 和 Paddle runtime 同时可导入；sidecar 结构、空页、空文本、源 PDF hash 读取失败均 fail-closed，不会把“部分页面成功”升级为 OCR 通过。
- 2026-07-17 A40 本机已安装 `paddleocr==3.7.0`、`paddlepaddle==3.2.2`，`PaddleOCRVL` 可导入；官方 `PaddleOCR-VL-1.6` 权重下载在当前 Hugging Face 网络上卡在约 53%，因此 readiness 明确返回 `paddle_model_weights_unavailable`，研究运行器不会误启动未完成的模型。
- 2026-07-17 已多次用 Yunwu `qwen3-vl-plus` 对 MR2605270001 做真实视觉链路探索：Tool 2、Tool 5、Tool 4 均曾成功越过，生成 fallback 也能返回非空 exploratory 文本。最新一次产物 `/tmp/single_yunwu_vl_mr2605270001_finalcheck` 完整生成 `generated_reports=1`、`generated_evaluations=1`、`rankings=1`、`pairwise=1`，无 errors 且质量门禁通过；但证据等级仍为 `exploratory_fresh`，fallback provenance 仍保留，且此前重复运行出现过 evidence 重排、枚举违规和 JSON 截断，因此尚未达到稳定小批次标准，不能作为正式评测结果。
- 2026-07-17 修复了单病例空生成占位符级联：空报告不再进入 Tool 1–6、ranking 或 pairwise。真实外部 `llm_fallback` 若返回非空文本，会标记为 `exploratory_fresh`，先过内容质量门禁后可用于探索性评估/排序；mock/debug fallback 仍 fail-closed，所有 exploratory 结果仍不能进入 formal gate。
- Tool 2 现在向视觉模型提供带 `span_id` 和源偏移的 source-ordered evidence spans，并由服务端按完整报告原文恢复 grounding；Tool 5 在 pairwise 中对 Qwen/VL 模型按每块 1 个错误、其他模型按每块 5 个错误请求，并对每个错误块只保留相关 finding/pair 上下文，把分块策略写入 checkpoint 指纹，降低多模态 JSON 截断和旧缓存复用风险。真实 Qwen 结果仍是 exploratory，不能升级为 winner。
- 跨模态 exploratory 复核：MRI `MR2605270001`、CXR `CR2605290003`、CT `CT2605300030` 均已完整生成报告、评估、ranking 和 pairwise，三例均无 errors 且质量门禁通过；CT 长病例在上下文裁剪后以 25 个单错误块完成 Tool 5，期间有一次 schema 重试但无 fallback。三例均未写入正式 benchmark 或论文统计。

| 工作线 | 状态 | 原因 |
| --- | --- | --- |
| 真实医生标注 | `not_started` | 尚未有真实 reader 输入 |
| OCR winner | `blocked` | 已有可执行的双次运行器、benchmark 回写和 PaddleOCR adapter；当前 Yunwu 目录已确认 `qwen3-vl-plus`/`qwen-vl-max`，但未暴露可确认的 Doubao/Volcengine OCR 视觉模型（`doubao-seedream-*` 仅为图像生成，不纳入 OCR），DMX 凭据 401，PaddleOCR-VL runtime 也未就绪；Qwen 第三轮仅 3/10 通过 |
| 论文 formal claim | `blocked`（`formal_claim_allowed=false`） | 只有实验设计，尚无 validated gate |

## 下一步

1. 将 10 例标注包交给真实 `reader_a` 与 `reader_b` 独立完成；
2. 完成 adjudication，运行 `annotation validate` 和 `annotation analyze`，再进入正式一致性与 hazard 统计；
3. 继续用 Yunwu Qwen VL 做 1–3 例可恢复的小批次真实链路，先达到 Tool 2/Tool 5 的稳定小批次成功率并修复剩余 schema/截断问题；OCR winner 仍需可用 Doubao OCR 凭据/模型或其他完整候选后再执行双次比较；
4. 运行 `research paper-gate` 汇总三类证据；只有所有 evidence gate 通过后，才允许生成 OCR winner 或论文正式结果。

合成草稿、模型输出和自动规则结果不会被标记为真实医生标注；北川参考报告是当前文本 benchmark gold，不等同于 reader adjudication。
