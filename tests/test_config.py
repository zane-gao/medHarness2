from __future__ import annotations

from pathlib import Path

from medharness2.config import load_config, resolve_existing_path, resolve_project_path


def test_loads_default_config():
    cfg = load_config()
    assert cfg.llm.provider == "mock"
    assert cfg.llm.model == "gpt-5.5"
    assert cfg.ranking.top_n == 3


def test_loads_override_config(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "default.yaml"
    config_path.write_text("llm:\n  provider: openai\n  model: gpt-test\nranking:\n  top_n: 2\n", encoding="utf-8")
    cfg = load_config(config_path)
    assert cfg.llm.provider == "openai"
    assert cfg.llm.model == "gpt-test"
    assert cfg.ranking.top_n == 2


def test_loads_model_role_routes_without_secrets(tmp_path: Path):
    config_path = tmp_path / "dmx.yaml"
    config_path.write_text(
        """
model_roles:
  hazard_primary:
    provider: chat_completions
    model: gpt-5.5
    api_key_env: DMX_API_KEY
    base_url: https://www.DMXAPI.cn/v1
    max_retries: 4
    timeout_sec: 120
  hazard_reviewer:
    provider: chat_completions
    model: claude-opus-4-8
    api_key_env: DMX_API_KEY
    base_url: https://www.DMXAPI.cn/v1
    temperature: 0.0
    seed: 0
""",
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.model_roles["hazard_primary"].model == "gpt-5.5"
    assert cfg.model_roles["hazard_primary"].max_retries == 4
    assert cfg.model_roles["hazard_primary"].timeout_sec == 120
    assert cfg.model_roles["hazard_reviewer"].model == "claude-opus-4-8"
    assert cfg.model_roles["hazard_reviewer"].omit_temperature is False
    assert cfg.model_roles["hazard_reviewer"].temperature == 0.0
    assert cfg.model_roles["hazard_reviewer"].seed == 0
    assert cfg.model_roles["hazard_reviewer"].as_call_options()["temperature"] == 0.0
    assert cfg.model_roles["hazard_reviewer"].seed == 0
    assert cfg.model_roles["hazard_primary"].api_key_env == "DMX_API_KEY"


def test_model_role_separates_schema_attempts_from_transport_retries(tmp_path: Path):
    config_path = tmp_path / "retries.yaml"
    config_path.write_text(
        """
model_roles:
  hazard_primary:
    provider: chat_completions
    model: gpt-5.6-terra
    schema_max_attempts: 3
    transport_max_retries: 2
""",
        encoding="utf-8",
    )

    role = load_config(config_path).model_roles["hazard_primary"]

    assert role.schema_attempts(default=7) == 3
    assert role.as_call_options()["max_retries"] == 2


def test_resolve_project_path():
    cfg = load_config()
    resolved = resolve_project_path(cfg, "config/default.yaml")
    assert resolved.name == "default.yaml"
    assert resolved.is_absolute()


def test_dmx_strong_profile_routes_every_llm_backed_tool_to_verified_strong_models():
    cfg = load_config(Path("config/dmx_strong.yaml"))

    assert cfg.llm.retry_initial_sec == 5.0
    assert cfg.llm.provider == "chat_completions"
    assert cfg.llm.api_key_env == "DMX_API_KEY"
    assert set(cfg.model_roles) >= {
        "ocr_primary",
        "ocr_verifier",
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "hazard_reviewer",
        "structure_auditor",
        "education",
    }
    for role in {
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "structure_auditor",
        "education",
    }:
        assert cfg.model_roles[role].provider == "chat_completions"
        assert cfg.model_roles[role].model == "gpt-5.6-terra"
        assert cfg.model_roles[role].api_key_env == "DMX_API_KEY"
    assert cfg.model_roles["finding_extractor"].max_tokens == 2048
    assert cfg.model_roles["ocr_primary"].model == "doubao-seed-2-1-pro-260628"
    assert cfg.model_roles["ocr_verifier"].model == "qwen-vl-ocr-latest"
    assert cfg.model_roles["hazard_reviewer"].model == "claude-opus-4-8"
    assert cfg.model_roles["hazard_reviewer"].omit_temperature is False
    assert cfg.model_roles["hazard_reviewer"].temperature == 0.0
    assert cfg.model_roles["hazard_reviewer"].seed == 0
    assert cfg.privacy.enforce_external is False
    assert cfg.generator.cloud_fallback_enabled is False


def test_yunwu_profile_is_an_explicit_nonautomatic_backup():
    cfg = load_config(Path("config/yunwu_strong.yaml"))

    assert cfg.model_roles["general_judge"].base_url == "https://yunwu.ai/v1"
    assert cfg.model_roles["general_judge"].api_key_env == "YUNWU_API_KEY"
    assert cfg.model_roles["general_judge"].model == "gpt-5.6-terra"
    assert cfg.model_roles["hazard_reviewer"].model == "claude-opus-4-8"


def test_codex_proxy_profile_uses_separate_gpt_and_claude_credentials():
    cfg = load_config(Path("config/codex_proxy_strong.yaml"))

    assert set(cfg.model_roles) >= {
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "hazard_reviewer",
        "structure_auditor",
        "education",
    }
    for role in {
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "structure_auditor",
        "education",
    }:
        route = cfg.model_roles[role]
        assert route.base_url == "https://codex.0u0o.com/v1"
        assert route.model == "gpt-5.6-terra"
        assert route.api_key_env == "CODEX_PROXY_GPT_API_KEY"
    reviewer = cfg.model_roles["hazard_reviewer"]
    assert reviewer.base_url == "https://codex.0u0o.com/v1"
    assert reviewer.model == "claude-opus-4-8"
    assert reviewer.api_key_env == "CODEX_PROXY_CLAUDE_API_KEY"
    assert reviewer.omit_temperature is False
    assert reviewer.temperature == 0.0
    assert reviewer.seed == 0


def test_codex_dmx_hybrid_profile_routes_only_reviewer_through_dmx():
    cfg = load_config(Path("config/codex_dmx_strong.yaml"))

    for role in {
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "structure_auditor",
        "education",
    }:
        route = cfg.model_roles[role]
        assert route.base_url == "https://codex.0u0o.com/v1"
        assert route.model == "gpt-5.6-terra"
        assert route.api_key_env == "CODEX_PROXY_GPT_API_KEY"
    reviewer = cfg.model_roles["hazard_reviewer"]
    assert reviewer.base_url == "https://www.DMXAPI.cn/v1"
    assert reviewer.model == "claude-opus-4-8"
    assert reviewer.api_key_env == "DMX_API_KEY"
    assert reviewer.omit_temperature is False
    assert reviewer.temperature == 0.0
    assert reviewer.seed == 0


def test_codex_yunwu_hybrid_profile_uses_independent_working_reviewer_route():
    cfg = load_config(Path("config/codex_yunwu_strong.yaml"))

    for role in {
        "general_judge",
        "finding_extractor",
        "alignment_auditor",
        "hazard_primary",
        "structure_auditor",
        "education",
    }:
        route = cfg.model_roles[role]
        assert route.base_url == "https://codex.0u0o.com/v1"
        assert route.model == "gpt-5.6-terra"
        assert route.api_key_env == "CODEX_PROXY_GPT_API_KEY"
    reviewer = cfg.model_roles["hazard_reviewer"]
    assert reviewer.base_url == "https://yunwu.ai/v1"
    assert reviewer.model == "claude-opus-4-8"
    assert reviewer.api_key_env == "YUNWU_API_KEY"
    assert reviewer.omit_temperature is False
    assert reviewer.temperature == 0.0
    assert reviewer.seed == 0
    adjudicator = cfg.model_roles["hazard_adjudicator"]
    assert adjudicator.base_url == "https://yunwu.ai/v1"
    assert adjudicator.model == "gpt-5.6-terra-ultra"
    assert adjudicator.api_key_env == "YUNWU_API_KEY"


def test_yunwu_codex_profile_routes_by_verified_workload_strength():
    cfg = load_config(Path("config/yunwu_codex_strong.yaml"))

    for role in {"general_judge", "finding_extractor", "education"}:
        route = cfg.model_roles[role]
        assert route.base_url == "https://yunwu.ai/v1"
        assert route.model == "gpt-5.6-terra"
        assert route.api_key_env == "YUNWU_API_KEY"
    for role in {"alignment_auditor", "hazard_primary", "structure_auditor"}:
        route = cfg.model_roles[role]
        assert route.base_url == "https://codex.0u0o.com/v1"
        assert route.model == "gpt-5.6-terra"
        assert route.api_key_env == "CODEX_PROXY_GPT_API_KEY"
    reviewer = cfg.model_roles["hazard_reviewer"]
    assert reviewer.base_url == "https://yunwu.ai/v1"
    assert reviewer.model == "claude-opus-4-8"
    assert reviewer.api_key_env == "YUNWU_API_KEY"
    assert reviewer.omit_temperature is False
    assert reviewer.temperature == 0.0
    assert reviewer.seed == 0
    adjudicator = cfg.model_roles["hazard_adjudicator"]
    assert adjudicator.base_url == "https://yunwu.ai/v1"
    assert adjudicator.model == "gpt-5.6-terra-ultra"
    assert adjudicator.api_key_env == "YUNWU_API_KEY"
    for route in cfg.model_roles.values():
        assert route.schema_attempts(default=9) == 2
        assert route.as_call_options()["max_retries"] == 1
        assert route.timeout_sec == 120


def test_codex_triple_profile_uses_distinct_hazard_models():
    cfg = load_config(Path("config/codex_triple_strong.yaml"))

    assert cfg.model_roles["hazard_primary"].model == "gpt-5.6-terra"
    assert cfg.model_roles["hazard_reviewer"].model == "gpt-5.6-sol"
    assert cfg.model_roles["hazard_adjudicator"].model == "gpt-5.6-luna"
    for route in cfg.model_roles.values():
        assert route.base_url == "https://codex.0u0o.com/v1"
        assert route.api_key_env == "CODEX_PROXY_GPT_API_KEY"
        assert route.schema_attempts(default=9) == 2
        assert route.as_call_options()["max_retries"] == 1
        assert route.timeout_sec == 120


def test_resolve_existing_path_falls_back_to_nfsdata_mount_for_legacy_medharness():
    resolved = resolve_existing_path("/data/isbi/gzp/medHarness/configs/reportgen_models.yaml")
    assert resolved == Path("/nfsdata_a40/isbi/gzp/medHarness/configs/reportgen_models.yaml")
    assert resolved.exists()
