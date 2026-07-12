# medHarness2 · 项目认知面板

一个**自包含、可离线双击打开**的单页面板（`index.html`），目标读者是项目负责人本人：
用最通俗的人话 + 比喻，自上而下讲清楚整个系统——

1. **这是什么**：一句话定位 + 阅卷老师比喻 + 系统边界（评估教学，不做生成）
2. **整体流程**：一条 7 步流水线，每步标注背后的工具，点击可跳转
3. **设计哲学**：四层架构（工作流/模块/工具/基础设施）为什么这么设计
4. **四条工作流**：单病例 → 批量 → 科室 → 教学，规模逐级放大
5. **13 台仪器**（Tool 1–12 + 质量门禁）：每张卡 = 人话 + 比喻 + 真实输入输出例子
   + 实现方式徽章（🤖 调大模型 API / 🏠 本地医学模型 / 📐 纯规则代码）
   + **诚实度徽章**（✓ 真跑 / ⚠ 部分真 / ✕ 本次为假）+ 可展开的实现细节
6. **真实运行证据**：KPI、模态分布、候选报告"成色"图、医生百分位（附诚实说明）、门禁失败清单
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

## 重新生成

```bash
cd /path/to/medHarness2
python3 web/build_panel.py                        # 默认读 qualityfix 52 例 run
python3 web/build_panel.py --run-dir outputs/xxx  # 指向其它已完成 run
```

生成页会内嵌所选 run 的病例、阅片者和报告摘要等数据，因此 `web/index.html`、
`web/control_panel.html` 及对应的 `web/legacy/` 生成页均被 Git 忽略，只用于本地查看。
如需对外发布页面，必须先使用公开或已审核脱敏的数据重新构建，并再次执行隐私检查。

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
  index.html            本地生成产物（自包含、Git 忽略、勿手改）
  legacy/               旧版构建脚本与模板；其中生成页同样被 Git 忽略
  README.md             本文件
```

- 叙事内容（比喻、实现解释、问题清单文案）维护在 `panel_template.html` 的
  `FLOW` / `WFS` / `TOOLS` / `ISSUES` 四个 JS 常量里；
- 运行数字、真实例子、诚实度徽章全部来自注入数据，模板里没有手填数字；
- 代表病例由构建脚本从当前 run 中选择，不存在首选病例时自动回退到发现数最多的病例。
