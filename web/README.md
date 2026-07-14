# medHarness2 · 项目认知面板

这里维护的是面向项目负责人的内部状态面板。页面是**自包含、可离线双击打开**的长页面，目标是用最通俗的人话 + 比喻，快速回答“现在做到哪了、哪些证据可信、下一步卡在哪里”。

当前发布状态是 `pilot-only`：页面用于项目开发与证据盘点，不代表临床验证完成，也不替代正式实验报告。

主页面按以下顺序组织内容：

1. **这是什么**：一句话定位 + 阅卷老师比喻 + 系统边界（评估教学闭环，也展示候选报告生成，但当前仍是 pilot-only）
2. **整体流程**：一条 7 步流水线，每步标注背后的工具，点击可跳转
3. **设计哲学**：四层架构（工作流/模块/工具/基础设施）为什么这么设计
4. **四条工作流**：单病例 → 批量 → 科室 → 教学，规模逐级放大
5. **13 台仪器**（Tool 1–12 + 质量门禁）：每张卡 = 人话 + 比喻 + 真实输入输出例子
   + 实现方式徽章（🤖 调大模型 API / 🏠 本地医学模型 / 📐 纯规则代码）
   + **诚实度徽章**（✓ 真跑 / ⚠ 部分真 / ✕ 本次为假）+ 可展开的实现细节
6. **真实运行证据**：KPI、模态分布、候选报告“成色”图、医生百分位（附诚实说明）、门禁失败清单
6.5. **最新进展**（数据存在才渲染）：全真 LLM 流水线（证据 A）、三法官仲裁（证据 B）、
     重测稳定性体检（证据 C，确定性 vs LLM 指标一致率对比条）、盲写 fresh 基准（证据 D）、
     OCR 截断审计（证据 E）、formal 就绪度体检（证据 F）
6.8. **工程进度地图**（数据存在才渲染）：九条战线状态（读 `docs/project_status.yaml`）、
     六实验 × 4 门禁矩阵（读 experiments results.json）、pilot10 临床标注进度条（读 annotation manifest）
7. **问题与下一步**：按「地基 → 承重墙 → 装修」排序的问题清单，每条附具体下一步

## 核心机制：诚实度自动核验

页面上所有「真/假」标注**不是手写的结论**，而是构建脚本扫描 run 产物元数据算出来的：

| 环节 | 核验依据 |
| --- | --- |
| T1 五维打分 | `likert.*.explanation` 是否含 "Deterministic MVP"（mock 打分的指纹） |
| T2 病灶抽取 | `finding_graph.backend`（cxr_rule/ct_rule/mri_rule/placeholder）+ coverage 均值 |
| T4 危害判级 | `hazards.metadata.backend`（mock_judge / llm_judge / deterministic） |
| T8 报告生成 | `source` × `evidence_tier` 分布（medharness_cli / fallback / artifact_reuse） |

换一个 run 目录重新构建，全部徽章和数字会跟着新数据变。

## 页面职责

- `web/index.html`：主状态页。它把当前 run、最新探索性评估、OCR 审计、实验门禁和项目进度地图汇总在一页，供项目负责人日常判断开发状态。
- `web/control_panel.html`：次级工程控制面板。它沿用 CLI dashboard 的工程视角，适合查看单次 run 的病例级明细、质量门禁和原始证据链接。
- `web/legacy/`：历史快照与旧版构建代码，仅用于回看过去的页面结构和叙事，不作为当前状态的唯一依据。

主状态页和控制面板的证据范围必须分开阅读：

- **52 例工程基线**：来自当前主 run，用于检查契约、路由、评估和报告流水线是否能端到端运行；其中报告证据层级仍以 `artifact` / `debug_fallback` 为主，不能当作正式 fresh 生成结果。
- **11 例纯 DMX 探索性证据**：来自冻结的 CXR chest exploratory benchmark，包含真实角色调用和零 fallback，但样本量、唯一报告率和临床标注都不足以支持正式模型结论。

页面会明确标注 `pilot-only`、`formal_fresh`、`exploratory_fresh` 等证据层级，避免把工程可运行性误读成临床有效性。

## 重新生成

```bash
cd /path/to/medHarness2
PYTHONPATH=src python3 web/build_panel.py                        # 默认读 qualityfix 52 例 run
PYTHONPATH=src python3 web/build_panel.py --run-dir outputs/xxx  # 指向其它已完成 run
PYTHONPATH=src python3 -m medharness2.cli dashboard build \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --output web/control_panel.html
```

生成页会内嵌所选 run 的病例、阅片者、报告摘要和运行证据等数据。按本项目当前协作约定，`web/index.html`、
`web/control_panel.html` 以及 `web/legacy/` 中的生成 HTML **直接纳入 Git 并上传远程仓库**，无需对页面中的运行数据做脱敏处理。
但任何 API key、PAT、私钥、密码、Cookie 或其他凭据都禁止进入仓库；提交前必须执行 secret 扫描。

「最新进展」一节的数据源写死在脚本顶部常量（`SMOKE_EVAL_DIR` / `BENCH_DIR` / `OCR_AUDIT_DIR`），
「进度地图」一节的数据源同理（`STATUS_YAML` / `EXPERIMENTS_RESULTS` / `PILOT10_MANIFEST`），
有更新的冒烟/基准/实验聚合时改这些路径即可；目录不存在会自动跳过对应卡片或整节。

## 查看

```bash
# 直接双击 web/index.html，或起个静态服务：
cd web && python3 -m http.server 8080   # 浏览器访问 http://<host>:8080/
```

## 文件

```text
web/
  panel_template.html   模板：全部叙事内容 + CSS + 渲染 JS（改文案改这里）
  build_panel.py        构建脚本：读 run 产物 → 诚实度核验 → 注入 __PANEL_DATA__
  index.html            主状态页生成产物（自包含；由 build_panel.py 重建）
  control_panel.html    次级工程控制面板生成产物（由 CLI dashboard build 重建）
  legacy/               旧版构建脚本、模板与历史生成页快照
  README.md             本文件
```

- 叙事内容（比喻、实现解释、问题清单文案）维护在 `panel_template.html` 的
  `FLOW` / `WFS` / `TOOLS` / `ISSUES` 四个 JS 常量里；
- 运行数字、真实例子、诚实度徽章全部来自注入数据，模板里没有手填数字；
- 代表病例由构建脚本从当前 run 中选择，不存在首选病例时自动回退到发现数最多的病例。
