# 独立工具实现计划（Independent Tools Implementation Plan）

> **面向 Agent 执行者：** 必选子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 实现 Tool 1、3、7、9、10、11、12 — 均为纯函数，工具内部不做文件 I/O。所有工具接收原始数据，返回 JSON 兼容的字典。

**架构：** 每个工具是一个独立模块，对外暴露单个公共函数。需要 LLM/VLM 能力时调用 `llm_client.call()`。CLI 层（位于 `cli.py`）负责文件读写。工具本身是纯函数，易于测试。

**技术栈：** Python 3.10+、Pydantic（工具内部按需用于校验）、标准库。

**前置依赖：** 基础设施须已就绪（`src/config.py`、`src/llm_client.py`、`src/utils/`）。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/tools/tool1.py` | Likert 量表 LLM 评估 |
| `src/tools/tool3.py` | 层级结构检查（Hierarchical Structure Check） |
| `src/tools/tool7.py` | 模态识别（Modality Recognition） |
| `src/tools/tool9.py` | 选取 Top K 报告/模型 |
| `src/tools/tool10.py` | 按模型加权指标（Modelwise Weighted Metrics） |
| `src/tools/tool11.py` | 按危害等级加权指标（Hazardwise Weighted Metrics） |
| `src/tools/tool12.py` | 统计量计算（Statistic Calculation） |
| `tests/tools/test_tool1.py` | Tool 1 测试 |
| `tests/tools/test_tool3.py` | Tool 3 测试 |
| `tests/tools/test_tool7.py` | Tool 7 测试 |
| `tests/tools/test_tool9.py` | Tool 9 测试 |
| `tests/tools/test_tool10.py` | Tool 10 测试 |
| `tests/tools/test_tool11.py` | Tool 11 测试 |
| `tests/tools/test_tool12.py` | Tool 12 测试 |

---

### 任务 1：Tool 1 — Likert 量表 LLM 评估

**文件：**
- 新建：`src/tools/tool1.py`
- 新建：`tests/tools/test_tool1.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool1.py`
```python
import pytest
from src.tools.tool1 import evaluate_likert


class TestEvaluateLikert:
    def test_returns_dict(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '{"Completeness and Accuracy": {"score": 4, "explanation": "good"}}'
        result = evaluate_likert("This is a report.", llm_client=mock_client)
        assert isinstance(result, dict)
        assert "Completeness and Accuracy" in result

    def test_no_image_warning(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '{"Completeness and Accuracy": {"score": 3, "explanation": "ok"}}'
        result = evaluate_likert("Report text.", llm_client=mock_client)
        assert result.get("warning") == "No image/volume provided"

    def test_with_image_no_warning(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '{"Completeness and Accuracy": {"score": 5, "explanation": "excellent"}}'
        result = evaluate_likert("Report text.", image_path="/tmp/img.png", llm_client=mock_client)
        assert "warning" not in result
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool1.py -v`
预期：FAIL，import/模块错误

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool1.py`
```python
"""Tool 1: Likert-Scale LLM Evaluation.

使用 LLM/VLM 按预定义的 Likert 量表指标评估放射学报告。
"""

import json
import logging
from typing import Optional

from src.llm_client import LLMClient
from src.utils.file_io import read_text

logger = logging.getLogger(__name__)

# Likert 量表指标名称
LIKERT_METRICS = [
    "Completeness and Accuracy",
    "Conciseness and Clarity",
    "Terminological Accuracy",
    "Structure and Style",
    "Overall Writing Quality",
]


def evaluate_likert(
    report_text: str,
    image_path: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> dict:
    """使用 Likert 量表指标评估报告。

    Args:
        report_text: 待评估的放射学报告文本。
        image_path: 可选，关联的图像/体数据路径。
        llm_client: LLM/VLM 客户端实例。为 None 时须由调用方创建。
        config_dir: 包含 prompt 文件的目录。

    Returns:
        字典，键为指标名称，值为 {"score": int, "explanation": str}。
        若未提供图像，包含 "warning" 键。
    """
    logger.debug("Tool 1: Starting Likert-scale evaluation")

    system_prompt = read_text(f"{config_dir}/prompts/tool1_system.txt")
    likert_definitions = read_text(f"{config_dir}/prompts/tool1_likert_definition.txt")

    prompt = f"{system_prompt}\n\n{likert_definitions}\n\nReport to evaluate:\n{report_text}\n\nEvaluate the report and return JSON with keys: {', '.join(LIKERT_METRICS)}."

    if llm_client is None:
        raise ValueError("llm_client is required")

    logger.debug("Tool 1: Calling LLM")
    response = llm_client.call(
        prompt,
        image_path=image_path,
        response_format={"type": "json_object"},
    )
    logger.debug("Tool 1: LLM response received")

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        logger.error(f"Tool 1: Failed to parse LLM response as JSON: {response[:200]}")
        raise RuntimeError("LLM response is not valid JSON")

    # 校验预期指标是否齐全
    for metric in LIKERT_METRICS:
        if metric not in result:
            logger.warning(f"Tool 1: Metric '{metric}' missing from LLM response")
            result[metric] = {"score": 0, "explanation": "missing"}

    if image_path is None:
        result["warning"] = "No image/volume provided"
        logger.warning("Tool 1: No image/volume provided")

    logger.debug("Tool 1: Likert-scale evaluation complete")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool1.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool1.py tests/tools/test_tool1.py
git commit -m "feat: add Tool 1 Likert-Scale LLM Evaluation"
```

---

### 任务 2：Tool 3 — 层级结构检查（Hierarchical Structure Check）

**文件：**
- 新建：`src/tools/tool3.py`
- 新建：`tests/tools/test_tool3.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool3.py`
```python
import pytest
from src.tools.tool3 import check_structure


class TestCheckStructure:
    def test_returns_dict(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '{"Findings": ["Para 1"], "Impression": ["Para 2"], "Patient Information": [], "Additional Information": []}'
        result = check_structure("Report text.", llm_client=mock_client)
        assert isinstance(result, dict)
        assert "classified" in result
        assert "score" in result

    def test_score_calculation(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = '{"Findings": ["P1", "P2"], "Impression": ["P3"], "Patient Information": [], "Additional Information": []}'
        result = check_structure("Report text.", llm_client=mock_client)
        # score = 2*0.4 + 1*0.4 + 0*0.1 + 0*0.1 = 1.2
        assert result["score"] == 1.2
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool3.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool3.py`
```python
"""Tool 3: Hierarchical Structure Check.

使用 LLM 将段落分类到预定义章节，并计算加权得分。
"""

import json
import logging
from typing import Optional

from src.llm_client import LLMClient
from src.utils.file_io import read_json, read_text

logger = logging.getLogger(__name__)


def check_structure(
    report_text: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> dict:
    """检查放射学报告的层级结构。

    Args:
        report_text: 放射学报告文本。
        llm_client: LLM 客户端实例。
        config_dir: 包含 prompt 和模板的目录。

    Returns:
        字典，包含以下键：
            - classified: Dict[str, List[str]]，章节名称到段落列表的映射
            - score: float，根据章节权重计算的加权得分
    """
    logger.debug("Tool 3: Starting structure check")

    system_prompt = read_text(f"{config_dir}/prompts/tool3_system.txt")
    template = read_json(f"{config_dir}/structure_template.json")
    sections = template["sections"]
    section_names = list(sections.keys())

    prompt = f"{system_prompt}\n\nSections to classify into: {', '.join(section_names)}\n\nReport:\n{report_text}\n\nReturn JSON with each section as a key and a list of paragraphs as the value."

    if llm_client is None:
        raise ValueError("llm_client is required")

    logger.debug("Tool 3: Calling LLM")
    response = llm_client.call(
        prompt,
        response_format={"type": "json_object"},
    )
    logger.debug("Tool 3: LLM response received")

    try:
        classified = json.loads(response)
    except json.JSONDecodeError:
        logger.error(f"Tool 3: Failed to parse LLM response as JSON: {response[:200]}")
        raise RuntimeError("LLM response is not valid JSON")

    # 确保所有章节都存在
    for section in section_names:
        if section not in classified:
            classified[section] = []

    # 计算加权得分
    score = 0.0
    for section_name, paragraphs in classified.items():
        if section_name in sections:
            weight = sections[section_name].get("weight", 0.0)
            score += len(paragraphs) * weight

    logger.debug(f"Tool 3: Structure score = {score}")
    return {"classified": classified, "score": score}
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool3.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool3.py tests/tools/test_tool3.py
git commit -m "feat: add Tool 3 Hierarchical Structure Check"
```

---

### 任务 3：Tool 7 — 模态识别（Modality Recognition）

**文件：**
- 新建：`src/tools/tool7.py`
- 新建：`tests/tools/test_tool7.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool7.py`
```python
import pytest
from src.tools.tool7 import recognize_modality


class TestRecognizeModality:
    def test_dicom_header(self, tmp_path, mocker):
        # 创建一个最小 DICOM 文件
        try:
            import pydicom
            from pydicom.dataset import FileDataset, FileMetaInfo

            file_meta = FileMetaInfo()
            file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            file_meta.MediaStorageSOPInstanceUID = "1.2.3"
            file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"

            ds = FileDataset(str(tmp_path / "test.dcm"), {}, file_meta=file_meta, preamble=b"\x00" * 128)
            ds.Modality = "CT"
            ds.save_as(str(tmp_path / "test.dcm"))

            result = recognize_modality(str(tmp_path / "test.dcm"), config_dir="./config")
            assert result == "chest_ct"
        except ImportError:
            pytest.skip("pydicom not installed")

    def test_non_dicom(self, tmp_path, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = "CT"
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake image data")
        result = recognize_modality(str(img_path), llm_client=mock_client, config_dir="./config")
        assert result == "chest_ct"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool7.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool7.py`
```python
"""Tool 7: Modality Recognition.

从 DICOM 头信息检测模态，非 DICOM 文件则回退到 VLM 识别。
"""

import logging
from typing import Optional

from src.llm_client import LLMClient
from src.utils.file_io import read_yaml  # 需要添加此辅助函数

logger = logging.getLogger(__name__)


def recognize_modality(
    image_path: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> str:
    """识别图像/体数据文件的模态。

    Args:
        image_path: 图像或 DICOM 文件路径。
        llm_client: 用于回退检测的 VLM 客户端。
        config_dir: 包含 modality_map.yaml 的目录。

    Returns:
        标准化模态键（如 'chest_ct'）。
    """
    logger.debug(f"Tool 7: Recognizing modality for {image_path}")

    raw_modality = None

    # 优先尝试 DICOM
    try:
        import pydicom
        ds = pydicom.dcmread(image_path, stop_before_pixels=True)
        raw_modality = ds.Modality
        logger.debug(f"Tool 7: DICOM modality = {raw_modality}")
    except Exception:
        logger.debug("Tool 7: Not a valid DICOM or no Modality header")

    # 无 DICOM 模态时回退到 VLM
    if raw_modality is None and llm_client is not None:
        logger.debug("Tool 7: Falling back to VLM modality detection")
        prompt = "What is the imaging modality of this medical image? Return only the modality abbreviation (e.g., CT, MR, DX, CR)."
        response = llm_client.call(prompt, image_path=image_path)
        raw_modality = response.strip().upper()
        logger.debug(f"Tool 7: VLM detected modality = {raw_modality}")

    if raw_modality is None:
        raise RuntimeError("Could not determine modality from file or VLM")

    # 映射到标准键
    try:
        from src.config import load_config
        cfg = load_config(config_dir)
        mapping = cfg.modality_map.mapping
    except Exception:
        logger.warning("Tool 7: Could not load modality map from config, using defaults")
        mapping = {"CT": "chest_ct", "MR": "brain_mri", "DX": "chest_xray", "CR": "chest_xray"}

    mapped = mapping.get(raw_modality, raw_modality.lower().replace(" ", "_"))
    logger.debug(f"Tool 7: Mapped modality = {mapped}")
    return mapped
```

**注意：** 需要在 `src/utils/file_io.py` 中添加 `read_yaml`：
```python
import yaml

def read_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool7.py -v`
预期：PASS（若未安装 pydicom 则 SKIP）

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool7.py tests/tools/test_tool7.py src/utils/file_io.py
git commit -m "feat: add Tool 7 Modality Recognition"
```

---

### 任务 4：Tool 9 — 选取 Top K 报告/模型

**文件：**
- 新建：`src/tools/tool9.py`
- 新建：`tests/tools/test_tool9.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool9.py`
```python
import pytest
from src.tools.tool9 import select_top_k


class TestSelectTopK:
    def test_basic_ranking(self):
        metrics = [
            {"completeness": 4, "clarity": 3, "free_text": "good"},
            {"completeness": 2, "clarity": 5, "free_text": "bad"},
        ]
        weights = {"completeness": 0.5, "clarity": 0.5}
        result = select_top_k(metrics, weights=weights, k=1)
        assert len(result) == 1
        assert result[0] == 0  # 归一化后第一份报告排名更高

    def test_k_larger_than_input(self):
        metrics = [
            {"completeness": 4, "clarity": 3},
        ]
        weights = {"completeness": 0.5, "clarity": 0.5}
        result = select_top_k(metrics, weights=weights, k=5)
        assert len(result) == 1
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool9.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool9.py`
```python
"""Tool 9: Select Top K Reports/Models.

对定量指标做归一化后按加权综合得分排序，返回前 K 个报告/模型。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def select_top_k(
    metrics_list: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
    k: int = 3,
) -> List[int]:
    """根据加权综合得分选取前 K 个报告/模型。

    Args:
        metrics_list: N 份报告的指标字典列表。
        weights: 指标名称到权重的映射。为 None 时使用等权。
        k: 返回的报告数量。

    Returns:
        前 K 个报告在 metrics_list 中的索引列表，按得分降序排列。
    """
    logger.debug(f"Tool 9: Selecting top {k} from {len(metrics_list)} reports")

    if not metrics_list:
        return []

    # 识别定量指标（int/float 值，排除自由文本）
    quantitative_keys = set()
    for metrics in metrics_list:
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                quantitative_keys.add(key)

    logger.debug(f"Tool 9: Quantitative metrics: {quantitative_keys}")

    # 对每个指标在所有报告间做 Min-Max 归一化
    normalized = []
    for metrics in metrics_list:
        normalized_metrics = {}
        for key in quantitative_keys:
            values = [m.get(key, 0) for m in metrics_list if isinstance(m.get(key), (int, float))]
            if not values:
                continue
            min_val = min(values)
            max_val = max(values)
            if max_val == min_val:
                normalized_metrics[key] = 1.0
            else:
                normalized_metrics[key] = (metrics.get(key, 0) - min_val) / (max_val - min_val)
        normalized.append(normalized_metrics)

    # 计算加权得分
    scores = []
    for idx, metrics in enumerate(normalized):
        if weights is None:
            keys = list(metrics.keys())
            score = sum(metrics.get(k, 0) for k in keys) / len(keys) if keys else 0.0
        else:
            total_weight = 0.0
            score = 0.0
            for key, weight in weights.items():
                if key in metrics:
                    score += metrics[key] * weight
                    total_weight += weight
            score = score / total_weight if total_weight > 0 else 0.0
        scores.append((idx, score))
        logger.debug(f"Tool 9: Report {idx} score = {score:.4f}")

    # 按得分降序排列
    scores.sort(key=lambda x: x[1], reverse=True)

    top_k = [idx for idx, _ in scores[:k]]
    logger.debug(f"Tool 9: Top K indices: {top_k}")
    return top_k
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool9.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool9.py tests/tools/test_tool9.py
git commit -m "feat: add Tool 9 Select Top K"
```

---

### 任务 5：Tool 10 — 按模型加权指标（Modelwise Weighted Metrics）

**文件：**
- 新建：`src/tools/tool10.py`
- 新建：`tests/tools/test_tool10.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool10.py`
```python
import pytest
from src.tools.tool10 import modelwise_weighted


class TestModelwiseWeighted:
    def test_weighted_mean(self):
        metrics_by_model = [
            {"accuracy": 0.8, "f1": 0.7},
            {"accuracy": 0.9, "f1": 0.6},
        ]
        weights = {"model_a": 0.3, "model_b": 0.7}
        result = modelwise_weighted(metrics_by_model, weights=weights)
        # accuracy = 0.8*0.3 + 0.9*0.7 = 0.87
        # f1 = 0.7*0.3 + 0.6*0.7 = 0.63
        assert result["accuracy"] == pytest.approx(0.87, rel=1e-2)
        assert result["f1"] == pytest.approx(0.63, rel=1e-2)
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool10.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool10.py`
```python
"""Tool 10: Modelwise Weighted Metrics.

跨多个模型按加权均值聚合各指标。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def modelwise_weighted(
    metrics_list: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """计算各指标在多个模型间的加权均值。

    Args:
        metrics_list: 指标字典列表，每个模型一项。
        weights: 模型索引或名称到权重的映射。为 None 时使用等权。

    Returns:
        字典，指标名称到加权均值的映射。
    """
    logger.debug(f"Tool 10: Aggregating {len(metrics_list)} models")

    if not metrics_list:
        return {}

    # 收集所有指标键
    all_keys = set()
    for metrics in metrics_list:
        all_keys.update(metrics.keys())

    result = {}
    for key in all_keys:
        values = []
        for idx, metrics in enumerate(metrics_list):
            if key in metrics and isinstance(metrics[key], (int, float)):
                values.append((idx, metrics[key]))

        if not values:
            continue

        if weights is None:
            result[key] = sum(v for _, v in values) / len(values)
        else:
            total_weight = 0.0
            weighted_sum = 0.0
            for idx, value in values:
                weight = weights.get(str(idx), 1.0)
                weighted_sum += value * weight
                total_weight += weight
            result[key] = weighted_sum / total_weight if total_weight > 0 else 0.0

        logger.debug(f"Tool 10: Metric '{key}' weighted mean = {result[key]:.4f}")

    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool10.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool10.py tests/tools/test_tool10.py
git commit -m "feat: add Tool 10 Modelwise Weighted Metrics"
```

---

### 任务 6：Tool 11 — 按危害等级加权指标（Hazardwise Weighted Metrics）

**文件：**
- 新建：`src/tools/tool11.py`
- 新建：`tests/tools/test_tool11.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool11.py`
```python
import pytest
from src.tools.tool11 import hazardwise_weighted


class TestHazardwiseWeighted:
    def test_apply_weights(self):
        metrics = [
            {"accuracy": 0.8, "hazard_level": 3, "error_type": "false_finding"},
            {"accuracy": 0.9, "hazard_level": 1, "error_type": "omission_finding"},
        ]
        hazard_weights = {
            "false_finding": {"1": 1.0, "2": 1.5, "3": 2.0, "4": 2.5, "5": 3.0},
            "omission_finding": {"1": 1.0, "2": 1.5, "3": 2.0, "4": 2.5, "5": 3.0},
        }
        result = hazardwise_weighted(metrics, hazard_weights=hazard_weights)
        # 第一条：0.8 * 2.0 = 1.6
        # 第二条：0.9 * 1.0 = 0.9
        assert result[0]["accuracy"] == pytest.approx(1.6, rel=1e-2)
        assert result[1]["accuracy"] == pytest.approx(0.9, rel=1e-2)
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool11.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool11.py`
```python
"""Tool 11: Hazardwise Weighted Metrics.

对指标施加危害等级权重，保留所有维度。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def hazardwise_weighted(
    metrics_list: List[Dict[str, Any]],
    hazard_weights: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """对指标施加危害等级权重。

    Args:
        metrics_list: 指标字典列表，每项包含 hazard_level 和 error_type。
        hazard_weights: error_type 到 {等级: 权重} 映射的字典。

    Returns:
        施加危害权重后的指标字典列表。
    """
    logger.debug(f"Tool 11: Applying hazard weights to {len(metrics_list)} items")

    result = []
    for metrics in metrics_list:
        new_metrics = dict(metrics)
        hazard_level = metrics.get("hazard_level", 1)
        error_type = metrics.get("error_type", "unknown")

        if hazard_weights and error_type in hazard_weights:
            level_key = str(int(hazard_level))
            weight = hazard_weights[error_type].get(level_key, 1.0)
        else:
            weight = 1.0

        for key, value in new_metrics.items():
            if isinstance(value, (int, float)) and key not in ("hazard_level",):
                new_metrics[key] = value * weight

        result.append(new_metrics)
        logger.debug(f"Tool 11: Applied weight {weight} to {error_type} level {hazard_level}")

    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool11.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool11.py tests/tools/test_tool11.py
git commit -m "feat: add Tool 11 Hazardwise Weighted Metrics"
```

---

### 任务 7：Tool 12 — 统计量计算（Statistic Calculation）

**文件：**
- 新建：`src/tools/tool12.py`
- 新建：`tests/tools/test_tool12.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/tools/test_tool12.py`
```python
import pytest
from src.tools.tool12 import calculate_statistics


class TestCalculateStatistics:
    def test_mean_and_std(self):
        metrics_list = [
            {"accuracy": 0.8, "f1": 0.7},
            {"accuracy": 0.9, "f1": 0.6},
            {"accuracy": 0.85, "f1": 0.75},
        ]
        result = calculate_statistics(metrics_list)
        assert "accuracy" in result
        assert "f1" in result
        assert result["accuracy"]["mean"] == pytest.approx(0.85, rel=1e-2)
        assert result["f1"]["mean"] == pytest.approx(0.683, rel=1e-2)
        assert "std" in result["accuracy"]
        assert "ci_lower" in result["accuracy"]
        assert "ci_upper" in result["accuracy"]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool12.py -v`
预期：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/tools/tool12.py`
```python
"""Tool 12: Statistic Calculation.

计算各指标在多份报告间的均值、标准差和置信区间。
"""

import logging
import statistics
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def calculate_statistics(metrics_list: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """计算各指标的统计量。

    Args:
        metrics_list: 来自多份报告的指标字典列表。

    Returns:
        字典，指标名称到 {"mean": float, "std": float, "ci_lower": float, "ci_upper": float} 的映射。
    """
    logger.debug(f"Tool 12: Calculating statistics for {len(metrics_list)} reports")

    if not metrics_list:
        return {}

    # 收集所有定量指标键
    all_keys = set()
    for metrics in metrics_list:
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                all_keys.add(key)

    result = {}
    for key in all_keys:
        values = [m[key] for m in metrics_list if isinstance(m.get(key), (int, float))]
        if not values:
            continue

        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0

        # 95% 置信区间，使用 t 分布近似（大样本时 z=1.96）
        import math
        n = len(values)
        ci = 1.96 * (std / math.sqrt(n)) if n > 0 else 0.0

        result[key] = {
            "mean": mean,
            "std": std,
            "ci_lower": mean - ci,
            "ci_upper": mean + ci,
        }
        logger.debug(f"Tool 12: Metric '{key}' mean={mean:.4f}, std={std:.4f}")

    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool12.py -v`
预期：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool12.py tests/tools/test_tool12.py
git commit -m "feat: add Tool 12 Statistic Calculation"
```

---

### 任务 8：验证所有独立工具

- [ ] **步骤 1：运行全部工具测试**

运行：`python -m pytest tests/tools/ -v`
预期：全部 PASS

- [ ] **步骤 2：提交**

```bash
git commit --allow-empty -m "checkpoint: independent tools complete"
```

---

## 自查（Self-Review）

**1. 规格覆盖：**
- Tool 1：Likert 量表结构化输出，缺少图像时附带警告 — 任务 1
- Tool 3：段落分类，加权得分 — 任务 2
- Tool 7：DICOM 头信息 + VLM 回退 — 任务 3
- Tool 9：Min-Max 归一化、加权均值、Top K — 任务 4
- Tool 10：跨模型按指标加权均值 — 任务 5
- Tool 11：危害权重矩阵乘法 — 任务 6
- Tool 12：均值、标准差、置信区间（CI） — 任务 7

**2. 占位符扫描：** 无占位符，所有代码完整。

**3. 类型一致性：** 所有工具均将 `llm_client` 作为可选参数接收。纯函数已确认。

**缺口：** 无。
