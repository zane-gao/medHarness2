from __future__ import annotations

import json
from pathlib import Path

from medharness2.config import AppConfig, ModelRoleConfig
from medharness2.validation.live_smoke import run_live_judge_smoke


def test_live_smoke_is_blocked_without_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SMOKE_KEY", raising=False)
    cfg = AppConfig(model_roles={"general_judge": ModelRoleConfig(api_key_env="SMOKE_KEY")})
    result = run_live_judge_smoke(tmp_path / "smoke.json", config=cfg)
    assert result["status"] == "blocked"
    assert json.loads((tmp_path / "smoke.json").read_text())["reason"] == "missing_api_key"


def test_live_smoke_validates_synthetic_json(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SMOKE_KEY", "test-only")
    cfg = AppConfig(
        model_roles={
            "general_judge": ModelRoleConfig(
                provider="chat_completions",
                model="smoke-model",
                api_key_env="SMOKE_KEY",
                base_url="https://smoke.invalid/v1",
            )
        }
    )

    class Client:
        def call(self, *args, **kwargs):
            return '{"status":"ok","echo":"synthetic-live-smoke"}'

    result = run_live_judge_smoke(tmp_path / "smoke.json", config=cfg, client=Client())
    assert result["status"] == "succeeded"
    assert result["response_schema_valid"] is True
    assert result["fallback_used"] is False
