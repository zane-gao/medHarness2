# T1/T2/T4/T5/T6 LLM 工具升级记录

更新日期：2026-07-11

## 范围与结论

本轮只升级后端工具、契约、模型路由和测试，不包含前端或控制面板工作。

- T1 正式路径必须真实调用 LLM 完成五维评分；mock 与 deterministic fallback 在 strict 模式下会被拒绝。
- T2 使用“模态规则/模板候选 + LLM 完整校正”，所有 finding 必须绑定原报告证据片段并通过 `FindingGraph` 校验。
- T4 使用“确定性 hazard 先验 + 主 LLM + 独立 reviewer”；reviewer 只生成 `HazardReviewArtifact`，不覆盖主结果。
- T5 保留最大权重二分匹配作为主结果，LLM 只生成哈希绑定的 `AlignmentAuditArtifact`。
- T6 保留 section presence/length/order/score 差异作为主结果，LLM 只生成临床沟通影响 `StructureAuditArtifact`。
- 正式角色持续 schema invalid、API 失败或命中 mock 时直接失败，不以规则结果冒充真实 LLM 结果。

## 角色路由

主 profile：`config/dmx_strong.yaml`

| 角色 | 当前候选模型 | 用途 |
| --- | --- | --- |
| `general_judge` | `gpt-5.6-terra` | T1 五维评分 |
| `finding_extractor` | `gpt-5.6-terra` | T2 模板候选校正 |
| `alignment_auditor` | `gpt-5.6-terra` | T5 对齐审计 |
| `hazard_primary` | `gpt-5.6-terra` | T4 主危害研判 |
| `hazard_reviewer` | `claude-opus-4-8` | T4 独立复核 |
| `hazard_adjudicator` | `gpt-5.6-sol` | T4 第三方分歧裁决 |
| `structure_auditor` | `gpt-5.6-terra` | T6 临床结构研判 |
| `education` | `gpt-5.6-terra` | 教育建议候选 |

`claude-opus-4-8` 通过 `omit_temperature: true` 兼容 DMX/Yunwu 调用约束。统一 JSON 解析器支持纯 JSON 或完整 Markdown JSON 围栏，但不接受夹杂任意说明文字的部分 JSON。

备用 profile：`config/yunwu_strong.yaml`。它只能被显式选择，不做静默 provider failover，避免同一次实验混入不同 endpoint 而失去可复现性。

新增 API 对应两个额外显式 profile：

- `config/codex_proxy_strong.yaml`：GPT 与 Claude 都走 `codex.0u0o.com`，分别读取 `CODEX_PROXY_GPT_API_KEY` 与 `CODEX_PROXY_CLAUDE_API_KEY`。当前 GPT 通道可用，但 Claude 4.8/4.7/Sonnet 5 均返回 HTTP 503，因此该 profile 尚不能作为完整链路。
- `config/codex_dmx_strong.yaml`：应急混合路线，GPT 角色走 codex proxy，独立 Claude 4.8 reviewer 走 DMX。该路线必须手工选择，两个 endpoint 都写入 provenance，不是静默 failover，也不改变 DMX 作为首选 full profile 的决策。

这些模型是当前强候选，不是 gold-set 胜出模型。正式角色仍需按医生标签比较 ICC/Spearman、weighted kappa、critical recall、schema success 和稳定性。

## 合成 API 验证

验证输入均为无患者身份信息的合成胸片报告，不能作为临床有效性证据。

### DMX

- `/v1/models` 可用，确认 `gpt-5.6-terra`、`gpt-5.5`、`claude-opus-4-8` 等模型 ID 存在。
- `gpt-5.6-terra`：hazard JSON smoke 成功；T1 五维真实调用成功；T2 模板 + LLM 严格抽取成功，首次通过、无 fallback。
- `claude-opus-4-8`：省略 temperature 后真实调用成功；完整 JSON 围栏可被严格解析。
- `gpt-5.6-sol`：T4 第三方 adjudication 在 11 例中全部完成。
- 纯 DMX 11 例探索性 CXR 链路已完成：11/11 成功、0 failure、0 fallback；每例 9 条真实角色证据，总计 99 条。路由计数为 `gpt-5.6-terra=77`、`claude-opus-4-8=11`、`gpt-5.6-sol=11`。
- T5 原 prompt 允许自由文本 replacement error type，而 validator 只接受 7 个枚举，导致 2 例失败。修复后 prompt 与 validator 共用同一枚举来源，两个原失败病例均恢复；新实现哈希为 `ed9d26ca0e73f777ee419fbdc3683f803fd93edac7499c492265909371e12b4a`。
- 冻结运行配置哈希为 `2ccc541797fc011ea665a80ac7f7cfb14f6d31301f361ca539816f502a892818`，结果路径为 `outputs/benchmarks/cxr_chest_qwen3vl8b_11_v1_20260711/evaluation_dmx_ontology_v2_v2/attempt_001`。

该 11 例结果仍不是临床验证。对旧、新运行共同成功的 9 例，T1 均分完全一致率只有 11.1%，平均绝对差 0.356；consensus material-error count 完全一致率 22.2%，平均绝对差 4.44。稳定性摘要与图位于运行目录 `analysis_v1/`，正式实验必须增加重复调用、聚合规则和医生校准。

### Yunwu 显式备用

完整 T1/T2/T5/T4/T6 合成链路成功：

- T1：5/5 维度，`llm_judge`，`fallback_used=false`。
- T2：single 与 pairwise 三次均为 `template_llm`，`fallback_used=false`。
- T5：审计执行成功，识别到 alignment issues，主 alignment 保持不变。
- T4：`gpt-5.6-terra` 主评与 `claude-opus-4-8` reviewer 均无 fallback；生成 2 项分歧并要求 adjudication。
- T6：`tool6-structure-v2` + LLM 临床意义研判成功，无 fallback。

### Codex GPT + DMX Claude 显式应急路线

完整 T1/T2/T5/T4/T6 合成链路成功：

- T1：五个维度，`gpt-5.6-terra`，`fallback_used=false`。
- T2：single 与 pairwise 三次均为 `template_llm`，finding 数分别为 3/3/3，无 fallback。
- T5：识别 4 个 deterministic alignment error，审计 verdict 为 `issues_found`；hash 匹配且主结果保持不变。
- T4：GPT 主评输出 4 个 hazard，DMX `claude-opus-4-8` 独立复核；产生 1 项 disagreement 并要求 adjudication；hash 匹配，双侧均无 fallback。
- T6：`tool6-structure-v2` 与审计均通过；hash 匹配，主结果保持不变，无 fallback。

该结果只证明显式混合 profile 的工程可用性，不证明纯 DMX full profile 已恢复，也不允许在同一正式实验中临时切换 endpoint。

机器可读摘要：`docs/llm_tools_synthetic_smoke_20260710.json`。

## 尚未完成的质量门

1. 尚未用医生双标与 adjudication gold set 计算 T1/T2/T4/T5/T6 的临床指标。
2. 当前 52 例 qualityfix run 尚未用本轮真实 LLM 工具全量重跑；本次只完成 11 例 CXR exploratory_fresh 子集。
3. 当前生成报告仍为 `14 artifact + 67 debug_fallback + 0 formal_fresh`，不能进行正式模型优劣结论。
4. LLM 评价重复性不足，必须预注册重复次数、共识聚合、置信区间和不稳定性门槛。
5. 参考报告仍包含行政头信息；正式评价前需冻结临床正文标准化并保存 raw/normalized 双哈希。
6. API smoke、11 例探索性运行和 330 项自动化测试证明工程行为，不证明医学正确性。
