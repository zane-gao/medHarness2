from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MOUNT_FALLBACKS = (
    (Path("/data/isbi/gzp"), Path("/nfsdata_a40/isbi/gzp")),
)


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
    seed: int | None = 0
    chat_max_tokens: int = 1024
    local_cli_python_bin: str = "python"
    local_cli_script: str = "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"
    local_cli_config_path: str = "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"
    local_cli_device: str = "cuda:0"
    local_cli_dtype: str = "bf16"
    local_cli_max_new_tokens: int = 512
    local_cli_timeout_sec: int = 1800
    local_cli_pdf_max_pages: int = 3
    local_hf_model_path: str = ""
    local_hf_device: str = "cuda:0"
    local_hf_dtype: str = "bf16"
    local_hf_max_new_tokens: int = 512
    local_hf_pdf_max_pages: int = 3


@dataclass
class ModelRoleConfig:
    provider: str = ""
    model: str = ""
    api_key_env: str = ""
    base_url: str = ""
    max_retries: int | None = None
    schema_max_attempts: int | None = None
    transport_max_retries: int | None = None
    timeout_sec: int | None = None
    temperature: float | None = None
    seed: int | None = 0
    max_tokens: int | None = None
    omit_temperature: bool = False
    consistency_runs: int = 1

    def schema_attempts(self, *, default: int) -> int:
        configured = (
            self.schema_max_attempts
            if self.schema_max_attempts is not None
            else self.max_retries
        )
        return max(1, int(configured if configured is not None else default))

    def as_call_options(self) -> dict[str, Any]:
        transport_retries = (
            self.transport_max_retries
            if self.transport_max_retries is not None
            else self.max_retries
        )
        options = {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "max_retries": transport_retries,
            "timeout_sec": self.timeout_sec,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
        }
        if self.omit_temperature:
            options["omit_temperature"] = True
        return {key: value for key, value in options.items() if value not in (None, "")}


@dataclass
class PrivacyConfig:
    enforce_external: bool = True
    block_external_images: bool = True
    allowed_external_classifications: list[str] = field(
        default_factory=lambda: ["deidentified_structured", "synthetic_test", "public_nonclinical"]
    )


@dataclass
class ExtractorConfig:
    backend: str = "auto"
    template_path: str = "config/templates/default_finding_template.json"


@dataclass
class GeneratorConfig:
    cloud_fallback_enabled: bool = True
    reference_assisted_generation: bool = False
    default_models: list[str] = field(default_factory=lambda: ["local_readiness_stub"])
    local_models: list[dict[str, Any]] = field(default_factory=list)
    include_legacy_ready_models: bool = True
    legacy_config_path: str = "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"


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
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    model_roles: dict[str, ModelRoleConfig] = field(default_factory=dict)
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
        privacy=PrivacyConfig(**dict(payload.get("privacy") or {})),
        model_roles={
            str(role): ModelRoleConfig(**dict(role_config or {}))
            for role, role_config in dict(payload.get("model_roles") or {}).items()
        },
        modality_map=dict(payload.get("modality_map") or AppConfig().modality_map),
    )


def resolve_project_path(config: AppConfig, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (config.project_root / candidate).resolve()


def resolve_existing_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return candidate
    candidate_text = str(candidate)
    for source_root, target_root in LEGACY_MOUNT_FALLBACKS:
        source_text = str(source_root)
        if candidate_text == source_text or candidate_text.startswith(f"{source_text}/"):
            fallback = Path(f"{target_root}{candidate_text[len(source_text):]}")
            if fallback.exists():
                return fallback
    return candidate


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data
