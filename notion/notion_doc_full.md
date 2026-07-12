
============================================================
# 📄 Radiology Report Evaluation and Education Agent


============================================================
## 📄 文章安排


============================================================
### 📄 文章故事 - Research Story


## Purposes

## Introduction

## Method

## Results

## Discussion

## Conclusion

============================================================
### 📄 参考图表 - Reference Figures/Tables


## Main Papers

## Supplementary

## 图例库

============================================================
#### 📄 论文图表与实验可视化规划

本页用于把论文主图、实验结果图、分析图、消融图和关键表格统一成可执行的绘图路线图。

---


### 主文核心图
Fig. 1（hero，可立即制作）要画的是：系统总览：image/reference/candidate report -> finding 抽取 -> 对齐 -> error taxonomy -> L1/L2/L3 -> 复核/教育反馈。 这张图服务的论文问题是：论文需要先说明为什么放射报告评估不能只靠文本相似度或单一总分。 可用数据或产物来自：系统设计、harness artifact schema、OpenI smoke 运行记录。 参考图主要看 GEMA-Score / Fig. 2 Workflow；AgentsEval / Fig. 2 Agent Roles；CLEAR / Fig. 2 Framework；RadReason / Fig. 1 Scoring Workflow。制作时重点注意：借鉴模块化 workflow 和 agent card 结构，主图先讲清系统边界和证据流。
![参考图：GEMA-Score / Fig. 2 Workflow。借鉴它把 objective extraction、multi-agent scoring 和 final score composition 放进同一条流程。](attachment:232dda00-db4c-430f-beda-91b95afc5b9f:fig02_workflow.png)
![参考图：AgentsEval / Fig. 2 Agent Roles。借鉴 agent card 形式来呈现不同评估组件的输入、输出和职责边界。](attachment:57e4d18b-e339-4a08-b677-25023648feae:fig02_agent_roles.png)
![参考图：CLEAR / Fig. 2 Framework。借鉴从输入报告到结构化属性与评价输出的 evidence chain。](attachment:34afab25-2839-4c53-8990-56e89ac94543:fig02_framework.png)
![参考图：RadReason / Fig. 1 Scoring Workflow。借鉴把评分、reason 和 sub-score 串成可解释输出链路。](attachment:abe4d2fc-102f-4eb1-a9cb-d71a2d78f782:fig01_scoring_workflow.png)
Fig. 2（method，可立即制作）要画的是：单例评估全流程 A-J：以 openi_1 展示 reference/candidate、finding alignment、impression_error、Likert/quality 输出。 这张图服务的论文问题是：评估链路必须能回到具体病例、具体 finding 和具体错误，而不是只给汇总分。 可用数据或产物来自：single_case_evaluation_flow、openi_1 case artifacts。 参考图主要看 GEMA-Score / Multimodal Case Study；RadReason / Reason Examples；GREEN / GPT-4 Summary Example。制作时重点注意：适合做一页宽幅 case figure，把报告文本、错误记录和主指标放在同一证据链。
![参考图：GEMA-Score / Multimodal Case Study。借鉴把图像、报告、医生反馈和分项评分放到同一病例页。](attachment:72b5822c-c30d-4ebc-8cd8-630ccedc3c84:fig03_multimodal_case_study.png)
![参考图：RadReason / Reason Examples。借鉴错误理由和评分输出的并排展示方式。](attachment:b9461039-d229-4b4c-956e-50442e9f86d2:fig03_reason_examples.png)
![参考图：GREEN / GPT-4 Summary Example。借鉴把错误摘要、评分解释和病例上下文连在一起。](attachment:bc2955b2-7f4c-43b8-ab02-e6507bb20db0:fig03_gpt4_summary_example_page.png)
Fig. 3（method/analysis，可立即制作）要画的是：Reference vs candidate finding graph 对齐图：matched / omitted / overcall / contradiction / anatomy attributes。 这张图服务的论文问题是：结构化 finding 对齐是临床事实评价的核心中间表示。 可用数据或产物来自：reference_findings、candidate_findings、alignments、errors artifacts。 参考图主要看 RadGraph / Report Graph；ReXVal / Error Categories；Chest ImaGenome / Knowledge Graph Example。制作时重点注意：借鉴 graph + taxonomy 的组合，把错误检测从自由文本判断转成可审查结构。
![参考图：RadGraph / Report Graph。借鉴报告实体、属性和关系图的可视表达。](attachment:b9c3c191-9a25-4fd7-8c5f-8aad2991d26b:radgraph_fig02_report_graph.png)
![参考图：ReXVal / Error Categories。借鉴错误类型与报告差异之间的映射方式。](attachment:23557053-66ee-41fc-8169-fd0ad70f7ce3:related_fig02_error_categories.jpg)
![参考图：Chest ImaGenome / Knowledge Graph Example。借鉴把解剖位置、属性和关系组织成图证据。](attachment:cd225fc2-71ac-4915-bd94-bba6150407ce:fig01_knowledge_graph_example.png)
Fig. 4（method，可立即制作）要画的是：医生可读反馈卡：总分、子分、错误类型、证据句、修改建议、是否需人工复核。 这张图服务的论文问题是：系统价值不只是评分，还要把错误解释成医生可复核、可教学的反馈。 可用数据或产物来自：Case result、LLMJudgeSummary、ErrorRecord、未来 correction suggestion 对象。 参考图主要看 RadReason / Output Comparison；GEMA-Score / Multimodal Case Study；CLEAR / Annotation Interface。制作时重点注意：重点借鉴 output card 和证据句高亮，避免只画 dashboard 数字。
![参考图：RadReason / Output Comparison。借鉴总分、子分和自然语言理由同时出现的反馈卡结构。](attachment:149b38b0-d0da-4847-8191-76708e7b9131:fig01_output_comparison.png)
![参考图：GEMA-Score / Multimodal Case Study。借鉴把系统反馈贴回具体临床病例。](attachment:72b5822c-c30d-4ebc-8cd8-630ccedc3c84:fig03_multimodal_case_study.png)
![参考图：CLEAR / Label Annotation Interface。借鉴医生可审查的标签/属性界面组织方式。](attachment:c31ecdd3-3e1c-49c2-a056-03eef4bad2e8:fig05_label_annotation_interface.png)

### 实验结果图
Fig. 5（experiment-setup，可立即制作）要画的是：实验协议图：OpenI 50 smoke、1 例 live GPT-5.5、未来华西 gold standard、candidate source、offline fallback、输出 artifacts。 这张图服务的论文问题是：实验必须清楚区分 smoke、live generation 和未来真实金标准验证。 可用数据或产物来自：experiment_plan、harness_v1、PLAN、summary artifacts。 参考图主要看 RadCliQ/ReXVal / Alignment Protocol；MRScore / Reward Pipeline；ReXamine-Global / Multi-site Setup。制作时重点注意：caption 必须写明 OpenI/IU X-Ray offline smoke, n=50，不能写成最终临床验证。
![参考图：RadCliQ/ReXVal / Alignment Protocol。借鉴 metric 与医生判断对齐的实验协议表达。](attachment:985a34ba-f14f-458e-9032-a8cfb76a7e11:related_fig01_alignment_protocol.jpg)
![参考图：MRScore / Reward Pipeline。借鉴数据构造、评分规则和模型训练放在同一页的布局。](attachment:f810430b-06b8-4568-a24c-7e762f31c80f:fig01_reward_pipeline_and_error_rubric.png)
![参考图：ReXamine-Global / Multi-site Dataset Characteristics。借鉴多站点/多阶段实验口径的清晰列法。](attachment:3be1b64a-6af3-4406-8be7-4452ad3f5cb6:table01_multisite_dataset_characteristics.png)
Fig. 6（result，可立即制作）要画的是：主结果概览：50 例 success/failure/review、Finding P/R/F1、omission/overcall/contradiction、clinical quality、L3 averages。 这张图服务的论文问题是：当前 harness 已跑通完整评价体系，并能输出批量主指标。 可用数据或产物来自：OpenI/IU X-Ray offline smoke, n=50；50/50 success；36 needs_review；finding F1 约 0.917；clinical quality 约 91.07；L3 section completeness 0.59。 参考图主要看 GEMA-Score / Radiologist Correlation；MRScore / Human Correlation Table；RadEval/ReXrank / Leaderboard。制作时重点注意：用主结果 table + 小型 bar panel；所有数字标注 smoke-stage。
![参考图：GEMA-Score / Radiologist Correlation。借鉴主结果中把 metric 表现和医生一致性放在一起。](attachment:804cab2f-621a-44c9-8e4e-ef0c4b492d41:fig04_radiologist_correlation.png)
![参考图：MRScore / Human Correlation Table。借鉴用关键表格承载自动指标与人工评分相关性。](attachment:f7c32d5d-5c10-4966-add9-592d0b2886ea:table03_human_correlation_metrics.png)
![参考图：RadEval/ReXrank / Leaderboard。借鉴模型/指标排名图的 compact 结果呈现。](attachment:2bef6696-2a3c-4f26-b9ed-e1e2382489b8:rexrank_fig02_model_ranking.png)
Fig. 7（analysis，可立即制作）要画的是：Case-level 分布：finding F1 / recall / clinical_quality_score / needs_review 的散点、箱线或条带图。 这张图服务的论文问题是：case-level 分布能暴露平均分掩盖的复核压力和失败模式。 可用数据或产物来自：50 个 case-level result.json。 参考图主要看 HeadCT-ONE / Cross-site Boxplots；VERT / Distribution；ReXrank / Metric Distribution；AgentsEval / Metric Trends。制作时重点注意：建议用 needs_review 作为颜色或形状编码，突出复核队列。
![参考图：HeadCT-ONE / Cross-site Boxplots。借鉴用箱线图表现病例或站点级分布。](attachment:ac408f9e-9dfa-4cde-b0f6-0c55a1bf8bf5:fig02_cross_site_boxplots.png)
![参考图：VERT / Distribution。借鉴分布图展示 metric 在不同样本上的波动。](attachment:3681503a-cffb-40bf-8552-bd186afd019f:fig05_radeval_distribution.png)
![参考图：ReXrank / Metric Distributions。借鉴多指标分布对比的版式。](attachment:28903e8b-1ac2-43a9-b295-2da860639633:rexrank_fig03_metric_distributions.png)
![参考图：AgentsEval / Metric Trends。借鉴按样本走势暴露局部不稳定的方式。](attachment:be9d69ee-6540-44ff-9e06-efd0c6ee5082:fig03_medval_bench_trends_page.png)

### 分析/消融图
Fig. 8（analysis，可立即制作）要画的是：错误类型与严重度热力图：当前展示 impression_error/omission，未来扩展到 12 类 taxonomy。 这张图服务的论文问题是：错误类型和严重度比单一 quality score 更能解释系统风险。 可用数据或产物来自：当前 errors.json 与 error_type_counts；未来真实错误标注和医生复核。 参考图主要看 ReXErr-v1 / Error Taxonomy；CRIMSON / Severity Analysis；VERT / Error-type F1；CTest / Reliability Heatmaps。制作时重点注意：当前可做 v0 频次条形图；完整 severity heatmap 依赖更多真实错误。
![参考图：ReXErr-v1 / Error Taxonomy。借鉴 clinically meaningful error taxonomy 的视觉组织。](attachment:7dadcb07-b312-4843-a530-3abdac890c92:fig02_error_taxonomy.png)
![参考图：CRIMSON / Severity Analysis。借鉴错误严重度和结构化错误分类的联合呈现。](attachment:abda15f6-8bd1-4b45-beaa-fcc68198479d:fig04_error_severity_analysis.png)
![参考图：VERT / Error-type F1。借鉴按错误类型评价 judge 可靠性。](attachment:b5e4c44f-cb0f-4946-9605-a96844c8cea4:fig04_error_type_f1_radeval.png)
![参考图：CTest / Reliability Heatmaps。借鉴用热力图展示指标对错误等级的响应。](attachment:6de046fc-18fa-4db3-8ba8-93eb8c5bdd46:fig02_metric_reliability_heatmaps.png)
Fig. 9（result/analysis，可立即制作）要画的是：L3 辅助指标图：section completeness、findings-impression consistency、readability、ROUGE/BERTScore proxy 等。 这张图服务的论文问题是：报告质量不仅是临床事实覆盖，还包括结构、语言和辅助 NLP 信号。 可用数据或产物来自：summary.l3_averages 与每例 l3_auxiliary.json。 参考图主要看 DOCLENS / Multi-aspect Metrics；CLEAR / Expert Attributes；RadReason / Sub-score Results。制作时重点注意：建议用 grouped bar 或 radar；caption 说明 BLEU/ROUGE/METEOR/BERTScore 当前为 lightweight proxy。
![参考图：DOCLENS / Multi-aspect Metrics。借鉴把多维文本质量指标拆成可解释子项。](attachment:4462b984-3034-4eb0-a672-b5f04539070c:fig02_metric_illustration_page.png)
![参考图：CLEAR / Expert Attributes。借鉴专家属性表组织多维评估字段。](attachment:68aca976-2b2f-4580-b8c2-18ec61be3428:table01_expert_attributes_page.png)
![参考图：RadReason / Sub-score Results。借鉴子分维度结果图的表达方式。](attachment:9d436e27-60c3-487b-a86b-2ac8c6e74c00:fig02_subscore_results.png)
Fig. 10（ablation，可选补充）要画的是：组件/策略消融：L1 vs L2 vs L3、offline rule vs LLM judge、fallback 对结果的影响。 这张图服务的论文问题是：需要证明各层指标、judge 设置和 fallback 策略不是装饰，而是影响评价可靠性。 可用数据或产物来自：后续 ablation runs；不同 judge/backbone/fallback 设置的重复实验。 参考图主要看 MRScore / Backbone Ablation；RadReason / Reward Ablation；VERT / Prompt and Metric Correlation；CTest / Reliability。制作时重点注意：当前只列规划；等有多组运行后再制作主文或补充图。
![参考图：MRScore / Backbone Ablation。借鉴把相关性结果和 backbone 消融放在同一证据块。](attachment:c41286aa-4ed9-423f-80ec-8e3b019d258c:fig02_metric_correlation_and_backbone_ablation.png)
![参考图：RadReason / Reward Ablation。借鉴用表格证明 reason/sub-score 机制贡献。](attachment:4189f087-d6cc-4613-8a19-bc83867e5f52:table01_correlation_ablation_page.png)
![参考图：VERT / Prompt and Metric Correlation。借鉴 prompt/judge 设置与相关性的对照表。](attachment:2a33f670-e958-4e92-804d-a98b71d635b0:table01_02_prompt_metric_correlation_page.png)
Fig. 11（result，依赖华西/医生复核）要画的是：医生一致性验证：Spearman/Kendall/ICC、pairwise preference、专家错误计数相关性。 这张图服务的论文问题是：最终论文的核心可信度来自和医生判断对齐。 可用数据或产物来自：未来华西 gold standard 与医生复核记录。 参考图主要看 GREEN / Expert Correlation Matrix；LLM-RadJudge / Agreement；ReFINE / Alignment Scatter；GEMA-Score / Correlation。制作时重点注意：这应是最终临床验证主结果之一，当前不要用 OpenI smoke 替代。
![参考图：GREEN / Expert Correlation Matrix。借鉴专家均值、专家间一致性和模型输出的相关性矩阵。](attachment:ae4a42a4-e2ad-4294-91a1-2b2d92cb06dd:fig06_expert_correlation_matrix.png)
![参考图：LLM-RadJudge / Agreement。借鉴 LLM 与 radiologist agreement 的主结果表达。](attachment:ea6c1882-f979-4648-9d84-10899b82bd3e:fig01_agreement.png)
![参考图：ReFINE / Alignment Scatter。借鉴 human alignment scatter 的视觉语法。](attachment:fea0fa16-01a2-4dcd-923e-f73bd5d56131:fig04_alignment_scatter.png)
Fig. 12（result/table，依赖华西/医生复核）要画的是：模型/医生/科室级 leaderboard：modelwise weighted、hazardwise weighted、Top-K reports/models。 这张图服务的论文问题是：系统后续可以支撑模型、医生和科室级报告质量比较。 可用数据或产物来自：后续 workflow2/workflow3、模型生成报告池、医生分组数据。 参考图主要看 RadEval/ReXrank / Leaderboard；CheXpert / Radiologist-model Comparison；RadGraph-XL / Modality Statistics。制作时重点注意：当前作为未来完整论文/扩展实验图，不放入已完成结果。
![参考图：RadEval/ReXrank / Leaderboard。借鉴模型或指标排行榜的主结果呈现。](attachment:2bef6696-2a3c-4f26-b9ed-e1e2382489b8:rexrank_fig02_model_ranking.png)
![参考图：CheXpert / Radiologist-model Comparison。借鉴医生和模型表现并列比较。](attachment:d64fcd35-1d04-45a6-90f9-6d07d447b071:fig03_radiologist_model_comparison.png)
![参考图：RadGraph-XL / Modality Statistics。借鉴跨模态/部位统计图用于科室级扩展。](attachment:866352b3-e86a-4a55-9595-73e30d7a0e2d:radgraph_xl_fig01_statistics_page.png)

### 表格与补充图
Table 1（table，可立即制作）要画的是：Dataset & run summary：数据源、case 数、模态/部位、candidate source、gold source、review status。 这张图服务的论文问题是：读者需要一眼看到每个实验阶段的数据、case 数、gold source 和输出对象。 可用数据或产物来自：experiment_plan、harness_v1、summary.json、未来华西数据登记。 参考图主要看 CheXpert / Label Space；RadGraph / Annotation Statistics；MRScore / Setup Tables。制作时重点注意：主文表格可以先列 OpenI smoke 和 live_one，再预留 Huaxi gold standard 行。
![参考图：CheXpert / Label Space。借鉴数据集、标签空间和 labeler 示例合并成表。](attachment:6c7c62de-5135-435c-91c1-b21f4ab97adf:table01_label_space_and_labeler_example.png)
![参考图：RadGraph / Annotation Statistics。借鉴数据规模、标注对象和统计口径表。](attachment:83eeac13-45d3-493a-8981-b335f366f14d:radgraph_table01_annotation_statistics_page.png)
![参考图：MRScore / Setup and Rating Validation Table。借鉴实验阶段与验证对象的表格结构。](attachment:8c0cbf17-978a-4624-8024-6c57ac2b7585:table02_gpt4_rating_validation.png)
Table 2（table，可立即制作）要画的是：Metric taxonomy：L1/L2/L3 指标、error taxonomy、artifact 字段、对应工具/模块。 这张图服务的论文问题是：指标体系需要和工具/模块/artifact 字段一一对应，方便复现。 可用数据或产物来自：evaluation_system_completion_audit、single_case_evaluation_flow、schemas/metrics 实现。 参考图主要看 CLEAR / Expert Attributes；ReXErr-v1 / Taxonomy Table；CRG Score / Metric Equations。制作时重点注意：建议作为主文表或 appendix table，明确 lightweight proxy 和生产替换项。
![参考图：CLEAR / Expert Attributes。借鉴把细粒度属性与评价字段一一列出。](attachment:68aca976-2b2f-4580-b8c2-18ec61be3428:table01_expert_attributes_page.png)
![参考图：ReXErr-v1 / Taxonomy Table。借鉴错误 taxonomy、定义和类别说明。](attachment:fd3815f8-3d4f-4ef8-8ea1-a4ae7c22927b:table01_error_taxonomy_page.png)
![参考图：CRG Score / Metric Equations。借鉴指标公式、字段和解释的并列呈现。](attachment:9483974f-24b0-4182-9c95-d9ed08e6f3b0:fig_metric_equations.png)

---


### 参考图索引
上方每个规划项已经直接嵌入对应参考图；参考图优先从现有 Reference Figures Tables 的 30 个论文子页里取，不新增二手截图。系统/方法主图主要看 GEMA-Score、AgentsEval、CLEAR 和 RadReason，借鉴模块边界、agent 分工、输入输出和评分链路；单例解释图主要看 GEMA-Score、GREEN 和 RadReason，借鉴把病例文本、错误、评分、理由放在同一页里的方式；图谱和错误 taxonomy 主要看 RadGraph、ReXVal、ReXErr-v1 和 Chest ImaGenome，借鉴 finding graph、错误类别、解剖属性关系；实验协议图主要看 RadCliQ/ReXVal、MRScore 和 ReXamine-Global，借鉴数据来源、构造策略、医生对齐协议和多站点口径；主结果和 leaderboard 主要看 GEMA-Score、MRScore、RadEval/ReXrank 和 CheXbert，借鉴人类一致性、相关性、排序和关键表格；分布、敏感性和多维质量指标主要看 HeadCT-ONE、VERT、CTest、AgentsEval、DOCLENS、CLEAR 和 RadReason。

============================================================
## 📄 评估实验安排


## Radiologist Evaluation Study

## Radiologist Finding Extraction Study

## Radiologist Error Hazard Evaluation Study

## Radiologist Educational Study

## Validation of Image-to-text AI Models

## Validation of Modality Recognition VLM
(only for VLM if used)

============================================================
## 📄 系统设计 - Systems Design


============================================================
### 📄 系统3 - LLM报告评分系统（Agent）


## 整体系统设计 - Overall Designs

### 单独报告评估系统 - Individual Report Evaluation

### 报告对比的评估系统 - Comparative Report Evaluation

## Agent 流程
```Mermaid
graph TD
	1
```

## Agent 工具

### 图生文工具 - Report Generation Tool

### 模态识别工具 - Modality Recognition Tool

### 中英翻译工具 - Translation Tool

### 报告评估工具 - Report Evaluation Tools

## 系统流程 - Design Flows

## 评估流程 - Evaluation Flow

============================================================
## 📄 **文献综述 - **Literature Review


## 医疗Foundation模型与对话/报告生成能力

## 大模型对医疗工作的评估
PET

============================================================
## 📄 组会总结 - Meeting Summary


## 小组会：2026-04-25

## 小组会：2026-04-18

## 小组会：2026-04-11

## 小组会：2026-04-04

## 小组会：2026-03-28

## 小组会：2026-03-21

## 工作安排

## 系统设计 - Architectural Design

##### 🗃️ 数据库: 文献综述 - Literature Review (new)
| Name | Author | Status | Year | Note | URL | Journal |
| --- | --- | --- | --- | --- | --- | ---
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='title' raw=[['Holistic evaluation of large language models for medical tasks with MedHELM']]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='?gDz' raw=[['Bendi']]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='JKqf' raw=[['Done']]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key=']~U]' raw=[['2026']]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='kTw|' raw=[['  • LLM judge need multiple prompts testing\n  • Find the way to evaluate your LLM judge (both via dataset and clinician correlation)']]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='oVG}' raw=[['https://www.nature.com/articles/s41591-025-04151-2', [['a', 'https://www.nature.com/articles/s41591-025-04151-2']]]]
  [20707ab9-ace7-837d-a1a4-0125485f2682]: row prop key='yO:}' raw=[['Nat. Med.']]
| Holistic evaluation of large language models for medical tasks with MedHELM | Bendi | Done | 2026 |   • LLM judge need multiple prompts testing   • Find the way to evaluate your LLM judge (both via dataset and clinician correlation) | [https://www.nature.com/articles/s41591-025-04151-2](https://www.nature.com/articles/s41591-025-04151-2) | Nat. Med. |
  ── 行「Holistic evaluation of large language models for medical tasks with MedHELM」内嵌页面:

## Annotated Bibliography
    This article introduces a comprehensive benchmark with holistic evaluation approach for evaluating the performance of currently cutting edge LLM in real-world clinical task.
    They utilized and categorized both public and private medical dataset to mirror actual clinical workflows, and assessed models on both task performance, and cost. From 9 frontier LLMs, reasoning models, especially DeepSeekR1 and o3-mini, perform best in most clinical tasks.
    By classifying and mapping evaluation tasks to real clinical activities, the study enhances the benchmark’s relevance to practice and covers the majority of the clinical workflows.
  ── 行「Holistic evaluation of large language models for medical tasks with MedHELM」内嵌页面:

## Problems & Purpose
    - benchmark questions do not match real-world settings
    - limited utilization of real-world data
    - limited tasks diversity
  ── 行「Holistic evaluation of large language models for medical tasks with MedHELM」内嵌页面:

## Methods

### Dataset
![Fig 2: MedHELM taxonomy
→ definition of real world medical task categories
  • Clinical decision support (12 benchmarks)
  • Clinical note generation and Medical research assistance (6 benchmarks)
  • Patient communication (8 benchmarks)
  • Administration and workflow (5 benchmarks)
14 publics + 16 privates (7 approval pending)](attachment:f0e8036b-0567-449f-bbbb-de9474de20e2:Screenshot_2026-05-08_at_14.37.09.png)
    these dataset classification was prove by letting clinicians classified and compare with original classification results

### Benchmarks
    **Construction of benchmark suite**
    - Context: Raw input for LLM
    - Prompt: Standardized instruction template
    - Evaluation metrics:
exact-match (token-wise)
micro-F1 (multi-label classification)
LLM-jury (opened-text generation)
    - +/- Gold-standard response
    **LLM-Jury Approach**
    - 3 models (3 LLMs) Likert-scale protocol: accuracy, completeness and clarity
    - Evaluate the approach by comparing with 20 clinicians and traditional metrics (intraclass correlation coefficient, ICC)
    - LLM-jury prompt → Supplementary Fig. 2
![Fig. 1(b): A suite of benchmarks
Pulling public or private dataset → mapping with predefined taxonomy (real clinical task classification) → structure the dataset into pieces for integration benchmark](attachment:e32c0b14-48df-43a4-b176-5b56b984c163:Screenshot_2026-05-08_at_14.37.45.png)

### Evaluations Flow
![Fig. 1(c): Frontier LLMs evaluation flow (main flow of benchmarking)
  • Separate LLMs into 2 groups: reasoning and non-reasoning LLM
  • Evaluate across all existing benchmarks
→ using evaluation metrics (accuracy and semantic) and LLM-jury with clinical agreement](attachment:a1934ed4-7672-4953-8a01-33ccaf413903:Screenshot_2026-05-08_at_14.33.03.png)
  ── 行「Holistic evaluation of large language models for medical tasks with MedHELM」内嵌页面:

## Results
    → MedHELM organizes tasks by clinical function rather than NLP task type (for example, NLI, NER), incorporates real-world EHR data and includes cost-performance analysis absent from these frameworks.

### DeepSeek R1 and o3-mini model performed best in both overall and individual result across all benchmarks
![Table 1: Overall performance of 9 frontier LLMs on 37 MedHELM benchmarks
(pairwise win-rate + macro average score)](attachment:4bced122-844c-4507-8785-d8c3f3e66c92:Screenshot_2026-05-08_at_14.55.31.png)
![Fig 4: Model performance across MedHELM categories
(normalized score)](attachment:72f24ea9-e48c-44ab-9fc0-f1cf45421983:Screenshot_2026-05-14_at_09.16.50.png)
![Fig 3: Individual performance of 9 frontier LLMs across all 37 MedHELM benchmarks
(normalized score; each benchmark has individual score calculation)
  • EM: exact match
  • Jury score: average normalized score from 3 frontier LLMs
  • MedCalc: accuracy of exact match or thresholded match
  • MedFlagAcc: binary accuracy of detecting error
  • EHRSQLExeAcc: execution accuracy of generated code
  • MIMICBillingF1: F1 score if ICD-10 code](attachment:16960213-97bf-43c8-a2bc-9669a7dade8e:Screenshot_2026-05-08_at_14.58.25.png)

### Smaller open-source models achieved reasonable performance, but significant deficits than in-domain reasoning models
    - `Qwen-2.5-7B-instruct`
    - `Phi-3.5-mini-instruct`
    - `MedGemma-4b-it`

### LLM-jury have better correlation with clinician than automated metrics
![Extended Data Table 4: Agreement of LLM-jury with automated metrics and clinician ratings
ICC of 0.47 with clinician → outperform both inter-clinician agreement (0.43) and automated metrics.](attachment:00328588-eb18-4382-b442-65facfa41ed5:Screenshot_2026-05-08_at_15.52.46.png)

### Non-reasoning models run with lower cost but with lower performance
![Fig 5: Performance vs. computational cost of all models
→ author didn’t summarize which model is best cost-effective](attachment:33a5ec75-2a99-4f19-894d-634e5cbfaa14:Screenshot_2026-05-14_at_09.19.05.png)
  ── 行「Holistic evaluation of large language models for medical tasks with MedHELM」内嵌页面:

## Limitations
    - LLM-jury only validate on 2 benchmarks
    - Uneven distribution of benchmark categories
    - Current rubrics only evaluate on benchmark level (not case level)
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='title' raw=[['Evaluating and mitigating bias in AI-based medical text generation', [['b']]]]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='?gDz' raw=[['Chen']]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='JKqf' raw=[['Done']]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key=']~U]' raw=[['2026']]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='kTw|' raw=[['  • reference the bias calculation → might be useful for finding-level or modality-level bias']]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='oVG}' raw=[['https://www.nature.com/articles/s43588-025-00789-7', [['a', 'https://www.nature.com/articles/s43588-025-00789-7']]]]
  [a3507ab9-ace7-83ec-87b5-019a5ef8fa54]: row prop key='yO:}' raw=[['Nat. Com. Sci.']]
| **Evaluating and mitigating bias in AI-based medical text generation** | Chen | Done | 2026 |   • reference the bias calculation → might be useful for finding-level or modality-level bias | [https://www.nature.com/articles/s43588-025-00789-7](https://www.nature.com/articles/s43588-025-00789-7) | Nat. Com. Sci. |
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:

## Annotated Bibliography
    This study investigates and addresses demographic bias in AI-powered medical text generation tasks, such as radiology report generation and summarization.
    The authors first demonstrate that standard models exhibit significant performance disparities across subgroups defined by race, sex, and age, using datasets like MIMIC-CXR and PubMed. To quantify this issue, they introduce a new metric, the Metric-aware Fairness Difference (MFD), which measures performance gaps between demographic groups.
    They then propose a novel selection optimization framework that uses a combination of a selected cross-entropy loss and a ranking loss to mitigate these observed biases.
    The key finding is that their proposed framework effectively reduces the fairness gap across all tasks and datasets while maintaining or improving overall text quality.
    The study highlights the importance of evaluating and correcting for fairness in clinical AI applications.
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:

## Problems & Purpose
    - Explore the existing of bias problem in image-based diagnosis, text-based summarization of AI model
    - Purpose a metric-aware unfairness indicator
    - Purpose a selection optimization framework applicable to any task and model
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:

## Methods

### Data
    MIMIC-CXR: image-text pairs (one report per patient)
→ race, sex and age
    PubMed dataset: full-text-abstract pairs
→ race and sex

### Model Pipeline
![Fig 2: Selection algorithm
(in this research they use the report generation and text summarization as example, but the framework can be applied to any task)
→ use 2 loss for model to learn
  **• Selected cross-entropy loss**: select only top k largest cross-entropy loss for text-generation (same as loss we normally use but only allow backpropagation of top k inputs)
**  • Ranking loss**: let model predict score of reference/candidate (generated by other method) as rating score (represent the quality of ground truth), and order the rank (should align with other traditional metrics, e.g. ROUGE, CheXpert score)](attachment:c184449a-cfa4-4511-9d07-79d045be0fa6:Screenshot_2026-05-15_at_13.43.51.png)
![Fig 1: Overview of model training pipeline](attachment:11c3c375-d265-46b7-9ad3-feba4a58bb1b:Screenshot_2026-05-15_at_13.43.34.png)
    **Baseline Models:**
    - report generation: `R2Gen`
    - report summarization: pre-trained `BART-large`
    - paper summarization: pre-trained `BART-large` , `Llama-2-13B`

### Evaluation
    **Text quality metrics**
    - ROUGE score
    - CheXpert score
    **Metric-aware fairness difference (MFD)**
    → pairwise fairness difference (PFD)
    calculating a differential score between subgroups for each specific metric by subtracting the score of the lowest-performing group from the highest score within the subgroups.
![Formula 9: MFD calculation
  • n represents the number of instances
  • Metric_subgroup1(i) and Metric_subgroup2(i) denote the metric values for the i th instance in subgroup 1 and subgroup 2, respectively](attachment:d5741103-0b70-4665-814c-80fb65603fad:Screenshot_2026-05-15_at_14.38.19.png)
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:

## Results

### Text-generation quality of baseline models for all datasets differs in most of the considered subpopulations
![Fig 3: Performance disparities across demographics.
→ compare raw metrics
(a) ROUGE - report generation
(b) ROUGE - report summarization
(c) ROUGE - paper summarization
(d) CheXpert - report generation
(e) CheXpert - report summarization
Note: sample size = 6](attachment:d0f0e3dd-31c1-4ff1-adff-82dbb55b7373:Screenshot_2026-05-15_at_14.12.16.png)

### Intersectional subgroups frequently experience notable biases in text generation
    → intersectional groups, defined as patients belonging to two subpopulations
![Fig 4: Performance disparities across intersectional groups
→ compare raw ROUGE and CheXpert
(a) report generation (sex-race)
(b) report summarization (sex-race)
(c) report summarization (sex-age)
Note: sample size = 6](attachment:8713dbca-f655-40f8-b491-a697a96a7638:Screenshot_2026-05-15_at_14.19.40.png)

### **Why unfairness exists in radiology-report generation tasks**
    - ROUGE score is related to the target length
→ a mild correlation where longer references tend to lead to lower ROUGE scores
    - CheXpert score is related to the original positive labels
→ If a group has more diseases classified as positive, its CheXpert score tends to be higher
    - Number of training cases
→ Larger number of training lead to better performance/quality

### The purposed model is effective in reducing disparities
across all datasets with respect to age, sex and race
![Fig 5: Reduction of MFD comparing purposed model with baseline
→ calculate MFD for every metrics
(a) report generation
(b) report summarization
(c) paper summarization
Note: sample size = 6](attachment:23251ed4-ca36-4b59-95f4-d1f191fcc046:image.png)
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:

## Limitations
    - inherent bias within existing datasets
    - selective optimization depends on quality of fairness metrics used
    - unexplored performance in real-time or resource constrained environment
  ── 行「**Evaluating and mitigating bias in AI-based medical text generation**」内嵌页面:
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='title' raw=[['Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation']]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='?gDz' raw=[['Phadke']]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='JKqf' raw=[['Done']]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key=']~U]' raw=[['2026']]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='kTw|' raw=[['  • reference the Likert-scale table\n  • can try in-domain (literature) vs. generic (API)']]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='oVG}' raw=[['https://www.nature.com/articles/s41746-026-02586-6', [['a', 'https://www.nature.com/articles/s41746-026-02586-6']]]]
  [46c07ab9-ace7-83b4-8389-0127da408c2a]: row prop key='yO:}' raw=[['npj Digit. Med.']]
| Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation | Phadke | Done | 2026 |   • reference the Likert-scale table   • can try in-domain (literature) vs. generic (API) | [https://www.nature.com/articles/s41746-026-02586-6](https://www.nature.com/articles/s41746-026-02586-6) | npj Digit. Med. |
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:

## Annotated Bibliography
    This study aimed to evaluate and compare oncologic radiology reports generated by an in-domain LLM and a generic LLM from the perspective of different clinicians.
    Using 200 internal cases, reports were generated and then assessed by authoring radiologists, independent radiologists, and oncologists on criteria such as completeness, correctness, and clinical utility.
    The results showed that the in-domain model's performance was comparable to the original human authors and was generally preferred by radiologists.
    Notably, all reports, whether human or AI-generated, were rated as having low potential for patient harm, but the inter-rater reliability for quality assessment was low across all evaluator groups.
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:

## Problems & Purpose
    - Evaluate the LLM generated report from different role of clinicians
    - Compare the performance between generic and in-domain LLM
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:

## Methods

### Data
    Internal oncologic radiology data → 200 cases
(from 4 radiologists, 50 each)

### LLM report generation
    **LLM model**
    - In-domain model: `RadAI` (private model)
    - Generic model: `GPT-4.1`
    **LLM input**
    - finding section
    - clinical indication
    - imaging protocol

### Assessment
    **Raters**
    - original authoring radiologists (n=4)
    - independent radiologists (n=3)
    - oncologists (n=3)
    **Likert-scale Evaluation**
    - completeness（完整性）
    - correctness（准确性）
    - conciseness（简洁性）
    - potential patient harm（危害性）
    - clarity（清晰度）
    - clinical utility（实用性）
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:

## Results

### In-domain models performed similar to original authoring radiologists
![Table 4: pairwise quality rating comparison](attachment:fa52eae1-eeb1-4e39-b911-3dfd4fe27dfd:image.png)

### Radiologists are more likely to favor report generated by in-domain model
    - radiologists are all favor model generated report, especially in-domain model
    - oncologists don’t have any specific preference
![Table 1: evaluator preference](attachment:ae12c501-1be4-40f3-b31c-9608b0cdd754:Screenshot_2026-05-14_at_16.13.17.png)

### Hazard level are low for both radiologist-written and model-generated report
    → Table 4

### Inter-reader reliability of Likert-scale evaluation are low for all readers
![Table 5: inter-rater reliability
Krippendorff’s α values are shown with 95% confidence intervals (CI) for evaluator groups with overlapping cases. Higher α indicates greater agreement](attachment:ed8cbcdc-594b-4260-a11f-63661d409758:Screenshot_2026-05-14_at_16.16.00.png)
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:

## Limitations
    - single center
    - retrospective
    - Subjective hazard level evaluation
    - small dataset
    - didn’t cooperate actual clinical outcome
  ── 行「Comparison of AI-generated radiology impressions; a multi-stakeholder evaluation」内嵌页面:
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='title' raw=[['Error detection in emergency radiology reports using a large language model: multistage evaluation study', [['b']]]]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='?gDz' raw=[['Shen']]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='JKqf' raw=[['Done']]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key=']~U]' raw=[['2026']]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='kTw|' raw=[['  • apply staging to the selection of open-source models']]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='oVG}' raw=[['https://doi.org/10.2196/86841', [['a', 'https://doi.org/10.2196/86841']]]]
  [11e07ab9-ace7-8327-b9e3-8148cbb4ee20]: row prop key='yO:}' raw=[['JMIR']]
| **Error detection in emergency radiology reports using a large language model: multistage evaluation study** | Shen | Done | 2026 |   • apply staging to the selection of open-source models | [https://doi.org/10.2196/86841](https://doi.org/10.2196/86841) | JMIR |
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:

## Annotated Bibliography
    This study evaluates the ability of Large Language Models (LLMs) to detect errors in non-English emergency radiology reports, addressing a gap in research that often relies on synthetic data or single-institution studies.
    The methodology involved a four-stage validation process: an initial screening of five LLMs, few-shot optimization to select the best model, benchmarking against six radiologists, and finally, a real-world validation using 800 unverified reports.
    The key findings indicate that the `DeepSeek-R1` model performed best, achieving error detection rates comparable to human radiologists, and in some cases, outperforming junior residents.
    Furthermore, LLMs demonstrated a significant time efficiency advantage, processing reports much faster than their human counterparts, though their agreement with radiologists was only fair to moderate.
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:

## Problems & Purpose
    - Explore the LLM complex clinical decision skill on emergency report
    - Most studies use synthetic error / single institution
    - Explore the performance on non-English language
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:

## Methods

### Data
    **Dataset 1**
    → 3 types of emergency radiology reports
    - CT (n=5237)
    - MRI (n=381)
    - radiography (n=1817)
    **Dataset 2**
    - 50 error-free emergency radiology reports that passed quality control
    - 50 erroneous reports that did not meet quality control
    **Real-world Dataset**
    → 800 unverified real emergency radiology reports with finalized version as ground truth
    - CT (n=400)
    - MRI (n=200)
    - radiography (n=200)

### Error Categories
![Table 1: Types of medical error](attachment:9a502073-db7c-4774-8055-f26bc62db3c8:Screenshot_2026-05-15_at_16.01.58.png)

### Multistage Validation
![Table 1: Main Validation study flow](attachment:e06c9214-e829-4c0a-8ed7-0797eeaa5fee:Screenshot_2026-05-15_at_20.22.02.png)
    **Stage 1: initial screen 5 LLMs**
    - random sample dataset 1 (n=200, 100 error-free + 100 synthetic errors)
    - select top 2 models
→ `DeepSeek-R1`+ `Grok3`
    **Stage 2: few-shot optimization**
    - dataset 2 (50 pass-qc + 50 under-qc)
    - further selection of 2 best models from stage 1
    - select the best model
→ `DeepSeek-R1`
    **Stage 3: Benchmarking against radiologists**
    - dataset 2 (50 pass-qc + 50 under-qc)
    - let 6 different experience level of radiologists detect error and time-to-completion
    - compare with the result of `DeepSeek-R1` & `Grok3` in stage 2
    **Stage 4: Real-world validation**
    - real-world dataset (n=800)
    - only use best model from stage 2 (`DeepSeek-R1`)
    - let model detect errors from unverified report → assess by 2 senior radiologists using finalized version as ground truth (false-positive rate)
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:

## Results

### DeepSeek-R1 perform the best in zero-shot error detection (Stage 1) among all LLMs
![Table 3: Performance of different LLMs in error detection in a 0-shot setting](attachment:87f40b16-8078-4f32-ae9b-09aa1f8a84bb:Screenshot_2026-05-16_at_09.14.59.png)

### Both DeepSeek-R1 and Grok3 perform better error detection rate in few-shot than zero-shot setting (Stage 2 & 3)
    table 4 (below)

### DeepSeek-R1 perform equivalent to radiologists in both zero-shot and few-shot setting (Stage 2 & 3)
![Table 4: Comparison of error detection between LLMs and the radiologists in 0-shot and few-shot setting](attachment:3ac5046d-afee-47fe-a45e-e49e210c0578:Screenshot_2026-05-16_at_09.21.32.png)

### DeepSeek-R1 shows no different overall error detection rate (by error type) comparing to radiologists
    - In the zero-shot setting, `DeepSeek-R1` showed superior performance over 2 residents in detecting side confusion
    - In the zero-shot setting, `DeepSeek-R1` detected other types of errors more frequently than resident 1
    - In the few-shot setting, `DeepSeek-R1` outperformed resident 3 in detecting both omission errors and resident 4
![Table 5: Comparison of detection rates for different error types in radiology reports in 0-shot and few-shot settings](attachment:8a832cde-00e4-4980-b868-a4e9f1407f9c:Screenshot_2026-05-16_at_09.27.00.png)

### No significant different of error detection (by image modalities) between DeepSeek-R1 and radiologists
    - In the 0-shot learning scenario, no significant difference was observed in error detection between `DeepSeek-R1` and the radiologists for either radiography reports
    - In the few-shot learning scenario, `DeepSeek-R1` detected significantly more errors than the lowest-performing resident radiologist
![Table 6: Subgroup analyses of imaging modalities](attachment:c644a490-1acd-45e5-bc39-d940c2e241a1:Screenshot_2026-05-16_at_09.35.03.png)

### Evaluation on real-world dataset
    - `DeepSeek-R1` classified 207 reports as having errors, among which 117 were true errors, yielding a PPV of 0.565
    - omission was the most common error (n=56), whereas incorrect laterality was the least common (n=6)
    → no further evaluation yet since no automated error classification on real-world reports

### DeepSeek-R1 showed fair to moderate consistency with radiologists
![Fig 3: Inter-rater agreement analysis](attachment:c6ea3a10-801f-48ed-b3f6-e68fa9a550f2:Screenshot_2026-05-16_at_09.42.12.png)

### LLMs demonstrated significant time efficiency advantages
    - `DeepSeekR1` required 2.56 hours in the 0-shot setting and 2.26 hours in
the few-shot setting
    - `Grok3` processed 100 reports in 0.34 and 0.26 hours under 0-shot and
few-shot settings
    - radiologists’ reading times ranged from 3.04 to 5.36 hours
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:

## Limitations
    - synthetic design cannot fully capture the diversity and contextual complexity of errors
    - exploratory analyses in stages 2‐3 were conducted in a simulated environment that differed from routine clinical practice
    - error taxonomy and definitions of false-positive subtypes involve some subjectivity
    - did not include a formal cost-effectiveness analysis
    - radiologists’ awareness of observation temporarily enhanced performance (Hawthorne effect, not totally blinded)
  ── 行「**Error detection in emergency radiology reports using a large language model: multistage evaluation study**」内嵌页面:
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='title' raw=[['Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study', [['b']]]]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='?gDz' raw=[['Yamashiki']]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='JKqf' raw=[['Done']]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key=']~U]' raw=[['2026']]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='kTw|' raw=[['  • LLM judge has bias\n  • traditional metric for token-type ratio (TTR)']]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='oVG}' raw=[['https://arxiv.org/abs/2604.02207', [['a', 'https://arxiv.org/abs/2604.02207']]]]
  [44b07ab9-ace7-82ae-bbf3-01a4b23e04bb]: row prop key='yO:}' raw=[['arXiv']]
| **Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study** | Yamashiki | Done | 2026 |   • LLM judge has bias   • traditional metric for token-type ratio (TTR) | [https://arxiv.org/abs/2604.02207](https://arxiv.org/abs/2604.02207) | arXiv |
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:

## Annotated Bibliography
    This study evaluates the quality of LLM-generated translations of Japanese radiology reports and compares assessments from human experts against those from LLM judges.
    The researchers had two radiologists and three different LLMs assess the quality of 50 chest CT reports translated by either a human-edited process or an LLM.
    The main finding was a significant discrepancy in evaluations: the human radiologists had opposing preferences, whereas all LLM judges consistently favored the LLM-generated translations. This suggests a potential self-preference bias in LLM evaluators, leading the authors to conclude that expert human review remains a critical quality gate for high-stakes clinical content.
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:

## Problems & Purpose
    - Evaluate the quality of LLM-translated Japanese medical reports
    - Compare assessment of translated report between expert rating and LLM judges
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:

## Methods

### Data
    CT-RATE-JPN: Chest CT radiology → total 50 image-text pairs
    - Human-edited translation: `GPT-4o mini` translate → radiology resident edit
    - LLM-generated translation: `DeepSeek-V3.2` translate
(temperature 0, standardizing prompt)

### LLM Translation
    Benchmarking LLM:
    - `DeepSeek-V3.2`
    - `Mistral Large 3`
    - `GPT-5`
![System prompt for LLM translation](attachment:ab38b961-8a06-4816-901d-591d40447b1d:Screenshot_2026-05-14_at_10.44.40.png)

### Assessments

### Linguistic Analysis (~ traditional metrics)
    → measure of lexical diversity, using both all parts of speech and content words only (nouns, verbs, adjectives, and adverbs).
    `Janome tokenizer` → computed type-token ratio (TTR)

### Compare Assessment
    → assessment with LLM or clinicians
    Comparative evaluation → choose which report is better or both equivalent
(A / B / TIE) for each topic
    - Terminology accuracy（术语准确性）
    - Readability and Fluency（可读性与流畅性）
    - Overall clinical suitability（总体临床适用性）
    - Radiologist-style authenticity（放射科风格）
![System prompt for LLM judge assessment](attachment:dfd834f0-fbd5-4953-add5-dd3192eeea0a:Screenshot_2026-05-14_at_10.42.54.png)
![Context prompt for LLM judge assessment](attachment:0b32e630-d5bc-4297-80f7-f657a0d1fed6:Screenshot_2026-05-14_at_10.41.58.png)
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:

## Results

### DeepSeek translations generate shorter report with multiple short individual sentences
    - Human-edited translations were significantly longer than DeepSeek-generated
translations in total character count (median 517.5 vs. 481.5 characters; Wilcoxon
signed-rank test, W = 729.5, p < .001)
    - DeepSeek translations contained significantly more sentences per report (mean 20.3 vs. 19.6; p < .001), while individual sentences were significantly shorter (mean sentence length 24.7 vs. 27.3 characters; p < .001)

### DeepSeek translations showed greater lexical
variety relative to total token count, but no significant difference in content words ratio
    - higher total TTR (mean 0.402 vs. 0.381; p < .001)
    - same context-only TTR (mean 0.550 vs. 0.549; p = .665)

### LLM-generated Japanese translations have diverse assessment results depending on the evaluator
![Fig 1: radiologists pairwise evaluation results
→ one preferred human-edited, another one preferred LLM-generated ](attachment:70f324d5-4d66-4656-ac08-c262337a1a55:image.png)
![Fig 3: LLM judge pairwise evaluation results
→ all LLMs preferred LLM-generated](attachment:2769448c-81e7-41a2-90d5-dbbc99a2d17f:image.png)
    **Discussion:**
    - LLM judges may not have been detecting clinically meaningful superiority alone, but may also have reflected model-specific stylistic preferences or alignment with particular lexical and syntactic patterns, consistent with prior reports of self-preference bias in LLM-as-a-judge settings → susceptible to multiple forms of bias
    - Japanese radiology reports follow highly conventionalized patterns in wording, uncertainty marking, anatomic description, and overall sentence style

### Recommendation: LLM-as-a-judge should not serve as the sole quality gate for either educational content or AI training data
    For higher-stakes applications, including model reports, teaching files, standardized assessment materials, or training data for clinical AI systems in which faithful representation of uncertainty is critical, expert radiologist review remains an important quality gate
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:

## Limitations
    - Only chest CT radiology
    - Only Japanese translation
    - Only two human raters
    - Only single prompt framework
    - No downstream tasks/results assessment
  ── 行「**Blinded Radiologist and LLM-Based Evaluation of LLM-Generated Japanese Translations of Chest CT Reports; Comparative Study**」内嵌页面:
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='title' raw=[['The effect of medical explanations from large language models on diagnostic accuracy in radiology']]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='?gDz' raw=[['Spitzer']]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='JKqf' raw=[['Done']]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key=']~U]' raw=[['2026']]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='kTw|' raw=[['  • maybe supportive tool evaluation of our agent?']]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='oVG}' raw=[['https://www.nature.com/articles/s41746-026-02619-0', [['a', 'https://www.nature.com/articles/s41746-026-02619-0']]]]
  [48807ab9-ace7-828f-8552-016357199807]: row prop key='yO:}' raw=[['npj Digit. Med.']]
| The effect of medical explanations from large language models on diagnostic accuracy in radiology | Spitzer | Done | 2026 |   • maybe supportive tool evaluation of our agent? | [https://www.nature.com/articles/s41746-026-02619-0](https://www.nature.com/articles/s41746-026-02619-0) | npj Digit. Med. |
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面:

## Annotated Bibliography
    This study addresses a critical gap in understanding how different formats of LLM-generated explanations influence physician diagnostic decision-making, moving beyond prior work that primarily assessed LLM diagnostic accuracy in isolation.
    Through a large-scale randomized experiment with 101 radiologists and 2,020 patient assessments, the authors demonstrate that chain-of-thought explanations significantly outperform both standard outputs and differential diagnoses in improving diagnostic accuracy, highlighting the importance of explanation design in clinical AI deployment.
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面:

## Problems & Purpose
    - Most of the studies primarily assess the correctness of LLM-generated diagnoses.
    - Impact of different explanation formats of LLM on medical decision-making is unclear.
    - Automation bias (LLM explanation, hallucination) might mislead physicians.
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面:

## Methods
![Fig 1. Research overall design.](attachment:d12d2c7c-7308-4237-b345-2d4b77332324:Screenshot_2026-05-21_at_09.28.33.png)

### Data
    20 real-world patient cases (`New England Journal of Medicine Image Challenge`)
    - brief clinical description
    - at least one radiology image (CT or MRI)
    - selected
      - 80% knowledge found in a standard textbook
      - 20% require more specialized knowledge

### Physicians
    101 radiologists, mean 13.6 years medical experience (SD=8.0).
    Fig 5(a)

### RCT
    - **Control**: without LLM explanation
    - **Standard output**: `GPT-4` offers a single diagnosis without explanation
    - **Differential analysis**: `GTP-4` offers 5 differential diagnoses (both top-1 and top5) with a short justification
    - **Chain-of-thought**: `GTP-4` offers reasoning explanation and a single diagnosis
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面:

## Results

### The LLM achieved moderate diagnostic accuracy
overall, where CoT performed the best
    - standard output: 75%
    - differential diagnosis (top-1): 65%
    - differential diagnosis (top-5): 80%
    - chain-of-thought: 80%

### Diagnostic accuracy of physicians augmented with LLM advice outperformed those in the control group without LLM advice
![Fig 2. Diagnostic accuracy across different LLM explanations.
  • CoT significant better than control and other formats](attachment:2d94048e-7bf4-4ed2-b649-46ad449b96ac:Screenshot_2026-05-21_at_13.42.01.png)
    Even after controlling for various physician-specific control variables
such as years of medical experience, radiology-specific expertise, hours per
week spent on visual inspections, IT skills, and experience with medical AI,
the effects remain robust (see Supplementary Table 9 for the regression
results).

### Human-computer interaction (Adherence)
![Fig 3. Adherence vs. overriding LLM advice](attachment:753b14e3-62e7-4fb1-9275-3a227b32ba30:Screenshot_2026-05-21_at_13.47.50.png)
    Adherence was highest in the differential diagnosis group irrespective of the correctness of the explanation → accepted incorrect LLM diagnoses at high rates
(right side of the Fig 3)
    - adherence for incorrect diagnosis but correct explanation: 63.3%
    - adherence for incorrect diagnosis and incorrect explanation: 80.0%
    adherence was highest in the chain-of-thought explanations in correct diagnosis
    - adherence for correct explanation: 90.8%
    - adherence for incorrect explanation: 94.0%

### CoT group tends to achieve a higher diagnostic accuracy across all heterogeneity of physicians
![Fig 4. Heterogeneity across physicians and patient cases.](attachment:9b248497-5541-4951-94b6-a2f8ff6f3e7b:Screenshot_2026-05-21_at_13.59.58.png)

### CoT improve diagnostic accuracy for both general radiologists and specialists
![Fig 5. Diagnostic accuracy across different radiological backgrounds (general radiologists vs. radiologists with sub-specializations)](attachment:476bd76e-b058-43ff-bb0c-520c27a7d9a2:Screenshot_2026-05-21_at_14.14.16.png)
    Diagnosis Accuracy
    - general radiologists in the chain-of-thought group tends to be higher than in the standard output group but the improvement is only marginally significant
    - specialists in the chain-of-thought condition performed significantly better
than in the control condition
    The key mechanism behind the performance gain from chain-of-thought explanations appears to be the physicians’ improved ability to assess the correctness of LLM output based on the provided reasoning
    Chain-of-thought reasoning focuses on a single diagnostic pathway, leaving physicians free to consider alternatives when they detect inconsistencies.
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面:

## Limitations
    - focused on only one medical specialty
    - focused on a single time point;
    - did not assess the potential harm that can arise from incorrect decisions or other patient outcomes
    - based on a single LLM (GPT-4)
  ── 行「The effect of medical explanations from large language models on diagnostic accuracy in radiology」内嵌页面: