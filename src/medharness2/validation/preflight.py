from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config, resolve_existing_path
from medharness2.utils.io import write_json


def run_sample_preflight(
    sample_root: str | Path,
    output_path: str | Path,
    *,
    config: AppConfig | None = None,
    require_real_ocr: bool = False,
    limit: int | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    warnings: list[str] = []

    root = Path(sample_root)
    if not root.exists():
        raise FileNotFoundError(f"sample root does not exist: {root}")

    from medharness2.workflows.sample_full import plan_sample_full_routes

    route_dir = out.parent / f"{out.stem}_route_plan"
    route = plan_sample_full_routes(
        root,
        route_dir,
        config=cfg,
        limit=limit,
        model_keys=model_keys,
        model_sources=model_sources,
    )
    cases = list(route.get("cases") or [])
    if not cases:
        blockers.append("no_cases_discovered")
    fallback_count = int(route.get("summary", {}).get("cases_requiring_fallback", 0) or 0)
    if fallback_count:
        warnings.append("cases_require_generation_fallback")
        if not cfg.generator.cloud_fallback_enabled:
            blockers.append("fallback_cases_but_cloud_fallback_disabled")

    ocr = _check_ocr_provider(cfg)
    if require_real_ocr:
        if str(ocr.get("provider") or "").lower() == "mock":
            blockers.append("real_ocr_required_but_provider_is_mock")
        elif ocr.get("status") != "ready":
            blockers.append(str(ocr.get("blocker") or "real_ocr_provider_unavailable"))
    elif ocr.get("status") != "ready":
        warnings.append(
            f"ocr_not_ready:{ocr.get('blocker') or ocr.get('status') or 'unknown'}"
        )

    result = {
        "passed": not blockers,
        "sample_root": str(root),
        "sample": {
            "case_count": len(cases),
            "modality_counts": dict(sorted(Counter(case.get("modality") for case in cases).items())),
            "body_part_counts": dict(sorted(Counter(case.get("body_part") for case in cases).items())),
        },
        "routing": dict(route.get("summary") or {}),
        "ocr": ocr,
        "require_real_ocr": require_real_ocr,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "paths": {
            "preflight": str(out),
            "route_plan": str(route.get("paths", {}).get("route_plan") or route_dir / "route_plan.json"),
        },
    }
    write_json(out, result)
    return result


def _check_ocr_provider(config: AppConfig) -> dict[str, Any]:
    route = config.model_roles.get("ocr_primary")
    provider = str(route.provider if route and route.provider else config.llm.provider).lower()
    model = str(route.model if route and route.model else config.llm.model)
    api_key_env = str(route.api_key_env if route and route.api_key_env else config.llm.api_key_env)
    if provider == "mock":
        return {
            "provider": provider,
            "model": model,
            "status": "mock",
            "blocker": "real_ocr_required_but_provider_is_mock",
            "real_ocr_capable": False,
        }
    if provider in {
        "openai",
        "openai_responses",
        "chat_completions",
        "openai_chat",
        "codex_proxy",
        "codex",
    }:
        key_set = bool(os.environ.get(api_key_env))
        return {
            "provider": provider,
            "model": model,
            "status": "ready" if key_set else "missing_api_key",
            "blocker": None if key_set else "missing_llm_api_key",
            "api_key_env": api_key_env,
            "api_key_set": key_set,
            "real_ocr_capable": key_set,
        }
    if provider in {"local_vlm_cli", "medharness_cli_vlm"}:
        dry_run = _run_local_vlm_dry_run(config, model=model)
        status = str(dry_run.get("status") or "")
        ready = status in {"ready", "debug_ready"}
        return {
            "provider": provider,
            "model": model,
            "status": "ready" if ready else "unavailable",
            "blocker": None if ready else "local_vlm_cli_model_unavailable",
            "dry_run": dry_run,
            "real_ocr_capable": ready,
        }
    if provider in {"local_hf_vlm", "hf_vlm_local"}:
        dry_run = _check_local_hf_vlm_files(config, model=model)
        ready = dry_run["status"] == "ready"
        return {
            "provider": provider,
            "model": model,
            "status": "ready" if ready else "unavailable",
            "blocker": None if ready else "local_hf_vlm_model_unavailable",
            "dry_run": dry_run,
            "real_ocr_capable": ready,
        }
    return {
        "provider": provider,
        "model": model,
        "status": "unsupported",
        "blocker": "unsupported_llm_provider_for_ocr",
        "real_ocr_capable": False,
    }


def _run_local_vlm_dry_run(config: AppConfig, *, model: str | None = None) -> dict[str, Any]:
    script = resolve_existing_path(config.llm.local_cli_script)
    if not script.exists():
        return {
            "status": "script_missing",
            "missing_paths": [str(script)],
        }
    cmd = [
        config.llm.local_cli_python_bin,
        str(script),
        "--config",
        str(resolve_existing_path(config.llm.local_cli_config_path)),
        "--model-key",
        model or config.llm.model,
        "--dry-run",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=config.llm.local_cli_timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {"status": "dry_run_timeout"}
    except Exception as exc:
        return {"status": "dry_run_failed", "error": f"{type(exc).__name__}: {exc}"}
    parsed = _parse_json_object(completed.stdout)
    if not parsed:
        parsed = {
            "status": "dry_run_unparseable",
            "stdout_tail": completed.stdout[-1000:],
        }
    parsed["returncode"] = completed.returncode
    if completed.stderr:
        parsed["stderr_tail"] = completed.stderr[-1000:]
    return parsed


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _check_local_hf_vlm_files(config: AppConfig, *, model: str | None = None) -> dict[str, Any]:
    model_path = Path(config.llm.local_hf_model_path)
    required = [
        model_path / "config.json",
        model_path / "tokenizer_config.json",
        model_path / "preprocessor_config.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    weight_patterns = ["model*.safetensors", "pytorch_model*.bin", "*.safetensors.index.json"]
    has_weights = any(next(model_path.glob(pattern), None) is not None for pattern in weight_patterns) if model_path.exists() else False
    if not has_weights:
        missing.append(str(model_path / "model*.safetensors"))
    return {
        "status": "ready" if not missing else "asset_missing",
        "model_path": str(model_path),
        "model": model or config.llm.model,
        "missing_paths": missing,
    }
