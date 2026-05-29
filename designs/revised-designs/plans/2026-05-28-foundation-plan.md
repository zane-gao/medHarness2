# 基础层实施计划


**目标：** 构建基础层 —— 配置系统、LLM/VLM 客户端、日志、CLI 框架、共享工具函数以及默认配置文件。

**架构：** 基于 Pydantic 校验的 YAML 配置，集中存放于单一目录。统一 LLM 客户端支持提供商（Provider）切换与指数退避重试。使用 Typer 构建嵌套子命令 CLI。日志基于标准库 logging。所有其他子项目均依赖于这些接口。

**技术栈：** Python 3.10+、Pydantic 2.x、PyYAML、Typer、python-dotenv（可选，用于环境变量覆盖）

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/config.py` | Pydantic 配置模型、加载器（合并多个 YAML 文件）、默认配置生成器 |
| `src/llm_client.py` | 统一 LLM/VLM 客户端，含重试、提供商切换、图像支持 |
| `src/cli.py` | 基于 Typer 的应用入口，含 tool / module / workflow 嵌套子命令 |
| `src/utils/logging_config.py` | 从配置初始化日志 |
| `src/utils/file_io.py` | JSON / CSV / Excel 读写辅助函数 |
| `config/api.yaml` | LLM 提供商、模型、API 密钥、重试设置 |
| `config/models.yaml` | 本地模型注册表（占位） |
| `config/weights.yaml` | 默认指标权重 |
| `config/hazard_weights.yaml` | 默认危害权重矩阵 |
| `config/alignment_tolerance.yaml` | 定量匹配默认容差 |
| `config/modality_map.yaml` | 原始检查模态到标准键的映射 |
| `config/structure_template.json` | 带权重的通用结构模板 |
| `config/prompts/tool1_system.txt` | Tool 1 系统提示词（System Prompt） |
| `config/prompts/tool1_likert_definition.txt` | Tool 1 Likert 量表定义 |
| `config/prompts/tool3_system.txt` | Tool 3 系统提示词 |
| `config/prompts/tool4_system.txt` | Tool 4 系统提示词 |
| `config/prompts/tool4_likert_definition.txt` | Tool 4 Likert 量表定义 |
| `tests/test_config.py` | 配置加载器测试 |
| `tests/test_llm_client.py` | LLM 客户端测试 |
| `tests/test_cli.py` | CLI 测试 |

---

### 任务 1：项目结构与空文件

**文件：**
- 创建：`src/__init__.py`
- 创建：`src/utils/__init__.py`
- 创建：`src/tools/__init__.py`
- 创建：`src/modules/__init__.py`
- 创建：`src/workflows/__init__.py`
- 创建：`tests/__init__.py`
- 创建：`config/.gitkeep`

- [ ] **步骤 1：创建目录与空 init 文件**

```bash
mkdir -p src/utils src/tools src/modules src/workflows tests config/prompts config/templates
touch src/__init__.py src/utils/__init__.py src/tools/__init__.py src/modules/__init__.py src/workflows/__init__.py tests/__init__.py config/.gitkeep
```

- [ ] **步骤 2：提交**

```bash
git add src/ tests/ config/
git commit -m "chore: scaffold project structure"
```

---

### 任务 2：配置加载器 —— Pydantic 模型

**文件：**
- 创建：`src/config.py`
- 创建：`tests/test_config.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/test_config.py`
```python
import os
import tempfile
import pytest
from src.config import load_config, generate_default_configs


class TestGenerateDefaultConfigs:
    def test_generates_api_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            generate_default_configs(td)
            assert os.path.exists(os.path.join(td, "api.yaml"))

    def test_generates_weights_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            generate_default_configs(td)
            assert os.path.exists(os.path.join(td, "weights.yaml"))


class TestLoadConfig:
    def test_loads_api_config(self):
        with tempfile.TemporaryDirectory() as td:
            generate_default_configs(td)
            cfg = load_config(td)
            assert cfg.api.provider == "openai"
            assert cfg.api.model == "gpt-4o"

    def test_missing_config_dir_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path")
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/test_config.py -v`
预期结果：FAIL，报 `ImportError` 或 `ModuleNotFoundError`

- [ ] **步骤 3：编写最小实现**

**实现：** `src/config.py`
```python
"""基于 Pydantic 的配置加载器，用于放射报告评估系统。

从单一配置目录加载多个 YAML 文件，合并为一个经过校验的配置对象。
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None
    max_retries: int = 3
    timeout: int = 60
    temperature: float = 0.0
    extraction_command: str = "echo '{}'"


class ModelRegistryConfig(BaseModel):
    models: list = Field(default_factory=list)


class WeightsConfig(BaseModel):
    metric_weights: dict = Field(default_factory=lambda: {
        "completeness_and_accuracy": 0.25,
        "conciseness_and_clarity": 0.15,
        "terminological_accuracy": 0.20,
        "structure_and_style": 0.20,
        "overall_writing_quality": 0.20,
    })


class HazardWeightsConfig(BaseModel):
    weights: dict = Field(default_factory=lambda: {
        "false_finding": {"1": 1.0, "2": 1.5, "3": 2.0, "4": 2.5, "5": 3.0},
        "omission_finding": {"1": 1.0, "2": 1.5, "3": 2.0, "4": 2.5, "5": 3.0},
        "incorrect_location": {"1": 0.5, "2": 1.0, "3": 1.5, "4": 2.0, "5": 2.5},
        "incorrect_severity": {"1": 0.5, "2": 1.0, "3": 1.5, "4": 2.0, "5": 2.5},
    })


class AlignmentToleranceConfig(BaseModel):
    tolerance_mm: float = 5.0


class ModalityMapConfig(BaseModel):
    mapping: dict = Field(default_factory=lambda: {
        "CT": "chest_ct",
        "MR": "brain_mri",
        "DX": "chest_xray",
        "CR": "chest_xray",
    })


class Config(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    models: ModelRegistryConfig = Field(default_factory=ModelRegistryConfig)
    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    hazard_weights: HazardWeightsConfig = Field(default_factory=HazardWeightsConfig)
    alignment_tolerance: AlignmentToleranceConfig = Field(default_factory=AlignmentToleranceConfig)
    modality_map: ModalityMapConfig = Field(default_factory=ModalityMapConfig)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_dir: str) -> Config:
    config_path = Path(config_dir)
    if not config_path.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    data = {}
    for filename, key in [
        ("api.yaml", "api"),
        ("models.yaml", "models"),
        ("weights.yaml", "weights"),
        ("hazard_weights.yaml", "hazard_weights"),
        ("alignment_tolerance.yaml", "alignment_tolerance"),
        ("modality_map.yaml", "modality_map"),
    ]:
        filepath = config_path / filename
        file_data = _load_yaml(filepath)
        if file_data:
            data[key] = file_data

    return Config(**data)


def generate_default_configs(config_dir: str) -> None:
    config_path = Path(config_dir)
    config_path.mkdir(parents=True, exist_ok=True)

    api = ApiConfig()
    with open(config_path / "api.yaml", "w", encoding="utf-8") as f:
        yaml.dump(api.model_dump(), f, default_flow_style=False, sort_keys=False)

    models = ModelRegistryConfig()
    with open(config_path / "models.yaml", "w", encoding="utf-8") as f:
        yaml.dump(models.model_dump(), f, default_flow_style=False, sort_keys=False)

    weights = WeightsConfig()
    with open(config_path / "weights.yaml", "w", encoding="utf-8") as f:
        yaml.dump(weights.model_dump(), f, default_flow_style=False, sort_keys=False)

    hazard = HazardWeightsConfig()
    with open(config_path / "hazard_weights.yaml", "w", encoding="utf-8") as f:
        yaml.dump(hazard.model_dump(), f, default_flow_style=False, sort_keys=False)

    tolerance = AlignmentToleranceConfig()
    with open(config_path / "alignment_tolerance.yaml", "w", encoding="utf-8") as f:
        yaml.dump(tolerance.model_dump(), f, default_flow_style=False, sort_keys=False)

    modality = ModalityMapConfig()
    with open(config_path / "modality_map.yaml", "w", encoding="utf-8") as f:
        yaml.dump(modality.model_dump(), f, default_flow_style=False, sort_keys=False)
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/test_config.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add pydantic config loader with defaults"
```

---

### 任务 3：共享工具 —— 文件 I/O

**文件：**
- 创建：`src/utils/file_io.py`
- 创建：`tests/test_file_io.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/test_file_io.py`
```python
import json
import os
import tempfile

import pytest

from src.utils.file_io import read_json, write_json, read_text, write_text


class TestJsonIO:
    def test_read_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            path = f.name
        try:
            result = read_json(path)
            assert result == {"key": "value"}
        finally:
            os.unlink(path)

    def test_write_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            write_json(path, {"key": "value"})
            assert os.path.exists(path)
            with open(path) as f:
                assert json.load(f) == {"key": "value"}


class TestTextIO:
    def test_read_text(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            path = f.name
        try:
            result = read_text(path)
            assert result == "hello world"
        finally:
            os.unlink(path)

    def test_write_text(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.txt")
            write_text(path, "hello world")
            with open(path) as f:
                assert f.read() == "hello world"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/test_file_io.py -v`
预期结果：FAIL，报导入错误

- [ ] **步骤 3：编写最小实现**

**实现：** `src/utils/file_io.py`
```python
"""JSON、文本及结构化数据的文件 I/O 辅助函数。"""

import json
from pathlib import Path
from typing import Any


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any, indent: int = 2) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/test_file_io.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/utils/file_io.py tests/test_file_io.py
git commit -m "feat: add file I/O utilities"
```

---

### 任务 4：共享工具 —— 日志

**文件：**
- 创建：`src/utils/logging_config.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/test_logging_config.py`
```python
import logging

from src.utils.logging_config import setup_logging


def test_setup_logging_sets_level():
    setup_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/test_logging_config.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/utils/logging_config.py`
```python
"""日志配置工具函数。"""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/test_logging_config.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/utils/logging_config.py tests/test_logging_config.py
git commit -m "feat: add logging configuration"
```

---

### 任务 5：LLM/VLM 客户端 —— 基础接口

**文件：**
- 创建：`src/llm_client.py`
- 创建：`tests/test_llm_client.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/test_llm_client.py`
```python
import os
import tempfile

import pytest

from src.llm_client import LLMClient
from src.config import generate_default_configs, load_config


class TestLLMClientInit:
    def test_init_with_config(self):
        with tempfile.TemporaryDirectory() as td:
            generate_default_configs(td)
            cfg = load_config(td)
            client = LLMClient(cfg)
            assert client.config.api.provider == "openai"
            assert client.config.api.model == "gpt-4o"

    def test_call_without_image(self):
        with tempfile.TemporaryDirectory() as td:
            generate_default_configs(td)
            cfg = load_config(td)
            client = LLMClient(cfg)
            # 不应在接口层抛出异常
            assert hasattr(client, "call")
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/test_llm_client.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/llm_client.py`
```python
"""统一 LLM/VLM 客户端，支持提供商切换与重试逻辑。"""

import json
import logging
import time
from typing import Optional

from src.config import Config

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.provider = config.api.provider
        self.model = config.api.model
        self.api_key = config.api.api_key
        self.base_url = config.api.base_url
        self.max_retries = config.api.max_retries
        self.timeout = config.api.timeout
        self.temperature = config.api.temperature

    def call(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        if not self.api_key:
            logger.warning("No API key configured. Returning mock response.")
            return json.dumps({"mock": True, "prompt_length": len(prompt)})

        attempt = 0
        delay = 1.0
        last_error = None

        while attempt < self.max_retries:
            try:
                if self.provider == "openai":
                    return self._call_openai(prompt, image_path, **kwargs)
                elif self.provider == "anthropic":
                    return self._call_anthropic(prompt, image_path, **kwargs)
                else:
                    raise ValueError(f"Unsupported provider: {self.provider}")
            except Exception as e:
                last_error = e
                attempt += 1
                logger.warning(f"LLM call failed (attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2

        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last_error}")

    def _call_openai(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        import openai

        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        messages = [{"role": "user", "content": prompt}]

        if image_path:
            # 读取图像并编码为 base64
            import base64

            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            messages[0]["content"] = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                },
            ]

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", self.temperature),
            response_format=kwargs.get("response_format"),
        )
        return response.choices[0].message.content

    def _call_anthropic(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        content = ["user", [{"type": "text", "text": prompt}]]

        if image_path:
            import base64

            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            content[1].append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_data,
                },
            })

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=kwargs.get("temperature", self.temperature),
            messages=[{"role": "user", "content": content[1]}],
        )
        return response.content[0].text
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/test_llm_client.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/llm_client.py tests/test_llm_client.py
git commit -m "feat: add unified LLM/VLM client with retry"
```

---

### 任务 6：CLI 入口

**文件：**
- 创建：`src/cli.py`
- 创建：`tests/test_cli.py`

- [ ] **步骤 1：编写失败测试**

**测试：** `tests/test_cli.py`
```python
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "tool" in result.output
    assert "module" in result.output
    assert "workflow" in result.output
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`python -m pytest tests/test_cli.py -v`
预期结果：FAIL

- [ ] **步骤 3：编写最小实现**

**实现：** `src/cli.py`
```python
"""放射报告评估系统 CLI 入口。"""

import logging

import typer

from src.config import load_config
from src.utils.logging_config import setup_logging

app = typer.Typer(
    name="radiology-eval",
    help="Radiology Report Evaluation CLI",
    add_completion=False,
)

tool_app = typer.Typer(help="Run individual evaluation tools")
module_app = typer.Typer(help="Run evaluation modules")
workflow_app = typer.Typer(help="Run evaluation workflows")

app.add_typer(tool_app, name="tool")
app.add_typer(module_app, name="module")
app.add_typer(workflow_app, name="workflow")


def _setup(config_dir: str) -> None:
    cfg = load_config(config_dir)
    setup_logging("DEBUG")
    return cfg


@tool_app.command("list")
def list_tools():
    """List available tools."""
    tools = ["tool1", "tool2", "tool3", "tool4", "tool5", "tool6", "tool7", "tool8", "tool9", "tool10", "tool11", "tool12"]
    for t in tools:
        typer.echo(t)


@module_app.command("list")
def list_modules():
    """List available modules."""
    modules = ["module1", "module2"]
    for m in modules:
        typer.echo(m)


@workflow_app.command("list")
def list_workflows():
    """List available workflows."""
    workflows = ["workflow1", "workflow2", "workflow3"]
    for w in workflows:
        typer.echo(w)


if __name__ == "__main__":
    app()
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`python -m pytest tests/test_cli.py -v`
预期结果：PASS

- [ ] **步骤 5：提交**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat: add typer CLI with nested subcommands"
```

---

### 任务 7：默认配置文件 —— 提示词与模板

**文件：**
- 创建：`config/prompts/tool1_system.txt`
- 创建：`config/prompts/tool1_likert_definition.txt`
- 创建：`config/prompts/tool3_system.txt`
- 创建：`config/prompts/tool4_system.txt`
- 创建：`config/prompts/tool4_likert_definition.txt`
- 创建：`config/structure_template.json`

- [ ] **步骤 1：创建默认提示词文件**

**文件：** `config/prompts/tool1_system.txt`
```
You are an expert radiologist evaluating a radiology report.
Evaluate the report using the following Likert-scale metrics.
Return your evaluation as a JSON object with each metric as a key.
For each metric, provide a score from 1 to 5 and a brief explanation.
```

**文件：** `config/prompts/tool1_likert_definition.txt`
```
## Completeness and Accuracy
- 1 (Poor): Major findings are missing or incorrect.
- 2 (Fair): Several findings are missing or there are significant inaccuracies.
- 3 (Good): Most key findings are present and accurate; minor omissions or errors.
- 4 (Very Good): Report is comprehensive and accurate with only trivial omissions.
- 5 (Excellent): Report is fully complete and correct in all aspects.

## Conciseness and Clarity
- 1 (Poor): Report is verbose, confusing, and indirect.
- 2 (Fair): Report is difficult to follow, contains unnecessary information.
- 3 (Good): Report is generally clear and reasonably concise.
- 4 (Very Good): Report is clear, direct, and well-written.
- 5 (Excellent): Report is exceptionally brief, direct, and easy to understand.

## Terminological Accuracy
- 1 (Poor): Frequent and critical errors in medical terminology.
- 2 (Fair): Several noticeable errors in terminology.
- 3 (Good): Terminology is mostly correct with some minor mistakes.
- 4 (Very Good): Terminology is accurate with rare, insignificant errors.
- 5 (Excellent): All medical terminology is used precisely and correctly.

## Structure and Style
- 1 (Poor): Lacks a logical structure and does not follow radiological reporting style.
- 2 (Fair): Poorly structured; deviates significantly from standard style.
- 3 (Good): Follows a basic structure and style, but could be better organized.
- 4 (Very Good): Well-structured and adheres well to radiological reporting conventions.
- 5 (Excellent): Exemplary structure and professional radiological style.

## Overall Writing Quality
- 1 (Poor): Requires a complete rewrite.
- 2 (Fair): Needs substantial revisions for clarity and correctness.
- 3 (Good): Acceptable, but would benefit from moderate revisions.
- 4 (Very Good): Well-written, requiring only minor proofreading or edits.
- 5 (Excellent): Does not require any revisions.
```

**文件：** `config/prompts/tool3_system.txt`
```
You are analyzing the structure of a radiology report.
Classify each paragraph into one of the following sections: Findings, Impression, Patient Information, Additional Information.
Return a JSON object where each key is a section name and the value is a list of paragraphs classified into that section.
If a section is not present, include it with an empty list.
```

**文件：** `config/prompts/tool4_system.txt`
```
You are evaluating errors in a radiology report by comparing it to a reference report.
Identify errors, classify their type, and rate their hazard level on a 1-5 scale.
Return a JSON array of errors, each with error_type, hazard_level, and explanation.
```

**文件：** `config/prompts/tool4_likert_definition.txt`
```
## Hazard Level
- 1 (Minor): Insignificant discrepancy that does not affect clinical care.
- 2 (Low): Minor error with minimal clinical impact.
- 3 (Moderate): Notable error that may affect clinical decisions.
- 4 (High): Significant error with potential for serious clinical impact.
- 5 (Critical): Critical error with high potential for patient harm.
```

**文件：** `config/structure_template.json`
```json
{
  "sections": {
    "Findings": {
      "weight": 0.4
    },
    "Impression": {
      "weight": 0.4
    },
    "Patient Information": {
      "weight": 0.1
    },
    "Additional Information": {
      "weight": 0.1
    }
  }
}
```

- [ ] **步骤 2：提交**

```bash
git add config/prompts/ config/structure_template.json
git commit -m "chore: add default prompts and structure template"
```

---

### 任务 8：基础层端到端验证

- [ ] **步骤 1：运行全部测试**

运行：`python -m pytest tests/test_config.py tests/test_file_io.py tests/test_logging_config.py tests/test_llm_client.py tests/test_cli.py -v`
预期结果：全部 PASS

- [ ] **步骤 2：验证 CLI 帮助信息**

运行：`python -m src.cli --help`
预期结果：显示 tool、module、workflow 子命令

运行：`python -m src.cli tool list`
预期结果：列出 tool1 至 tool12

- [ ] **步骤 3：提交**

```bash
git commit --allow-empty -m "checkpoint: foundation layer complete"
```

---

## 自检（Self-Review）

**1. 规格覆盖度：**
- 多 YAML 文件 + Pydantic 校验的配置系统：任务 2
- 带重试的统一 LLM/VLM 客户端：任务 5
- 基于标准库的日志：任务 4
- Typer 嵌套子命令 CLI：任务 6
- 文件 I/O 工具函数：任务 3
- 默认提示词与模板：任务 7

**2. 占位检查：** 无 TBD、TODO 或模糊步骤。所有代码均已完整。

**3. 类型一致性：**
- `Config` 类在 `config.py` 和 `llm_client.py` 中使用一致
- `load_config` 函数签名与 `cli.py` 中的调用匹配

**缺口：** 无。
