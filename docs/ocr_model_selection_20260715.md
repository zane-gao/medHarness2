# OCR 候选与冻结评测决策记录

更新时间：2026-07-16

## 结论先行

当前不把任何模型直接宣布为 OCR winner。`config/dmx_strong.yaml` 已将
`doubao-seed-2-1-pro-260628` 作为 `ocr_primary` 候选、`qwen-vl-ocr-latest`
作为独立 `ocr_verifier` 候选，但两者都必须经过北川冻结集的真实逐页比较。
主 OCR 负责产生唯一可下游消费的文本；verifier 只产生审计结果，不能静默改写主文本。

## 候选矩阵

| 候选 | 角色 | 当前状态 | 采用理由 | 不能直接推出的结论 |
| --- | --- | --- | --- | --- |
| Doubao Seed（Ark/DMX 精确模型 ID） | 主 OCR 候选 | 已接入配置，未完成北川真实 benchmark | 用户优先建议；OpenAI-compatible 路由便于复用逐页管线 | 不能仅凭模型名称宣布最强 |
| PaddleOCR-VL 系列（当前公开文档/版本） | 独立本地/服务候选 | 已接入可选 `paddleocr` provider adapter（安装 extra：`ocr-paddle`）；未安装依赖时 fail-closed | 官方项目提供文档解析管线和可部署推理路径；适合与 VLM 主 OCR 做独立比较 | 通用文档 benchmark 不等于放射报告临床 CER |
| PP-OCRv5/后续 PP-OCR 系列 | 专用 OCR 候选 | 已列入候选，尚未接入本仓库 provider | 专用文本识别路线，适合作为低成本基线和数字/标点对照 | 专用 OCR 不能自动完成版面/医学语义恢复 |
| Qwen OCR/VLM verifier | 独立审计候选 | 已接入 `ocr_verifier` 配置，未完成真实 smoke | 与主 OCR 分离，能做页级差异审计 | verifier 一致不等于 gold 正确 |
| Gemini Document Understanding | 可选外部审计候选 | 未接入 | 官方文档支持 PDF 原生视觉理解，适合抽查整页上下文 | 外部文档理解结果不能替代冻结集评分 |

## 冻结集与指标

北川数据集是当前工程金标准。正式比较前必须冻结：

1. case ID、源 PDF SHA-256、页数和页级渲染 hash；
2. 每个候选至少两次独立运行，保存 provider/model/role、prompt 版本和原始输出；
3. gold 文本与候选文本按病例和页码一一绑定，缺失或 provenance 不匹配直接 blocked。

主指标是临床文本 CER（优先 Findings/Impression 区段）；辅助指标包括：

- 数字 token 顺序、重复和漏识别；
- 否定词边界匹配；
- 页级截断/异常结束；
- provider/model/role provenance 完整性；
- 两次运行的一致性。

模型选择规则只能在 benchmark `succeeded` 且覆盖一致时运行：先按 clinical CER，
再按截断数量、否定词准确率排序；如果缺少冻结文本 gold、候选、模型键、病例覆盖或 provenance，
结果必须为 `blocked`，不能生成 winner。

## 实施边界

- PDF 文本层足够完整时可走 `pdf_text_layer`，但仍保留来源和 hash；扫描 PDF 走逐页渲染。
- 确定性全白页跳过；稀疏但有墨量的页保留并进入 OCR。
- verifier 失败、非法 JSON 或网络错误只写审计 warning，不拖垮主 OCR。
- `require_real` 只接受明确的真实 provider 白名单；mock、deterministic、fallback 和未知 provider 均不能冒充真实 OCR。

## 当前门禁状态

本地机制和回归测试已具备；真实北川 gold/candidate 冻结集、至少两个候选各两次真实 OCR、
独立 verifier smoke 仍未执行。当前环境缺少对应真实凭据/冻结产物，因此不把这些状态写成 succeeded。

## 一手资料

- PaddleOCR 官方仓库与 PaddleOCR-VL 文档：`https://github.com/PaddlePaddle/PaddleOCR`
- PP-OCRv5 官方文档：`https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5.md`
- PaddleOCR-VL 官方管线文档：`https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.md`
- Gemini 文档理解官方文档：`https://ai.google.dev/gemini-api/docs/document-processing`
