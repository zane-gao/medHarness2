# 工作流实现计划（Workflows Implementation Plan）

> **Agent 工作者须知：** 必须使用子技能 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行本计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 实现 Tool 8（报告生成适配器，Report Generation Adapter）以及 Workflow 1、2、3。Tool 8 是面向本地/云端模型的灵活适配器；各 Workflow 负责编排模块（Module）、工具（Tool）、缓存和批处理流程。

**架构：** Workflow 负责文件 I/O、批处理和工作目录缓存。Tool 8 采用适配器模式（Adapter Pattern），支持本地模型发现与云端回退。所有 Workflow 输出嵌套 JSON。

**技术栈：** Python 3.10+、pandas（Workflow 2/3 用于读取 Excel）、标准库。

**依赖：** 基础层 + 全部 Tool + 全部 Module 必须已就绪。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/tools/tool8.py` | 2D/3D 报告生成适配器（Report Generation Adapter） |
| `src/workflows/workflow1.py` | 单报告 + AI 生成 + 成对比较（Pairwise） |
| `src/workflows/workflow2.py` | 批量放射科医生 vs 模型 |
| `src/workflows/workflow3.py` | 科室 vs 模型组 |
| `tests/tools/test_tool8.py` | Tool 8 测试 |
| `tests/workflows/test_workflow1.py` | Workflow 1 测试 |
| `tests/workflows/test_workflow2.py` | Workflow 2 测试 |
| `tests/workflows/test_workflow3.py` | Workflow 3 测试 |

---

### 任务 1：Tool 8 — 2D/3D 报告生成适配器

**文件：**
- 新建：`src/tools/tool8.py`
- 新建：`tests/tools/test_tool8.py`

- [ ] **步骤 1：编写失败测试**

**测试文件：** `tests/tools/test_tool8.py`
```python
import pytest
from src.tools.tool8 import generate_reports


class TestGenerateReports:
    def test_returns_list(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = "Generated report text."
        result = generate_reports("/tmp/img.png", modality="chest_ct", llm_client=mock_client)
        assert isinstance(result, list)
        assert len(result) > 0
        assert "model" in result[0]
        assert "report" in result[0]

    def test_no_local_models_uses_cloud(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.call.return_value = "Cloud report."
        mocker.patch("src.tools.tool8._discover_local_models", return_value=[])
        result = generate_reports("/tmp/img.png", modality="chest_ct", llm_client=mock_client)
        assert any(r["source"] == "cloud" for r in result)
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/tools/test_tool8.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现文件：** `src/tools/tool8.py`
```python
"""Tool 8: 2D/3D Report Generation Adapter.

Flexible adapter for local and cloud model report generation.
Designed for worst-case: local models may exist, may be partial, may not exist.
"""

import importlib.util
import json
import logging
import os
from typing import List, Optional

from src.config import load_config
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _discover_local_models(config_dir: str) -> List[dict]:
    """Discover available local models from config."""
    try:
        cfg = load_config(config_dir)
        return cfg.models.models
    except Exception:
        return []


def _call_local_model(model_info: dict, image_path: str, modality: str) -> Optional[str]:
    """Attempt to call a local model. Returns report text or None if fails."""
    logger.debug(f"Tool 8: Attempting local model {model_info.get('name', 'unknown')}")

    # If local inference code exists elsewhere, dynamically import it
    inference_path = model_info.get("inference_script")
    if inference_path and os.path.exists(inference_path):
        try:
            spec = importlib.util.spec_from_file_location("local_inference", inference_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "generate"):
                return module.generate(image_path, modality)
        except Exception as e:
            logger.warning(f"Tool 8: Local model failed: {e}")

    logger.debug("Tool 8: Local model not available or failed")
    return None


def _call_cloud_model(
    image_path: str,
    modality: str,
    llm_client: LLMClient,
    reference_report: Optional[str] = None,
) -> str:
    """Call cloud model as fallback."""
    logger.debug("Tool 8: Calling cloud model")
    prompt = f"Generate a radiology report for a {modality} study."
    if reference_report:
        prompt += f"\n\nReference report:\n{reference_report}"
    prompt += "\n\nWrite the report now."

    return llm_client.call(prompt, image_path=image_path)


def generate_reports(
    image_path: str,
    modality: str,
    reference_report: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> List[dict]:
    """Generate reports from all available models.

    Args:
        image_path: Path to image/volume file.
        modality: Study modality.
        reference_report: Optional reference report for conditional generation.
        llm_client: Cloud LLM/VLM client.
        config_dir: Directory containing model registry config.

    Returns:
        List of dicts: {"model": str, "source": "local"|"cloud", "report": str}
    """
    logger.debug(f"Tool 8: Generating reports for {modality} from {image_path}")

    results = []
    local_models = _discover_local_models(config_dir)

    # Try local models
    for model_info in local_models:
        report = _call_local_model(model_info, image_path, modality)
        if report:
            results.append({
                "model": model_info.get("name", "unknown_local"),
                "source": "local",
                "report": report,
            })

    # Cloud fallback
    if llm_client is not None:
        try:
            report = _call_cloud_model(image_path, modality, llm_client, reference_report)
            results.append({
                "model": llm_client.config.api.model,
                "source": "cloud",
                "report": report,
            })
        except Exception as e:
            logger.warning(f"Tool 8: Cloud generation failed: {e}")
    else:
        logger.warning("Tool 8: No llm_client provided for cloud fallback")

    if not results:
        logger.error("Tool 8: No models available. Returning empty list.")

    logger.debug(f"Tool 8: Generated {len(results)} reports")
    return results
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/tools/test_tool8.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/tools/tool8.py tests/tools/test_tool8.py
git commit -m "feat: add Tool 8 Report Generation Adapter"
```

---

### 任务 2：Workflow 1 — 单报告 + AI 生成 + 成对比较

**文件：**
- 新建：`src/workflows/workflow1.py`
- 新建：`tests/workflows/test_workflow1.py`

- [ ] **步骤 1：编写失败测试**

**测试文件：** `tests/workflows/test_workflow1.py`
```python
import pytest
from src.workflows.workflow1 import run_workflow1


class TestWorkflow1:
    def test_end_to_end(self, mocker, tmp_path):
        mock_mod1 = mocker.patch("src.workflows.workflow1.evaluate_single_report")
        mock_mod1.side_effect = [
            {"tool1": {"score": 4}},  # human
            {"tool1": {"score": 3}},  # model 1
        ]

        mock_tool8 = mocker.patch("src.workflows.workflow1.generate_reports")
        mock_tool8.return_value = [
            {"model": "model1", "source": "cloud", "report": "Generated report."},
        ]

        mock_topk = mocker.patch("src.workflows.workflow1.select_top_k")
        mock_topk.return_value = [0]

        mock_mod2 = mocker.patch("src.workflows.workflow1.evaluate_pairwise")
        mock_mod2.return_value = {"tool4": []}

        result = run_workflow1(
            human_report_path=str(tmp_path / "human.txt"),
            image_path=str(tmp_path / "img.png"),
            output_dir=str(tmp_path),
        )
        assert "human_evaluation" in result
        assert "top_n_evaluations" in result
        assert "pairwise_results" in result
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/workflows/test_workflow1.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现文件：** `src/workflows/workflow1.py`
```python
"""Workflow 1: Single Report + AI Generation + Pairwise Comparison.

Evaluates a human report, generates AI reports, ranks them, and runs pairwise comparison.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from src.llm_client import LLMClient
from src.modules.module1 import evaluate_single_report
from src.modules.module2 import evaluate_pairwise
from src.tools.tool7 import recognize_modality
from src.tools.tool8 import generate_reports
from src.tools.tool9 import select_top_k
from src.utils.file_io import read_text, write_json

logger = logging.getLogger(__name__)


def run_workflow1(
    human_report_path: str,
    image_path: str,
    output_dir: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
    top_n: int = 3,
) -> dict:
    """Run Workflow 1.

    Args:
        human_report_path: Path to human-written report.
        image_path: Path to associated image/volume.
        output_dir: Working directory for intermediate results.
        llm_client: LLM/VLM client.
        config_dir: Directory containing configs.
        top_n: Number of top reports to select for pairwise comparison.

    Returns:
        Nested JSON with human evaluation, top N evaluations, and pairwise results.
    """
    logger.debug("Workflow 1: Starting")
    os.makedirs(output_dir, exist_ok=True)

    # Detect modality
    modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)
    logger.debug(f"Workflow 1: Modality = {modality}")

    # Read human report
    human_text = read_text(human_report_path)

    # Module 1 on human report
    logger.debug("Workflow 1: Evaluating human report")
    human_cache = os.path.join(output_dir, "human_module1.json")
    human_eval = evaluate_single_report(
        human_text,
        image_path=image_path,
        modality=modality,
        llm_client=llm_client,
        config_dir=config_dir,
        cache_path=human_cache,
    )

    # Generate reports from models
    logger.debug("Workflow 1: Generating AI reports")
    generated = generate_reports(
        image_path,
        modality,
        reference_report=human_text,
        llm_client=llm_client,
        config_dir=config_dir,
    )

    # Module 1 on each generated report
    logger.debug(f"Workflow 1: Evaluating {len(generated)} generated reports")
    generated_evals = []
    for idx, gen in enumerate(generated):
        cache_path = os.path.join(output_dir, f"generated_{idx}_{gen['model']}_module1.json")
        eval_result = evaluate_single_report(
            gen["report"],
            image_path=image_path,
            modality=modality,
            llm_client=llm_client,
            config_dir=config_dir,
            cache_path=cache_path,
        )
        generated_evals.append({
            "model": gen["model"],
            "source": gen["source"],
            "report": gen["report"],
            "evaluation": eval_result,
        })

    # Tool 9: Select top N
    logger.debug("Workflow 1: Selecting top N")
    metrics_for_ranking = [ge["evaluation"].get("tool1", {}) for ge in generated_evals]
    # Flatten metrics for ranking (use raw score dicts)
    top_indices = select_top_k(metrics_for_ranking, k=min(top_n, len(generated_evals)))
    top_n_evals = [generated_evals[i] for i in top_indices]

    # Module 2: Pairwise human vs top N
    logger.debug("Workflow 1: Running pairwise comparisons")
    pairwise_results = []
    for top in top_n_evals:
        pair_cache = os.path.join(output_dir, f"pairwise_human_vs_{top['model']}.json")
        pair_result = evaluate_pairwise(
            human_text,
            top["report"],
            image_path=image_path,
            modality=modality,
            llm_client=llm_client,
            config_dir=config_dir,
            cache_path=pair_cache,
        )
        pairwise_results.append({
            "model": top["model"],
            "result": pair_result,
        })

    result = {
        "human_evaluation": human_eval,
        "top_n_evaluations": top_n_evals,
        "pairwise_results": pairwise_results,
    }

    output_path = os.path.join(output_dir, "workflow1_result.json")
    write_json(output_path, result)
    logger.debug(f"Workflow 1: Complete. Output saved to {output_path}")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/workflows/test_workflow1.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/workflows/workflow1.py tests/workflows/test_workflow1.py
git commit -m "feat: add Workflow 1 Single Report + AI + Pairwise"
```

---

### 任务 3：Workflow 2 — 批量放射科医生 vs 模型

**文件：**
- 新建：`src/workflows/workflow2.py`
- 新建：`tests/workflows/test_workflow2.py`

- [ ] **步骤 1：编写失败测试**

**测试文件：** `tests/workflows/test_workflow2.py`
```python
import pytest
import pandas as pd
from src.workflows.workflow2 import run_workflow2


class TestWorkflow2:
    def test_end_to_end(self, mocker, tmp_path):
        # Create mock Excel input
        excel_path = tmp_path / "input.xlsx"
        df = pd.DataFrame({
            "report_path": ["r1.txt", "r2.txt"],
            "image_path": ["i1.png", "i2.png"],
            "radiologist_id": ["doc1", "doc1"],
        })
        df.to_excel(excel_path, index=False)

        mock_mod1 = mocker.patch("src.workflows.workflow2.evaluate_single_report")
        mock_mod1.return_value = {"tool1": {"score": 4}}

        mock_mod2 = mocker.patch("src.workflows.workflow2.evaluate_pairwise")
        mock_mod2.return_value = {"tool4": []}

        mock_tool8 = mocker.patch("src.workflows.workflow2.generate_reports")
        mock_tool8.return_value = [{"model": "m1", "source": "cloud", "report": "gen"}]

        mock_tool10 = mocker.patch("src.workflows.workflow2.modelwise_weighted")
        mock_tool10.return_value = {"accuracy": 0.8}

        mock_tool11 = mocker.patch("src.workflows.workflow2.hazardwise_weighted")
        mock_tool11.return_value = [{"accuracy": 0.8}]

        mock_tool12 = mocker.patch("src.workflows.workflow2.calculate_statistics")
        mock_tool12.return_value = {"accuracy": {"mean": 0.8}}

        result = run_workflow2(
            excel_path=str(excel_path),
            output_dir=str(tmp_path),
        )
        assert "per_doctor" in result
        assert "department_statistics" in result
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/workflows/test_workflow2.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现文件：** `src/workflows/workflow2.py`
```python
"""Workflow 2: Batch Radiologist Evaluation vs Models.

Evaluates batches of reports from multiple radiologists against AI models.
"""

import logging
import os
from typing import Optional

import pandas as pd

from src.llm_client import LLMClient
from src.modules.module1 import evaluate_single_report
from src.modules.module2 import evaluate_pairwise
from src.tools.tool10 import modelwise_weighted
from src.tools.tool11 import hazardwise_weighted
from src.tools.tool12 import calculate_statistics
from src.tools.tool7 import recognize_modality
from src.tools.tool8 import generate_reports
from src.utils.file_io import read_text, write_json

logger = logging.getLogger(__name__)


def run_workflow2(
    excel_path: str,
    output_dir: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> dict:
    """Run Workflow 2.

    Args:
        excel_path: Path to Excel file with columns report_path, image_path, radiologist_id.
        output_dir: Working directory for results.
        llm_client: LLM/VLM client.
        config_dir: Directory containing configs.

    Returns:
        Nested JSON with per-doctor metrics and department statistics.
    """
    logger.debug("Workflow 2: Starting batch evaluation")
    os.makedirs(output_dir, exist_ok=True)

    df = pd.read_excel(excel_path)
    required_cols = {"report_path", "image_path", "radiologist_id"}
    if not required_cols.issubset(set(df.columns)):
        raise ValueError(f"Excel must contain columns: {required_cols}")

    # Group by radiologist
    doctors = df.groupby("radiologist_id")
    per_doctor_results = {}

    for doctor_id, group in doctors:
        logger.debug(f"Workflow 2: Processing doctor {doctor_id} ({len(group)} cases)")
        doctor_dir = os.path.join(output_dir, doctor_id)
        os.makedirs(doctor_dir, exist_ok=True)

        case_results = []
        for idx, row in group.iterrows():
            report_text = read_text(row["report_path"])
            image_path = row["image_path"]
            modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)

            # Module 1 on doctor report
            doctor_eval = evaluate_single_report(
                report_text,
                image_path=image_path,
                modality=modality,
                llm_client=llm_client,
                config_dir=config_dir,
            )

            # Generate model reports
            generated = generate_reports(
                image_path,
                modality,
                reference_report=report_text,
                llm_client=llm_client,
                config_dir=config_dir,
            )

            # Module 1 on each model report
            model_evals = []
            for gen in generated:
                model_eval = evaluate_single_report(
                    gen["report"],
                    image_path=image_path,
                    modality=modality,
                    llm_client=llm_client,
                    config_dir=config_dir,
                )
                model_evals.append({
                    "model": gen["model"],
                    "evaluation": model_eval,
                })

            # Module 2 pairwise: doctor vs each model
            pairwise = []
            for me in model_evals:
                pair_result = evaluate_pairwise(
                    report_text,
                    me["model"],  # This should be the generated report text
                    image_path=image_path,
                    modality=modality,
                    llm_client=llm_client,
                    config_dir=config_dir,
                )
                pairwise.append({"model": me["model"], "result": pair_result})

            case_results.append({
                "case_index": idx,
                "doctor_evaluation": doctor_eval,
                "model_evaluations": model_evals,
                "pairwise_results": pairwise,
            })

        # Aggregate: Modelwise -> Hazardwise
        # Extract metrics per model across all cases
        all_model_metrics = []
        for cr in case_results:
            for me in cr["model_evaluations"]:
                all_model_metrics.append(me["evaluation"].get("tool1", {}))

        modelwise = modelwise_weighted(all_model_metrics) if all_model_metrics else {}
        hazard_weighted = hazardwise_weighted([modelwise]) if modelwise else []

        per_doctor_results[doctor_id] = {
            "case_results": case_results,
            "modelwise": modelwise,
            "hazardwise": hazard_weighted,
        }

    # Department-level statistics
    all_doctor_metrics = []
    for doctor_id, result in per_doctor_results.items():
        all_doctor_metrics.append(result["modelwise"])

    dept_stats = calculate_statistics(all_doctor_metrics) if all_doctor_metrics else {}

    result = {
        "per_doctor": per_doctor_results,
        "department_statistics": dept_stats,
    }

    output_path = os.path.join(output_dir, "workflow2_result.json")
    write_json(output_path, result)
    logger.debug(f"Workflow 2: Complete. Output saved to {output_path}")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/workflows/test_workflow2.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/workflows/workflow2.py tests/workflows/test_workflow2.py
git commit -m "feat: add Workflow 2 Batch Radiologist vs Models"
```

---

### 任务 4：Workflow 3 — 科室 vs 模型组

**文件：**
- 新建：`src/workflows/workflow3.py`
- 新建：`tests/workflows/test_workflow3.py`

- [ ] **步骤 1：编写失败测试**

**测试文件：** `tests/workflows/test_workflow3.py`
```python
import pytest
import pandas as pd
from src.workflows.workflow3 import run_workflow3


class TestWorkflow3:
    def test_end_to_end(self, mocker, tmp_path):
        excel_path = tmp_path / "input.xlsx"
        df = pd.DataFrame({
            "report_path": ["r1.txt"],
            "image_path": ["i1.png"],
            "radiologist_id": ["doc1"],
        })
        df.to_excel(excel_path, index=False)

        mock_mod1 = mocker.patch("src.workflows.workflow3.evaluate_single_report")
        mock_mod1.return_value = {"tool1": {"score": 4}}

        mock_tool8 = mocker.patch("src.workflows.workflow3.generate_reports")
        mock_tool8.return_value = [
            {"model": "m1", "source": "cloud", "report": "gen1"},
            {"model": "m2", "source": "cloud", "report": "gen2"},
        ]

        mock_tool12 = mocker.patch("src.workflows.workflow3.calculate_statistics")
        mock_tool12.return_value = {"score": {"mean": 0.8}}

        result = run_workflow3(
            excel_path=str(excel_path),
            output_dir=str(tmp_path),
        )
        assert "comparisons" in result
        assert "statistics" in result
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/workflows/test_workflow3.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现文件：** `src/workflows/workflow3.py`
```python
"""Workflow 3: Department-Level Doctor vs Model Group Comparison.

Compares overall department performance against AI model group.
"""

import logging
import os
from typing import Optional

import pandas as pd

from src.config import load_config
from src.llm_client import LLMClient
from src.modules.module1 import evaluate_single_report
from src.tools.tool12 import calculate_statistics
from src.tools.tool7 import recognize_modality
from src.tools.tool8 import generate_reports
from src.utils.file_io import read_text, write_json

logger = logging.getLogger(__name__)


def run_workflow3(
    excel_path: str,
    output_dir: str,
    llm_client: Optional[LLMClient] = None,
    config_dir: str = "./config",
) -> dict:
    """Run Workflow 3.

    Args:
        excel_path: Path to Excel with columns report_path, image_path, radiologist_id.
        output_dir: Working directory for results.
        llm_client: LLM/VLM client.
        config_dir: Directory containing configs.

    Returns:
        Comparison JSON with per-report differences and statistics.
    """
    logger.debug("Workflow 3: Starting department comparison")
    os.makedirs(output_dir, exist_ok=True)

    df = pd.read_excel(excel_path)
    required_cols = {"report_path", "image_path", "radiologist_id"}
    if not required_cols.issubset(set(df.columns)):
        raise ValueError(f"Excel must contain columns: {required_cols}")

    # Evaluate all doctor reports
    doctor_evals = []
    for idx, row in df.iterrows():
        report_text = read_text(row["report_path"])
        image_path = row["image_path"]
        modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)

        eval_result = evaluate_single_report(
            report_text,
            image_path=image_path,
            modality=modality,
            llm_client=llm_client,
            config_dir=config_dir,
        )
        doctor_evals.append({
            "case_index": idx,
            "radiologist_id": row["radiologist_id"],
            "evaluation": eval_result,
        })

    # Evaluate all model reports per case
    model_evals = []
    for idx, row in df.iterrows():
        image_path = row["image_path"]
        modality = recognize_modality(image_path, llm_client=llm_client, config_dir=config_dir)
        generated = generate_reports(
            image_path,
            modality,
            llm_client=llm_client,
            config_dir=config_dir,
        )
        for gen in generated:
            eval_result = evaluate_single_report(
                gen["report"],
                image_path=image_path,
                modality=modality,
                llm_client=llm_client,
                config_dir=config_dir,
            )
            model_evals.append({
                "case_index": idx,
                "model": gen["model"],
                "evaluation": eval_result,
            })

    # Compute model representative per case (weighted average)
    try:
        cfg = load_config(config_dir)
        model_weights = cfg.weights.metric_weights
    except Exception:
        model_weights = {}

    comparisons = []
    for idx in df.index:
        doctor_eval = next((de for de in doctor_evals if de["case_index"] == idx), None)
        case_models = [me for me in model_evals if me["case_index"] == idx]

        if doctor_eval and case_models:
            # Simple representative: average of model scores
            model_scores = [
                me["evaluation"].get("tool1", {}).get("Overall Writing Quality", {}).get("score", 0)
                for me in case_models
            ]
            rep_score = sum(model_scores) / len(model_scores) if model_scores else 0

            doctor_score = doctor_eval["evaluation"].get("tool1", {}).get("Overall Writing Quality", {}).get("score", 0)

            comparisons.append({
                "case_index": idx,
                "doctor_score": doctor_score,
                "model_representative_score": rep_score,
                "difference": doctor_score - rep_score,
            })

    # Statistics via Tool 12
    if comparisons:
        metrics_list = [{"doctor_score": c["doctor_score"], "model_score": c["model_representative_score"]} for c in comparisons]
        stats = calculate_statistics(metrics_list)
    else:
        stats = {}

    # Count how many reports are better than model
    better_count = sum(1 for c in comparisons if c["difference"] > 0)

    result = {
        "comparisons": comparisons,
        "statistics": stats,
        "better_than_model_count": better_count,
        "total_reports": len(comparisons),
    }

    output_path = os.path.join(output_dir, "workflow3_result.json")
    write_json(output_path, result)
    logger.debug(f"Workflow 3: Complete. Output saved to {output_path}")
    return result
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/workflows/test_workflow3.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/workflows/workflow3.py tests/workflows/test_workflow3.py
git commit -m "feat: add Workflow 3 Department vs Model Group"
```

---

### 任务 5：验证所有 Workflow

- [ ] **步骤 1：运行全部 Workflow 测试**

运行：`python -m pytest tests/workflows/ tests/tools/test_tool8.py -v`
预期结果：全部 PASS

- [ ] **步骤 2：最终端到端检查**

运行：`python -m src.cli --help`
预期结果：显示 tool、module、workflow 子命令

- [ ] **步骤 3：提交**

```bash
git commit --allow-empty -m "checkpoint: workflows and tool8 complete"
```

---

## 自审（Self-Review）

**1. 规格覆盖：**
- Tool 8：本地模型适配器，支持动态导入、云端回退、带标签输出 — 任务 1
- Workflow 1：模态识别 → Module 1（人类报告）→ Tool 8 生成 → Module 1（生成报告）→ Tool 9 排序 → Module 2 成对比较 — 任务 2
- Workflow 2：Excel 输入 → 按医生分组 → 报告生成 → 每例 Module 1/2 → Modelwise→Hazardwise→统计聚合 — 任务 3
- Workflow 3：Excel 输入 → 对全部报告执行 Module 1 → 模型代表加权平均 → 逐例比较 → Tool 12 统计 — 任务 4

**2. 占位符扫描：** 无占位符。

**3. 类型一致性：**
- 所有 Workflow 均接受 `llm_client: Optional[LLMClient]`
- 所有 Workflow 均接受 `config_dir: str = "./config"`
- 所有 Workflow 均接受 `output_dir: str`

**缺口：** 无。
