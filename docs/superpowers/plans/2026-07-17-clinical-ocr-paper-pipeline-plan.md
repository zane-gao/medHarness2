# 临床标注、正式 OCR 与论文实验流水线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成可供真实医生使用的 10 例盲化标注包，并建立 OCR/论文实验的可复现 manifest 与门禁。

**Architecture:** 新增一个确定性 case selector 和两个 manifest builder；所有输入从现有 52 例产物读取，输出只包含 hash、路径、模态和状态，不生成临床标签。复用现有 annotation schema、OCR benchmark CLI 和实验协议。

**Tech Stack:** Python 3.11、PyYAML/JSONL、Pydantic 现有合约、pytest、现有 CLI。

---

### Task 1: 10 例标注包选择器

**Files:**
- Create: `src/medharness2/clinical_prep.py`
- Create: `tests/test_clinical_prep.py`
- Modify: `src/medharness2/cli.py`

- [ ] 读取 52 例 manifest，严格校验病例对象、模态、源路径和 hash。
- [ ] 按 `cxr/ct/mri` 覆盖及 OCR 风险排序，确定性选出 10 例。
- [ ] 输出盲化 manifest、候选模型映射隔离文件、10 个 annotation case JSON。
- [ ] 增加 CLI：`annotation prepare-pilot --run-dir ... --output-dir ... --count 10`。

### Task 2: OCR 与论文 manifest

**Files:**
- Create: `src/medharness2/research_prep.py`
- Create: `tests/test_research_prep.py`
- Modify: `src/medharness2/cli.py`

- [ ] 输出 OCR candidate/repeat manifest，真实 provider 缺失时状态为 `blocked`。
- [ ] 输出论文 experiment manifest，固定四组实验和统计方法。
- [ ] 增加 manifest schema 校验和 CLI：`research prepare-manifests`。

### Task 3: 文档、前端和验证

**Files:**
- Modify: `docs/project_status.yaml`
- Modify: `docs/blindspot_audit_20260714.md`
- Modify: `web/index.html`

- [ ] 记录 10 例准备状态、OCR winner 状态和论文实验状态。
- [ ] 运行专项/全量测试、compileall、diff check。
- [ ] 重建前端，确认 SHA 与 dirty 状态。
- [ ] 提交并推送 `main`，核对远程 SHA。
