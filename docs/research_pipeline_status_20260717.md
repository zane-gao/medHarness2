# 临床标注 / OCR / 论文实验准备状态（2026-07-17）

## 已完成的准备工作

- 从当前 52 例运行产物确定性筛选出 10 例，覆盖 `cxr`、`ct`、`mri` 三类模态。
- 生成盲化医生标注包：`annotation/pilot10/`。
- 标注包包含 `reader_a`、`reader_b`、`adjudication` 三个槽位，初始均为 `not_started`。
- 模型身份映射隔离于 `internal/model_blinding_map.json`，不进入读者包。
- 当前 OCR/文本 benchmark 使用北川参考报告作为工程金标准（`gold_source=beichuan_reference_report`）；真实 reader 标注单独用于临床校准。
- 生成 OCR/论文实验 manifest：`outputs/research/20260717/`（本地 outputs/ 产物，被忽略规则排除；可用命令重建）。
- 已增加 reader 隔离导出命令，真实标注可以从 `annotation/pilot10/` 生成不泄漏另一 reader 槽位的交付副本。

## 当前证据状态

| 工作线 | 状态 | 原因 |
| --- | --- | --- |
| 真实医生标注 | `not_started` | 尚未有真实 reader 输入 |
| OCR winner | `blocked` | 北川金标准文本已就绪，尚缺真实 provider 双次运行 |
| 论文 formal claim | `pending` | 只有实验设计，尚无 validated gate |

## 下一步

1. 将 10 例标注包交给真实 `reader_a` 与 `reader_b` 独立完成；
2. 完成 adjudication，并运行一致性与 hazard 统计；
3. 按 `outputs/research/20260717/ocr_manifest.json` 在北川金标准上执行真实 OCR 候选双次比较；
4. 只有所有 evidence gate 通过后，才允许生成 OCR winner 或论文正式结果。

合成草稿、模型输出和自动规则结果不会被标记为真实医生标注；北川参考报告是当前文本 benchmark gold，不等同于 reader adjudication。
