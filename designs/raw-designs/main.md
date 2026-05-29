# 多 AI 模型放射科报告评估（Radiology Report Evaluation with Multiple AI Models）
本文概述目标与关键流程。

# 目标
## 主目标
- 评估输入的自由文本放射科报告（free text radiology report）
- 输出定量评估（quantitative evaluation）和定性评估（qualitative assessment）

## 子目标
- 使用固定的传统工具作为基线评估
- 使用 AI 模型生成的放射科报告作为主要评估和对比参考


# 通用规则
- 通过 CLI API 使用
- AI 模型包括本地推理（local inference）和云 API 调用（cloud API call）
- 若存在多个配置文件，所有配置放在同一目录；除非模块明确要求，不做硬编码
- 流程相同时尽量复用函数
- 关键步骤添加 `logging.debug`，便于调试
- 默认云端 LLM 应可通过配置调整
- 模块间共享的 API KEY 或通用配置应集中存放


# 模块与工作流工具
阅读 `tools.md`


# 主模块
## 模块 1：单报告评估（Single Report Evaluation）
描述：在没有参考报告的情况下评估自由文本报告。

输入：
- 输入自由文本报告（单文件，用于评估）
- 输入医学图像/体数据（单文件，与输入报告对应）

流程：
```mermaid
flowchart TD
    A[报告 + 图像/体数据] --> B["**工具：** Likert 量表 LLM 评估（Likert-Scale LLM Evaluation）"]
    A --> C["**工具：** 实体-关系病灶提取（Entity-Relation Finding Extraction）"]
    A --> D["**工具：** 层级结构检查（Hierarchical Structure Check）"]

    B --> B1["**输出**：Likert JSON"]
    C --> C1["**输出**：病灶图谱 + 缺失项"]
    D --> D1["**输出**：结构评分 JSON"]

    B1 --> E["汇总各单项评分"]
    C1 --> E
    D1 --> E

    style B fill:#e1bee7,stroke:#7b1fa2,color:#000
    style C fill:#e1bee7,stroke:#7b1fa2,color:#000
    style D fill:#e1bee7,stroke:#7b1fa2,color:#000
    style B1 fill:#c8e6c9,stroke:#388e3c,color:#000
    style C1 fill:#c8e6c9,stroke:#388e3c,color:#000
    style D1 fill:#c8e6c9,stroke:#388e3c,color:#000
```


## 模块 2：成对报告评估（Pairwise Report Evaluation）
描述：将自由文本报告与参考报告对比评估。

输入：
- 输入自由文本报告（单文件，用于评估）
- 输入医学图像/体数据（单文件，与输入报告对应）
- 参考自由文本报告（单文件，用作参考）

流程：
```mermaid
flowchart TD
    A[报告 A + 报告 B] --> Z["**工具：** 从两份报告提取图谱"]
    Z --> Z1["**输出**：图谱 A（Graph A）"]
    Z --> Z2["**输出**：图谱 B（Graph B）"]

    Z1 --> B["**工具：** 错误危害评估（Error Hazard Evaluation）"]
    Z2 --> B
    B --> B1["Likert 量表 LLM 评估"]
    B1 --> B2["**输出**：危险错误数量及其级别"]

    Z1 --> C["**工具：** 跨报告图谱对齐（Cross-Report Graph Alignment）"]
    Z2 --> C
    C --> C1["匹配 / 仅 A 有 / 仅 B 有 / 不匹配"]
    C1 --> C2["**输出**：每个病灶的 Accuracy + F1"]

    A --> D["**工具：** 结构差异（Structure Difference）"]
    D --> D1["**输出**：章节/子主题差异"]

    B2 --> E["汇总对比结果"]
    C2 --> E
    D1 --> E

    style Z fill:#e1bee7,stroke:#7b1fa2,color:#000
    style B fill:#e1bee7,stroke:#7b1fa2,color:#000
    style C fill:#e1bee7,stroke:#7b1fa2,color:#000
    style D fill:#e1bee7,stroke:#7b1fa2,color:#000
    style Z1 fill:#c8e6c9,stroke:#388e3c,color:#000
    style Z2 fill:#c8e6c9,stroke:#388e3c,color:#000
    style B2 fill:#c8e6c9,stroke:#388e3c,color:#000
    style C2 fill:#c8e6c9,stroke:#388e3c,color:#000
    style D1 fill:#c8e6c9,stroke:#388e3c,color:#000
```


# 集成工作流
## 工作流 1：
描述：评估一份随机人工撰写的自由文本报告。

输入：
- 输入自由文本报告（单文件，用于评估）
- 输入医学图像/体数据（单文件，与输入报告对应）

流程：
```mermaid
flowchart TD
    A[输入：图像/体数据 + 人工报告] --> B[**工具：** 模态识别（Modality Recognition）]
    B --> C{模态与维度}
    C -->|2D| D[**工具：** 2D 报告生成]
    C -->|3D| E[**工具：** 3D 报告生成]
    D --> F[生成报告池]
    E --> F
    F --> G[**工作流 1**：单报告评估]
    G --> H[综合评分排序]
    H --> I[**工具：** 选择 Top N 报告]
    I --> J[**工作流 2**：成对报告评估]
    A --> J
    J --> K[人工报告 vs Top N]
    K --> L[最终输出]

    %% Define custom styles
    style B fill:#e8eaf6,stroke:#3f51b5,color:#000
    style D fill:#e8eaf6,stroke:#3f51b5,color:#000
    style E fill:#e8eaf6,stroke:#3f51b5,color:#000
    style G fill:#e0f7fa,stroke:#0097a7,color:#000
    style H fill:#e8eaf6,stroke:#3f51b5,color:#000
    style J fill:#e0f7fa,stroke:#0097a7,color:#000
```


## 工作流 2：
描述：评估多名放射科医生的批量自由文本报告，并将每名医生的整体表现与所有 AI 模型及本科室整体水平进行比较（同一批次内）。

输入：
- 带唯一放射科医生 ID 的批量自由文本报告（Excel 文件，包含报告路径、对应图像/体数据路径、对应放射科医生唯一 ID；共 3 列，按名称匹配）

流程：
```mermaid
flowchart TD
    A[**医生-1**</br>报告 1, ... ,报告 n] --**工具：** 2D/3D 生成模型--> B[**k 个模型**</br>报告 1, ... ,报告 n]
    B --> C[**医生-1 : 模型-1**</br>报告 1</br>...</br>报告 n]
    A --> C
    B --> D[**医生-1 : 模型-2**</br>报告 1</br>...</br>报告 n]
    A --> D
    B --> E[**医生-1 : 模型-...**</br>报告 1</br>...</br>报告 n]
    A --> E
    B --> F[**医生-1 : 模型-k**</br>报告 1</br>...</br>报告 n]
    A --> F

    C --> G[**工作流 1 + 2**</br>单报告 + 成对</br>报告评估]
    D --> G
    E --> G
    F --> G
    G --> H[**医生-1 : 模型-1**</br>报告 1：i 个指标</br>...</br>报告 n：i 个指标]
    G --> I[**医生-1 : 模型-2**</br>报告 1：i 个指标</br>...</br>报告 n：i 个指标]
    G --> J[**医生-1 : 模型-...**</br>报告 1：i 个指标</br>...</br>报告 n：i 个指标]
    G --> K[**医生-1 : 模型-k**</br>报告 1：i 个指标</br>...</br>报告 n：i 个指标]

    H --> L[**工具：** 按模型加权（Modelwise Weighted）</br>i 个指标]
    I --> L
    J --> L
    K --> L
    L --> M[**医生-1**</br>**报告 1**：i 个加权指标</br>...</br>**报告 n**：i 个加权指标]
    M --> N[**工具：** 按危害加权（Hazardwise Weighted）</br>n 份报告]
    N --> O[**医生-1**</br>i 个加权得分</br>**按指标**]
    O --> P

    Q[**医生-2**</br>报告 1, ... ,报告 n] --同一评估流程--> R[**医生-2**</br>**报告 1**：i 个加权指标</br>...</br>**报告 n**：i 个加权指标]
    S[**医生-n**</br>报告 1, ... ,报告 n] --同一评估流程--> T[**医生-n**</br>**报告 1**：i 个加权指标</br>...</br>**报告 n**：i 个加权指标]
    R --> N
    T --> N
    N --> U[**医生-2**</br>i 个加权得分</br>**按指标**]
    N --> V[**医生-n**</br>i 个加权得分</br>**按指标**]
    O --> W[**工具：** 统计计算（Statistic Calculation）]
    U --> W
    V --> W
    W --> X
 
  
	subgraph 评估结果
		P[**医生-1** 在 i 个指标上的表现</br>例如 accuracy、error hazard level、error rate]
		X[**医生-1**</br>相对 n 名医生的</br>**百分位（percentile）** 和 **统计量（statistic）**]
	end
	
	
	%% Define custom styles
	classDef darkBlue fill:#1a237e,color:#fff,stroke:#0d1335,stroke-width:2px;
	classDef darkRed fill:#b71c1c,color:#fff,stroke:#7f0000,stroke-width:2px;
	classDef lightGray fill:#e0e0e0,color:#222,stroke:#bdbdbd,stroke-width:2px;
	class A,B,Q,S darkBlue;
	class G,L,N,W lightGray;
	class P,X darkRed;
	
	linkStyle 0,1,3,5,7 stroke:#fbc02d,stroke-width:1px;
	linkStyle 2,4,6,8 stroke:#4caf50,stroke-width:1px;
	
	linkStyle 9,10,11,12 stroke:#fbc02d,stroke-width:1px;
	linkStyle 13,14,15,16 stroke:#fbc02d,stroke-width:1px;
	linkStyle 17,18,19,20 stroke:#fbc02d,stroke-width:1px;
	linkStyle 21,22,23 stroke:#fbc02d,stroke-width:1px;
	
	linkStyle 24 stroke:#ff9800,stroke-width:3px;
	
	linkStyle 25,26,27,28 stroke:#fbc02d,stroke-width:1px;
	linkStyle 29,30 stroke:#fbc02d,stroke-width:1px;
	
	linkStyle 31,32,33,34 stroke:#9c27b0,stroke-width:3px;
```


## 工作流 3：
描述：评估同一科室/医院多名放射科医生的批量自由文本报告，并与整体 AI 模型组表现比较（将所有现有 AI 模型视为另一科室/医院的一组放射科医生）。

输入：
- 带唯一放射科医生 ID 的批量自由文本报告（Excel 文件，包含报告路径、对应图像/体数据路径、对应放射科医生唯一 ID；共 3 列，按名称匹配）

流程：
```mermaid
flowchart TD
    A[**医生组**</br>病例 1, ... ,病例 n</br>每病例一份报告] --m 个生成模型--> B[**模型组**</br>病例 1, ... ,病例 n</br>每病例 m 份报告]
	A --> C
	B --> C[**工作流 1**</br>单报告</br>评估]
	C --> D[**模型组**</br>病例 1：m x i 个指标</br>...</br>病例 n：m x i 个指标]
	%% D --Model Selection-->E[**Top-k** Models</br>case 1 : k x i metrics</br>...</br>case n : k x i metrics] 
	D --> G[**模型代表值（Model Representative）**</br>病例 1：平均 i 个指标</br>...</br>病例 n：平均 i 个指标]
	C --> F[**医生组**</br>病例 1：i 个指标</br>...</br>病例 n：i 个指标] 
	
	F --> H[**医生** : **平均模型**</br>i 个指标</br>病例 1, ..., 病例 n]
	G --> H
	
	H --> I
	H --> K
	F --> L[**工具：** 统计计算（Statistic Calculation）]
	G --> L
	
	L --> J
	
	subgraph 评估结果
		I[每份报告</br>**得分差异**]
		J[医生 / 模型</br>**得分分布**]
		K[**优于模型**的报告数量]
	end
	
	%% Define custom styles
	classDef darkBlue fill:#1a237e,color:#fff,stroke:#0d1335,stroke-width:2px;
	classDef darkRed fill:#b71c1c,color:#fff,stroke:#7f0000,stroke-width:2px;
	classDef lightGray fill:#e0e0e0,color:#222,stroke:#bdbdbd,stroke-width:2px;
	class A,B darkBlue;
	class C,L lightGray;
	class I,J,K darkRed;
	
	linkStyle 0,2,3,4 stroke:#fbc02d,stroke-width:1px;
	linkStyle 1,5 stroke:#4caf50,stroke-width:1px;
	
	linkStyle 10,11,12 stroke:#ff9800,stroke-width:3px;
	
	linkStyle 6,7,8,9 stroke:#9c27b0,stroke-width:3px;
```

备注：工作流 1、2、3 的指标/评估结果可以互相复用。应设计一条流程先计算模块 1 和模块 2，并保存到 Excel/CSV 或其他格式文件；调用工作流时，若引用文件已存在则直接读取，否则先重新计算并创建该指标引用文件。
