# 模块（Modules）实现计划

> **给 Agent 执行者：** 必选子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行本计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 实现 Module 1（单报告评估）和 Module 2（成对报告评估）。两者将工具编排为统一的评估流水线。

**架构：** 默认顺序执行，可通过参数调整。每个模块导入工具函数并按序调用。输出为按工具名称嵌套的统一 JSON。可选缓存路径用于保存结果。

**技术栈：** Python 3.10+，标准库。

**依赖：** Foundation + 所有 Tools 必须已存在。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/modules/module1.py` | 单报告评估编排器（Single Report Evaluation） |
| `src/modules/module2.py` | 成对报告评估编排器（Pairwise Report Evaluation） |
| `tests/modules/test_module1.py` | Module 1 测试 |
| `tests/modules/test_module2.py` | Module 2 测试 |

---

### 任务 1：Module 1 — 单报告评估

**文件：**
- 新建：`src/modules/module1.py`
- 新建：`tests/modules/test_module1.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/modules/test_module1.py`
```python
import pytest
from src.modules.module1 import evaluate_single_report


class TestEvaluateSingleReport:
    def test_orchestrates_tools(self, mocker):
        mock_tool1 = mocker.patch("src.modules.module1.evaluate_likert")
        mock_tool1.return_value = {"metric": {"score": 4, "explanation": "good"}}

        mock_tool2 = mocker.patch("src.modules.module1.extract_findings")
        mock_tool2.return_value = {"findings": ["nodule"]}

        mock_tool3 = mocker.patch("src.modules.module1.check_structure")
        mock_tool3.return_value = {"classified": {"Findings": ["P1"]}, "score": 0.4}

        result = evaluate_single_report("Report text.", modality="chest_xray")
        assert "tool1" in result
        assert "tool2" in result
        assert "tool3" in result
        assert result["tool1"]["metric"]["score"] == 4

    def test_with_image_no_modality(self, mocker):
        mock_tool7 = mocker.patch("src.modules.module1.recognize_modality")
        mock_tool7.return_value = "chest_ct"

        mock_tool1 = mocker.patch("src.modules.module1.evaluate_likert")
        mock_tool1.return_value = {}

        mock_tool2 = mocker.patch("src.modules.module1.extract_findings")
        mock_tool2.return_value = {}

        mock_tool3 = mocker.patch("src.modules.module1.check_structure")
        mock_tool3.return_value = {}

        result = evaluate_single_report("Report.", image_path="/tmp/img.png")
        mock_tool7.assert_called_once()
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/modules/test_module1.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小可用实现**

**实现：** `src/modules/module1.py`
```python
"""Module 1: Single Report Evaluation.

编排 Tool 1、2、3 以评估单份放射学报告。
"""

import json
import logging
from typing import Optional

from src.llm_client import LLMClient
from src.tools.tool1 import evaluate_likert
from src.tools.tool2 import extract_findings
from src.tools.tool3 import check_structure
from src.tools.tool7 import recognize_modality
from src.utils.file_io import write_json

logger = logging.getLogger(__name__)


def evaluate_single_report(
    report_text: str,
    image_path: Optional[str] = None,
    modality: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
    cache_path: Optional[str] = None,
    parallel: bool = False,
) -> dict:
    """评估单份放射学报告。

    Args:
        report_text: 放射学报告文本。
        image_path: 可选，关联影像/体积数据的路径。
        modality: 可选，检查模态（Modality）。若为 None 且提供了影像，则通过 Tool 7 自动检测。
        llm_client: LLM/VLM 客户端实例。
        config_dir: 配置文件与提示词所在目录。
        cache_path: 可选，保存结果 JSON 的路径。
        parallel: 若为 True，则并行运行独立工具（暂未实现，当前仍为顺序执行）。

    Returns:
        按工具名称嵌套的统一 JSON：
        {"tool1": {...}, "tool2": {...}, "tool3": {...}}
    """
    logger.debug("Module 1: Starting single report evaluation")

    # 如需检测模态
    if modality is None and image_path is not None:
        logger.debug("Module 1: Detecting modality")
        modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)
        logger.debug(f"Module 1: Detected modality = {modality}")

    # 运行各工具
    logger.debug("Module 1: Running Tool 1 (Likert)")
    tool1_result = evaluate_likert(
        report_text,
        image_path=image_path,
        llm_client=llm_client,
        config_dir=config_dir,
    )

    logger.debug("Module 1: Running Tool 2 (Findings Extraction)")
    tool2_result = extract_findings(
        report_text,
        modality=modality or "unknown",
        config_dir=config_dir,
    )

    logger.debug("Module 1: Running Tool 3 (Structure Check)")
    tool3_result = check_structure(
        report_text,
        llm_client=llm_client,
        config_dir=config_dir,
    )

    result = {
        "tool1": tool1_result,
        "tool2": tool2_result,
        "tool3": tool3_result,
    }

    if cache_path:
        write_json(cache_path, result)
        logger.debug(f"Module 1: Cached results to {cache_path}")

    logger.debug("Module 1: Single report evaluation complete")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/modules/test_module1.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/modules/module1.py tests/modules/test_module1.py
git commit -m "feat: add Module 1 Single Report Evaluation"
```

---

### 任务 2：Module 2 — 成对报告评估

**文件：**
- 新建：`src/modules/module2.py`
- 新建：`tests/modules/test_module2.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/modules/test_module2.py`
```python
import pytest
from src.modules.module2 import evaluate_pairwise


class TestEvaluatePairwise:
    def test_orchestrates_tools(self, mocker):
        mock_tool2 = mocker.patch("src.modules.module2.extract_findings")
        mock_tool2.side_effect = [
            {"findings": ["nodule A"]},
            {"findings": ["nodule B"]},
        ]

        mock_tool4 = mocker.patch("src.modules.module2.evaluate_error_hazard")
        mock_tool4.return_value = [{"error_type": "false_finding"}]

        mock_tool5 = mocker.patch("src.modules.module2.align_graphs")
        mock_tool5.return_value = {"categories": {}, "metrics": {}, "rexval_errors": {}}

        mock_tool6 = mocker.patch("src.modules.module2.compare_structure")
        mock_tool6.return_value = {"Findings": {"score_a": 0.4, "score_b": 0.8, "difference": 0.4}}

        result = evaluate_pairwise("Report A", "Report B", modality="chest_xray")
        assert "tool2_a" in result
        assert "tool2_b" in result
        assert "tool4" in result
        assert "tool5" in result
        assert "tool6" in result

    def test_with_modality_detection(self, mocker):
        mock_tool7 = mocker.patch("src.modules.module2.recognize_modality")
        mock_tool7.return_value = "brain_mri"

        mock_tool2 = mocker.patch("src.modules.module2.extract_findings")
        mock_tool2.side_effect = [{}, {}]

        mock_tool4 = mocker.patch("src.modules.module2.evaluate_error_hazard")
        mock_tool4.return_value = []

        mock_tool5 = mocker.patch("src.modules.module2.align_graphs")
        mock_tool5.return_value = {"categories": {}, "metrics": {}, "rexval_errors": {}}

        mock_tool6 = mocker.patch("src.modules.module2.compare_structure")
        mock_tool6.return_value = {}

        result = evaluate_pairwise("A", "B", image_path="/tmp/img.png")
        mock_tool7.assert_called_once()
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/modules/test_module2.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小可用实现**

**实现：** `src/modules/module2.py`
```python
"""Module 2: Pairwise Report Evaluation.

编排 Tool 2、4、5、6 以对比两份放射学报告。
"""

import logging
from typing import Optional

from src.llm_client import LLMClient
from src.tools.tool2 import extract_findings
from src.tools.tool4 import evaluate_error_hazard
from src.tools.tool5 import align_graphs
from src.tools.tool6 import compare_structure
from src.tools.tool7 import recognize_modality
from src.utils.file_io import write_json

logger = logging.getLogger(__name__)


def evaluate_pairwise(
    report_a: str,
    report_b: str,
    image_path: Optional[str] = None,
    modality: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
    cache_path: Optional[str] = None,
) -> dict:
    """对两份报告进行成对评估。

    Args:
        report_a: 报告 A 的文本。
        report_b: 报告 B 的文本。
        image_path: 可选，关联影像/体积数据的路径。
        modality: 可选，检查模态（Modality）。若为 None 且提供了影像，则通过 Tool 7 自动检测。
        llm_client: LLM/VLM 客户端实例。
        config_dir: 配置文件与提示词所在目录。
        cache_path: 可选，保存结果 JSON 的路径。

    Returns:
        按工具名称嵌套的统一 JSON：
        {"tool2_a": {...}, "tool2_b": {...}, "tool4": {...}, "tool5": {...}, "tool6": {...}}
    """
    logger.debug("Module 2: Starting pairwise report evaluation")

    # 如需检测模态
    if modality is None and image_path is not None:
        logger.debug("Module 2: Detecting modality")
        modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)
        logger.debug(f"Module 2: Detected modality = {modality}")

    mod = modality or "unknown"

    # 对两份报告分别运行 Tool 2
    logger.debug("Module 2: Running Tool 2 on report A")
    graph_a = extract_findings(report_a, modality=mod, config_dir=config_dir)

    logger.debug("Module 2: Running Tool 2 on report B")
    graph_b = extract_findings(report_b, modality=mod, config_dir=config_dir)

    # Tool 4：错误危害评估（Error Hazard）
    logger.debug("Module 2: Running Tool 4 (Error Hazard)")
    tool4_result = evaluate_error_hazard(
        graph_a,
        graph_b,
        llm_client=llm_client,
        config_dir=config_dir,
    )

    # Tool 5：图对齐（Graph Alignment）
    logger.debug("Module 2: Running Tool 5 (Graph Alignment)")
    tool5_result = align_graphs(graph_a, graph_b, config_dir=config_dir)

    # Tool 6：结构差异（Structure Difference）
    logger.debug("Module 2: Running Tool 6 (Structure Difference)")
    tool6_result = compare_structure(
        report_a,
        report_b,
        llm_client=llm_client,
        config_dir=config_dir,
    )

    result = {
        "tool2_a": graph_a,
        "tool2_b": graph_b,
        "tool4": tool4_result,
        "tool5": tool5_result,
        "tool6": tool6_result,
    }

    if cache_path:
        write_json(cache_path, result)
        logger.debug(f"Module 2: Cached results to {cache_path}")

    logger.debug("Module 2: Pairwise evaluation complete")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/modules/test_module2.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/modules/module2.py tests/modules/test_module2.py
git commit -m "feat: add Module 2 Pairwise Report Evaluation"
```

---

### 任务 3：验证所有模块

- [ ] **步骤 1：运行全部模块测试**

运行：`python -m pytest tests/modules/ -v`
预期结果：全部 PASS

- [ ] **步骤 2：提交**

```bash
git commit --allow-empty -m "checkpoint: modules complete"
```

---

## 自查（Self-Review）

**1. 规格覆盖：**
- Module 1：编排 Tool 1、2、3。可选模态检测。统一 JSON 输出。可选缓存。顺序/并行参数 — 任务 1
- Module 2：编排 Tool 2（×2）、4、5、6。可选模态检测。统一 JSON 输出。可选缓存。顺序执行 — 任务 2

**2. 占位符扫描：** 无占位符。

**3. 类型一致性：** 两个模块均接受 `llm_client: Optional[LLMClient]`，均接受 `cache_path: Optional[str]`。

**缺口（Gaps）：** 无。
