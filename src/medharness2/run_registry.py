from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from medharness2.utils.io import read_json, write_json


SECRET_MARKERS = ("key", "token", "secret", "password", "pat")


def record_run(
    root: str | Path,
    *,
    run_id: str,
    command: list[str] | None = None,
    stage: str,
    status: str,
    config: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> Path:
    run_dir = Path(root) / run_id
    return record_registry_entry(
        run_dir,
        run_id=run_id,
        command=command,
        stage=stage,
        status=status,
        config=config,
        inputs=inputs,
        outputs=outputs,
        metrics=metrics,
        warnings=warnings,
    )


def record_registry_entry(
    registry_dir: str | Path,
    *,
    run_id: str | None = None,
    command: list[str] | None = None,
    stage: str,
    status: str,
    config: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> Path:
    run_dir = Path(registry_dir)
    resolved_run_id = run_id or run_dir.name
    _require_string("run_id", resolved_run_id)
    _require_string("stage", stage)
    _require_string("status", status)
    command_value = _require_string_list("command", command)
    config_value = _require_mapping("config", config)
    inputs_value = _require_mapping("inputs", inputs)
    outputs_value = _require_mapping("outputs", outputs)
    metrics_value = _require_mapping("metrics", metrics)
    warnings_value = _require_string_list("warnings", warnings)
    entry = {
        "run_id": resolved_run_id,
        "stage": stage,
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": _redact(command_value),
        "config": _redact(config_value),
        "inputs": _redact(inputs_value),
        "outputs": _redact(outputs_value),
        "metrics": metrics_value,
        "warnings": warnings_value,
    }
    path = run_dir / "run_registry.json"
    previous_entries = _existing_entries(path)
    entries = [*previous_entries, entry]
    payload = {
        "schema_version": "1.0",
        **entry,
        "entry_count": len(entries),
        "entries": entries,
    }
    write_json(path, payload)
    return path


def _existing_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if _valid_entry(entry)]
    if payload.get("stage"):
        return [
            {
                "run_id": payload.get("run_id") or path.parent.name,
                "stage": payload.get("stage"),
                "status": payload.get("status") or "unknown",
                "created_at_utc": payload.get("created_at_utc") or "",
                "command": payload.get("command") or [],
                "config": payload.get("config") or {},
                "inputs": payload.get("inputs") or {},
                "outputs": payload.get("outputs") or {},
                "metrics": payload.get("metrics") or {},
                "warnings": payload.get("warnings") or [],
            }
        ]
    return []


def _require_string(name: str, value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _require_mapping(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_string_list(name: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return value


def _valid_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    for field in ("run_id", "stage", "status", "created_at_utc"):
        if not isinstance(entry.get(field), str):
            return False
    if not isinstance(entry.get("command"), list) or not all(
        isinstance(item, str) for item in entry["command"]
    ):
        return False
    for field in ("config", "inputs", "outputs", "metrics"):
        if not isinstance(entry.get(field), dict):
            return False
    return isinstance(entry.get("warnings"), list) and all(
        isinstance(item, str) for item in entry["warnings"]
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<redacted>" if _secret_key(str(key)) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        result: list[Any] = []
        redact_next = False
        for item in value:
            if redact_next:
                result.append("<redacted>")
                redact_next = False
                continue
            result.append(_redact(item))
            if isinstance(item, str) and _secret_key(item):
                redact_next = True
        return result
    return value


def _secret_key(value: str) -> bool:
    lowered = value.lower().lstrip("-")
    return any(marker in lowered for marker in SECRET_MARKERS)
