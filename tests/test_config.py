from __future__ import annotations

from pathlib import Path

from medharness2.config import load_config, resolve_project_path


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


def test_resolve_project_path():
    cfg = load_config()
    resolved = resolve_project_path(cfg, "config/default.yaml")
    assert resolved.name == "default.yaml"
    assert resolved.is_absolute()
