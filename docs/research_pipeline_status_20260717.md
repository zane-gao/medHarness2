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
- Doubao 是当前 primary OCR 候选；Qwen 仅作为 audit-only 多模态抽查，不进入 winner 比较；PaddleOCR-VL-1.6 已接入可选 baseline adapter，按官方 `PaddleOCRVL` 完整文档解析接口读取 Markdown 结果。provider 与 `paddle` runtime 分开检查，分别记录 `paddleocr_provider_unavailable` / `paddle_runtime_unavailable`；仅配置就绪不等于质量通过，必须有真实逐页 Qwen audit 且全部 `agree`。

## 当前证据状态

### 2026-07-17 运行复核

- `workflow preflight` 在真实数据路径 `/nfsdata_a40/isbi/gzp/medHarness/data/sample_data_2026-06-05` 上发现 52 例，模态计数为 `cxr/ct/mri=20/25/7`；使用 `config/dmx_strong.yaml --require-real-ocr` 时按预期以非零退出，阻断原因为 `missing_llm_api_key` 与 `real_ocr_verifier_unavailable`。
- `research run-ocr` 在 pilot10 上生成 60 个 sidecar，当前无外部凭据/本地 PaddleOCR-VL runtime 时保持 `blocked`；未把阻断结果计入 CER、winner 或论文统计。
- `research prepare-manifests` 是准备阶段命令，即使生成的 OCR/论文 gate 初始为 `blocked/pending` 也返回 0；只有实际执行命令在证据缺失时返回非零，避免自动化把“清单已生成”误判成“执行失败”。
- `annotation validate --package-dir annotation/pilot10` 返回 `not_started`、`0/10`，并以非零退出；没有把空标注包误报为完成。
- PaddleOCR baseline 现要求 `PaddleOCRVL` 和 Paddle runtime 同时可导入；sidecar 结构、空页、空文本、源 PDF hash 读取失败均 fail-closed，不会把“部分页面成功”升级为 OCR 通过。

| 工作线 | 状态 | 原因 |
| --- | --- | --- |
| 真实医生标注 | `not_started` | 尚未有真实 reader 输入 |
| OCR winner | `blocked` | 已有可执行的双次运行器、benchmark 回写和 PaddleOCR adapter，但当前缺真实 provider/verifier 凭据或本地 PaddleOCR 运行时 |
| 论文 formal claim | `pending` | 只有实验设计，尚无 validated gate |

## 下一步

1. 将 10 例标注包交给真实 `reader_a` 与 `reader_b` 独立完成；
2. 完成 adjudication，并运行一致性与 hazard 统计；
3. 按 `research run-ocr` 在北川金标准上执行真实 OCR 候选双次比较；Qwen 只看 audit sidecar，不参与 winner 排名；
4. 只有所有 evidence gate 通过后，才允许生成 OCR winner 或论文正式结果。

合成草稿、模型输出和自动规则结果不会被标记为真实医生标注；北川参考报告是当前文本 benchmark gold，不等同于 reader adjudication。
