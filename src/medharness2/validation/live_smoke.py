from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.utils.io import parse_json_object, write_json


def run_live_judge_smoke(
    output_path: str | Path,
    *,
    config: AppConfig | None = None,
    role: str = "general_judge",
    client: Any | None = None,
) -> dict[str, Any]:
    cfg = config or load_config("config/dmx_strong.yaml")
    route = cfg.model_roles.get(role)
    if route is None:
        result = {"status": "blocked", "reason": f"missing_role:{role}"}
        write_json(output_path, result)
        return result
    configured_provider = str(route.provider or "").strip().lower()
    provider = configured_provider or str(cfg.llm.provider or "").strip().lower()
    if not route.api_key_env or not str(os.environ.get(route.api_key_env) or "").strip():
        result = {
            "status": "blocked",
            "reason": "missing_api_key",
            "role": role,
            "api_key_env": route.api_key_env,
        }
        write_json(output_path, result)
        return result
    if provider in {"", "mock", "deterministic", "fallback"}:
        result = {
            "status": "blocked",
            "reason": "unsupported_provider_for_live_smoke",
            "role": role,
            "provider": provider or "unknown",
            "model": route.model,
            "fallback_used": False,
        }
        write_json(output_path, result)
        return result
    llm = client or LLMClient(cfg)
    options = route.as_call_options()
    prompt = (
        "Return JSON only: {\"status\":\"ok\",\"echo\":\"synthetic-live-smoke\"}. "
        "This is a connectivity/schema smoke test, not a clinical evaluation."
    )
    started = time.monotonic()
    try:
        raw = llm.call(
            prompt,
            response_format="json",
            payload_classification="synthetic_test",
            **options,
        )
        parsed = parse_json_object(raw, context="live judge smoke")
    except (LLMClientError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "status": "failed",
            "role": role,
            "provider": route.provider,
            "model": route.model,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "fallback_used": False,
        }
        write_json(output_path, result)
        return result
    result = {
        "status": "succeeded" if parsed.get("status") == "ok" else "failed",
        "role": role,
        "provider": route.provider,
        "model": route.model,
        "endpoint_host": route.base_url.split("/")[2] if "://" in route.base_url else "",
        "latency_sec": round(time.monotonic() - started, 4),
        "response_schema_valid": parsed.get("echo") == "synthetic-live-smoke",
        "fallback_used": False,
    }
    if not result["response_schema_valid"]:
        result["status"] = "failed"
        result["reason"] = "unexpected_smoke_payload"
    write_json(output_path, result)
    return result
