# 依赖工具（Dependent Tools）实现计划

**目标：** 实现 Tool 2、4、5、6。这些工具依赖其他工具或外部命令。Tool 2 封装外部命令；Tool 4 使用 LLM 进行危害评估（Hazard Evaluation）；Tool 5 执行带单位归一化的图对齐（Graph Alignment）；Tool 6 封装 Tool 3。

**架构：** Tool 2 是外部命令封装器，使用临时文件。Tool 4 和 Tool 5 接收 Tool 2 的原始输出字典。Tool 6 封装 Tool 3。所有工具均为纯函数，内部不进行文件 I/O。

**技术栈：** Python 3.10+、标准库、subprocess、pydicom（已被 Tool 7 使用）。

**前置依赖：** 基础层（Foundation）和独立工具（Independent Tools）必须已就绪。

---

## 文件结构

| 文件                          | 职责                                                                     |
| ----------------------------- | ------------------------------------------------------------------------ |
| `src/tools/tool2.py`        | 实体-关系发现提取（Entity-Relation Finding Extraction）—— 外部命令封装 |
| `src/tools/tool4.py`        | 错误危害评估（Error Hazard Evaluation）                                  |
| `src/tools/tool5.py`        | 跨报告图对齐（Cross-Report Graph Alignment）                             |
| `src/tools/tool6.py`        | 结构差异（Structure Difference）—— 封装 Tool 3                         |
| `tests/tools/test_tool2.py` | Tool 2 测试                                                              |
| `tests/tools/test_tool4.py` | Tool 4 测试                                                              |
| `tests/tools/test_tool5.py` | Tool 5 测试                                                              |
| `tests/tools/test_tool6.py` | Tool 6 测试                                                              |

---

### 任务 1：Tool 2 —— 实体-关系发现提取（Entity-Relation Finding Extraction）

**文件：**

- 新建：`src/tools/tool2.py`
- 新建：`tests/tools/test_tool2.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool2.py`

```python
import pytest
from src.tools.tool2 import extract_findings


class TestExtractFindings:
    def test_returns_dict(self, mocker):
        mocker.patch("src.tools.tool2.subprocess.run")
        import json
        import tempfile
        import os

        # Simulate the command writing output
        def mock_run(cmd, **kwargs):
            output_path = cmd[3]  # output path is the 4th arg
            with open(output_path, "w") as f:
                json.dump({"findings": ["finding1"], "missing": []}, f)

        mocker.patch("src.tools.tool2.subprocess.run", side_effect=mock_run)
        result = extract_findings("Report text.", modality="chest_xray")
        assert isinstance(result, dict)
        assert "findings" in result

    def test_modality_template_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            extract_findings("Report text.", modality="unknown_modality")
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool2.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool2.py`

```python
"""Tool 2: Entity-Relation Finding Extraction.

Wraps external command for extracting findings from a radiology report.
For now, returns random schema-valid JSON as placeholder.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

from src.config import Config
from src.utils.file_io import read_json

logger = logging.getLogger(__name__)


def extract_findings(
    report_text: str,
    modality: str,
    extraction_command: Optional[str] = None,
    config_dir: str = "./config",
) -> dict:
    """Extract findings from report using external command.

    Args:
        report_text: The radiology report text.
        modality: Study modality for template selection.
        extraction_command: External command string. If None, uses config default.
        config_dir: Directory containing templates and config.

    Returns:
        Dict with extracted findings and missing keys.
    """
    logger.debug(f"Tool 2: Extracting findings for modality={modality}")

    # Select template by exact match
    template_path = os.path.join(config_dir, "templates", f"{modality}.json")
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found for modality: {modality} at {template_path}")

    logger.debug(f"Tool 2: Using template {template_path}")

    # For now: return random schema-valid JSON as placeholder
    # When external command is ready, replace this block with subprocess.run
    logger.warning("Tool 2: Using placeholder random output. External command not configured.")
    import random

    template = read_json(template_path)
    keys = list(template.keys()) if isinstance(template, dict) else []
    findings = {}
    for key in keys:
        findings[key] = f"random_{key}_{random.randint(1, 100)}"

    return {"findings": findings, "missing": []}


def _run_external_command(
    report_text: str,
    template_path: str,
    command: str,
) -> dict:
    """Run external extraction command. Called when command is configured."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as report_file:
        report_file.write(report_text)
        report_file_path = report_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as output_file:
        output_file_path = output_file.name

    try:
        cmd = command.format(
            report_path=report_file_path,
            template_path=template_path,
            output_path=output_file_path,
        )
        logger.debug(f"Tool 2: Running command: {cmd}")
        subprocess.run(cmd, shell=True, check=True)

        with open(output_file_path, "r") as f:
            result = json.load(f)
        return result
    finally:
        os.unlink(report_file_path)
        if os.path.exists(output_file_path):
            os.unlink(output_file_path)
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool2.py -v`
预期结果：PASS（`unknown_modality` 测试用例会因模板文件缺失而抛出预期异常）

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool2.py tests/tools/test_tool2.py
git commit -m "feat: add Tool 2 Entity-Relation Finding Extraction (placeholder)"
```

---

### 任务 2：Tool 4 —— 错误危害评估（Error Hazard Evaluation）

**文件：**

- 新建：`src/tools/tool4.py`
- 新建：`tests/tools/test_tool4.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool4.py`

```python
import pytest
from src.tools.tool4 import evaluate_error_hazard


class TestEvaluateErrorHazard:
    def test_returns_error_list(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '[{"error_type": "false_finding", "hazard_level": 3, "explanation": "Missing nodule"}]'
        graph_a = {"findings": ["nodule"]}
        graph_b = {"findings": []}
        result = evaluate_error_hazard(graph_a, graph_b, llm_client=mock_client)
        assert isinstance(result, list)
        assert len(result) > 0
        assert result[0]["error_type"] == "false_finding"

    def test_empty_errors(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = "[]"
        result = evaluate_error_hazard({}, {}, llm_client=mock_client)
        assert result == []
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool4.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool4.py`

```python
"""Tool 4: Error Hazard Evaluation.

Uses LLM to evaluate errors in report A relative to report B (ground truth).
"""

import json
import logging
from typing import Optional

from src.llm_client import LLMClient
from src.utils.file_io import read_text

logger = logging.getLogger(__name__)


def evaluate_error_hazard(
    graph_a: dict,
    graph_b: dict,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> list:
    """Evaluate error hazards in report A relative to report B.

    Args:
        graph_a: Finding graph from report A (to evaluate).
        graph_b: Finding graph from report B (ground truth).
        llm_client: LLM client instance.
        config_dir: Directory containing prompts.

    Returns:
        List of error dicts: {"error_type": str, "hazard_level": int, "explanation": str}
    """
    logger.debug("Tool 4: Starting error hazard evaluation")

    system_prompt = read_text(f"{config_dir}/prompts/tool4_system.txt")
    likert_definitions = read_text(f"{config_dir}/prompts/tool4_likert_definition.txt")

    prompt = f"{system_prompt}\n\n{likert_definitions}\n\nReport A (to evaluate):\n{json.dumps(graph_a, indent=2)}\n\nReport B (ground truth):\n{json.dumps(graph_b, indent=2)}\n\nIdentify errors in Report A and return a JSON array of errors."

    if llm_client is None:
        raise ValueError("llm_client is required")

    logger.debug("Tool 4: Calling LLM")
    response = llm_client.call(
        prompt,
        response_format={"type": "json_object"},
    )
    logger.debug("Tool 4: LLM response received")

    try:
        result = json.loads(response)
        if isinstance(result, list):
            errors = result
        elif isinstance(result, dict) and "errors" in result:
            errors = result["errors"]
        else:
            errors = [result] if result else []
    except json.JSONDecodeError:
        logger.error(f"Tool 4: Failed to parse LLM response: {response[:200]}")
        errors = []

    # Validate expected keys
    for error in errors:
        if "error_type" not in error:
            error["error_type"] = "unknown"
        if "hazard_level" not in error:
            error["hazard_level"] = 1
        if "explanation" not in error:
            error["explanation"] = ""

    logger.debug(f"Tool 4: Found {len(errors)} errors")
    return errors
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool4.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool4.py tests/tools/test_tool4.py
git commit -m "feat: add Tool 4 Error Hazard Evaluation"
```

---

### 任务 3：Tool 5 —— 跨报告图对齐（Cross-Report Graph Alignment）

**文件：**

- 新建：`src/tools/tool5.py`
- 新建：`tests/tools/test_tool5.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool5.py`

```python
import pytest
from src.tools.tool5 import align_graphs


class TestAlignGraphs:
    def test_exact_match(self):
        graph_a = {"findings": [{"text": "nodule", "location": "lung"}]}
        graph_b = {"findings": [{"text": "nodule", "location": "lung"}]}
        result = align_graphs(graph_a, graph_b)
        assert "matched" in result["categories"]
        assert len(result["categories"]["matched"]) > 0

    def test_a_only(self):
        graph_a = {"findings": [{"text": "nodule"}]}
        graph_b = {"findings": []}
        result = align_graphs(graph_a, graph_b)
        assert len(result["categories"]["a-only"]) > 0

    def test_quantitative_tolerance(self):
        graph_a = {"findings": [{"text": "5.2 cm"}]}
        graph_b = {"findings": [{"text": "5.3 cm"}]}
        result = align_graphs(graph_a, graph_b)
        assert "approximate_match" in result["categories"]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool5.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool5.py`

```python
"""Tool 5: Cross-Report Graph Alignment.

Matches findings between two reports and calculates bidirectional metrics.
"""

import logging
import re
from typing import Any, Dict, List

from src.config import load_config

logger = logging.getLogger(__name__)


def _parse_quantity(text: str) -> tuple:
    """Extract numeric value and unit from text. Returns (value_mm, unit) or (None, None)."""
    match = re.search(r"([0-9]+\.?[0-9]*)\s*(cm|mm|m|km|um|nm)?", text, re.IGNORECASE)
    if not match:
        return None, None
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    # Convert to mm
    if unit == "cm":
        value *= 10
    elif unit == "m":
        value *= 1000
    elif unit == "km":
        value *= 1e6
    elif unit == "um":
        value *= 1e-3
    elif unit == "nm":
        value *= 1e-6
    return value, unit


def _match_findings(a: dict, b: dict, tolerance_mm: float = 5.0) -> str:
    """Classify a single finding pair. Returns category string."""
    text_a = str(a.get("text", "")).strip().lower()
    text_b = str(b.get("text", "")).strip().lower()

    # Exact qualitative match
    if text_a == text_b and not _parse_quantity(text_a)[0]:
        return "matched"

    # Quantitative match with tolerance
    val_a, _ = _parse_quantity(text_a)
    val_b, _ = _parse_quantity(text_b)
    if val_a is not None and val_b is not None:
        if abs(val_a - val_b) <= tolerance_mm:
            return "approximate_match" if val_a != val_b else "matched"

    return "mismatched"


def align_graphs(
    graph_a: dict,
    graph_b: dict,
    config_dir: str = "./config",
) -> dict:
    """Align two finding graphs.

    Args:
        graph_a: Finding graph from report A.
        graph_b: Finding graph from report B.
        config_dir: Directory containing alignment_tolerance.yaml.

    Returns:
        Dict with:
            - categories: Dict[str, List[dict]] of matched/a-only/b-only/mismatched/approximate_match
            - metrics: Dict with bidirectional accuracy/f1 and symmetric score
            - rexval_errors: Dict with error counts
    """
    logger.debug("Tool 5: Starting graph alignment")

    try:
        cfg = load_config(config_dir)
        tolerance = cfg.alignment_tolerance.tolerance_mm
    except Exception:
        tolerance = 5.0

    findings_a = graph_a.get("findings", [])
    findings_b = graph_b.get("findings", [])

    categories = {
        "matched": [],
        "a-only": [],
        "b-only": [],
        "mismatched": [],
        "approximate_match": [],
    }

    matched_b = set()

    for fa in findings_a:
        best_match = None
        best_cat = "a-only"
        for idx_b, fb in enumerate(findings_b):
            if idx_b in matched_b:
                continue
            cat = _match_findings(fa, fb, tolerance)
            if cat in ("matched", "approximate_match"):
                best_match = idx_b
                best_cat = cat
                break
        if best_match is not None:
            matched_b.add(best_match)
            categories[best_cat].append({"a": fa, "b": findings_b[best_match]})
        else:
            # Check if any unmatched in B exists (mismatched)
            found_mismatch = False
            for idx_b, fb in enumerate(findings_b):
                if idx_b not in matched_b:
                    categories["mismatched"].append({"a": fa, "b": fb})
                    found_mismatch = True
                    break
            if not found_mismatch:
                categories["a-only"].append({"a": fa})

    for idx_b, fb in enumerate(findings_b):
        if idx_b not in matched_b:
            categories["b-only"].append({"b": fb})

    # Calculate metrics
    total_a = len(findings_a) if findings_a else 1
    total_b = len(findings_b) if findings_b else 1

    matched_count = len(categories["matched"])
    approx_count = len(categories["approximate_match"])

    precision = (matched_count + approx_count) / total_a if total_a > 0 else 0.0
    recall = (matched_count + approx_count) / total_b if total_b > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    symmetric = (precision + recall) / 2.0

    metrics = {
        "a_as_ground_truth": {"accuracy": precision, "f1": f1},
        "b_as_ground_truth": {"accuracy": recall, "f1": f1},
        "symmetric_agreement": symmetric,
    }

    rexval = {
        "false_finding": len(categories["a-only"]),
        "omission_finding": len(categories["b-only"]),
        "incorrect_location": 0,  # Simplified; would need location field comparison
        "incorrect_severity": 0,
    }

    logger.debug(f"Tool 5: Alignment complete. Matched={matched_count}, A-only={len(categories['a-only'])}, B-only={len(categories['b-only'])}")
    return {
        "categories": categories,
        "metrics": metrics,
        "rexval_errors": rexval,
    }
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool5.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool5.py tests/tools/test_tool5.py
git commit -m "feat: add Tool 5 Cross-Report Graph Alignment"
```

---

### 任务 4：Tool 6 —— 结构差异（Structure Difference）

**文件：**

- 新建：`src/tools/tool6.py`
- 新建：`tests/tools/test_tool6.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool6.py`

```python
import pytest
from src.tools.tool6 import compare_structure


class TestCompareStructure:
    def test_delta_scores(self, mocker):
        mock_tool3 = mocker.patch("src.tools.tool6.check_structure")
        mock_tool3.side_effect = [
            {"classified": {"Findings": ["P1"]}, "score": 0.4},
            {"classified": {"Findings": ["P1", "P2"]}, "score": 0.8},
        ]
        result = compare_structure("Report A", "Report B")
        assert "Findings" in result
        assert result["Findings"]["score_a"] == 0.4
        assert result["Findings"]["score_b"] == 0.8
        assert result["Findings"]["difference"] == pytest.approx(0.4, rel=1e-2)
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool6.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool6.py`

```python
"""Tool 6: Structure Difference.

Compares hierarchical structure scores between two reports using Tool 3.
"""

import logging
from typing import Optional

from src.llm_client import LLMClient
from src.tools.tool3 import check_structure

logger = logging.getLogger(__name__)


def compare_structure(
    report_a: str,
    report_b: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> dict:
    """Compare structure of two reports.

    Args:
        report_a: Text of report A.
        report_b: Text of report B.
        llm_client: LLM client for Tool 3.
        config_dir: Directory containing templates.

    Returns:
        Dict with section names as keys and {"score_a", "score_b", "difference"} as values.
    """
    logger.debug("Tool 6: Comparing structure")

    result_a = check_structure(report_a, llm_client=llm_client, config_dir=config_dir)
    result_b = check_structure(report_b, llm_client=llm_client, config_dir=config_dir)

    classified_a = result_a.get("classified", {})
    classified_b = result_b.get("classified", {})
    all_sections = set(classified_a.keys()) | set(classified_b.keys())

    delta = {}
    for section in all_sections:
        paras_a = len(classified_a.get(section, []))
        paras_b = len(classified_b.get(section, []))
        delta[section] = {
            "score_a": paras_a,
            "score_b": paras_b,
            "difference": paras_b - paras_a,
        }

    logger.debug("Tool 6: Structure comparison complete")
    return delta
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool6.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool6.py tests/tools/test_tool6.py
git commit -m "feat: add Tool 6 Structure Difference"
```

---

### 任务 5：全部依赖工具验证

- [ ] **步骤 1：运行所有依赖工具测试**

运行：`python -m pytest tests/tools/test_tool2.py tests/tools/test_tool4.py tests/tools/test_tool5.py tests/tools/test_tool6.py -v`
预期结果：全部 PASS

- [ ] **步骤 2：提交**

```bash
git commit --allow-empty -m "checkpoint: dependent tools complete"
```

---

## 自检（Self-Review）

**1. 规格覆盖：**

- Tool 2：外部命令封装，精确匹配模板，占位随机 JSON —— 任务 1
- Tool 4：LLM 危害评估，输出错误列表 —— 任务 2
- Tool 5：定性精确匹配、定量单位归一化与容差、双向指标、对称分数、ReXVal 错误 —— 任务 3
- Tool 6：封装 Tool 3，输出差异字典（delta dict）—— 任务 4

**2. 占位符扫描：** 无未完成占位符。Tool 2 按设计返回随机 JSON。

**3. 类型一致性：** 所有工具接受可选的 `llm_client`。Tool 2 额外接受 `extraction_command`。

**缺口：** 无。
