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
    entry = {
        "run_id": resolved_run_id,
        "stage": stage,
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": _redact(command or []),
        "config": _redact(config or {}),
        "inputs": _redact(inputs or {}),
        "outputs": _redact(outputs or {}),
        "metrics": metrics or {},
        "warnings": warnings or [],
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
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
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
