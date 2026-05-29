from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class LLMConfig:
    provider: str = "mock"
    model: str = "gpt-5.5"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    timeout_sec: int = 60
    max_retries: int = 3
    retry_initial_sec: float = 0.25
    temperature: float = 0.0


@dataclass
class ExtractorConfig:
    backend: str = "placeholder"
    template_path: str = "config/templates/default_finding_template.json"


@dataclass
class GeneratorConfig:
    cloud_fallback_enabled: bool = True
    default_models: list[str] = field(default_factory=lambda: ["local_readiness_stub"])
    local_models: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RankingConfig:
    top_n: int = 3
    weights: dict[str, float] = field(
        default_factory=lambda: {"likert_mean": 0.4, "structure_score": 0.3, "finding_coverage": 0.3}
    )


@dataclass
class AlignmentConfig:
    tolerance_mm: float = 5.0


@dataclass
class AppConfig:
    project_root: Path = PROJECT_ROOT
    llm: LLMConfig = field(default_factory=LLMConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)
    modality_map: dict[str, str] = field(
        default_factory=lambda: {"DX": "cxr", "CR": "cxr", "XR": "cxr", "CT": "ct", "MR": "mri", "MRI": "mri"}
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "default.yaml"
    if not config_path.exists():
        return AppConfig(project_root=PROJECT_ROOT)
    payload = _read_yaml(config_path)
    root = config_path.parent.parent if config_path.name == "default.yaml" else PROJECT_ROOT
    return AppConfig(
        project_root=root.resolve(),
        llm=LLMConfig(**dict(payload.get("llm") or {})),
        extractor=ExtractorConfig(**dict(payload.get("extractor") or {})),
        generator=GeneratorConfig(**dict(payload.get("generator") or {})),
        ranking=RankingConfig(**dict(payload.get("ranking") or {})),
        alignment=AlignmentConfig(**dict(payload.get("alignment") or {})),
        modality_map=dict(payload.get("modality_map") or AppConfig().modality_map),
    )


def resolve_project_path(config: AppConfig, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (config.project_root / candidate).resolve()


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data
