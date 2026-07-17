from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class CheckpointIntegrityError(RuntimeError):
    """Raised when an existing checkpoint cannot be trusted."""


CheckpointValidator = Callable[[dict[str, Any]], dict[str, Any]]


class StageCheckpointStore:
    """Content-addressed storage for validated, structured stage outputs."""

    def __init__(
        self,
        root: str | Path,
        *,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.event_callback = event_callback
        self._stats = {"hits": 0, "misses": 0, "writes": 0}
        self._events: list[dict[str, Any]] = []

    def get_or_compute(
        self,
        stage: str,
        inputs: Any,
        producer: Callable[[], dict[str, Any]],
        *,
        validator: CheckpointValidator,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", stage):
            raise ValueError(f"Invalid checkpoint stage name: {stage!r}")
        input_sha256 = stable_sha256(inputs)
        stage_dir = self.root / stage.replace(".", "/")
        checkpoint_path = stage_dir / f"{input_sha256}.json"
        lock_path = stage_dir / f"{input_sha256}.lock"
        stage_dir.mkdir(parents=True, exist_ok=True)

        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if checkpoint_path.is_file():
                output, output_sha256 = self._read_checkpoint(
                    checkpoint_path,
                    stage=stage,
                    input_sha256=input_sha256,
                    validator=validator,
                )
                self._stats["hits"] += 1
                self._record_event(
                    stage=stage,
                    status="hit",
                    path=checkpoint_path,
                    input_sha256=input_sha256,
                    output_sha256=output_sha256,
                )
                return copy.deepcopy(output)

            self._stats["misses"] += 1
            self._record_event(
                stage=stage,
                status="miss",
                path=checkpoint_path,
                input_sha256=input_sha256,
            )
            produced = producer()
            if not isinstance(produced, dict):
                raise TypeError(f"Checkpoint producer for {stage!r} must return a JSON object")
            validated = validator(copy.deepcopy(produced))
            if not isinstance(validated, dict):
                raise TypeError(f"Checkpoint validator for {stage!r} must return a JSON object")
            output_sha256 = stable_sha256(validated)
            envelope = {
                "schema_version": "1.0",
                "artifact_type": "stage_checkpoint",
                "stage": stage,
                "input_sha256": input_sha256,
                "output_sha256": output_sha256,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "output": validated,
            }
            _atomic_write_json(checkpoint_path, envelope)
            self._stats["writes"] += 1
            self._record_event(
                stage=stage,
                status="write",
                path=checkpoint_path,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
            )
            return copy.deepcopy(validated)

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "root": str(self.root),
            "stats": dict(self._stats),
            "events": copy.deepcopy(self._events),
        }

    def _read_checkpoint(
        self,
        path: Path,
        *,
        stage: str,
        input_sha256: str,
        validator: CheckpointValidator,
    ) -> tuple[dict[str, Any], str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointIntegrityError(f"Unreadable checkpoint {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise CheckpointIntegrityError(f"Checkpoint must contain a JSON object: {path}")
        if payload.get("schema_version") != "1.0" or payload.get("artifact_type") != "stage_checkpoint":
            raise CheckpointIntegrityError(f"Unsupported checkpoint envelope: {path}")
        if payload.get("stage") != stage:
            raise CheckpointIntegrityError(f"Checkpoint stage mismatch: {path}")
        stored_input_sha256 = payload.get("input_sha256")
        if not isinstance(stored_input_sha256, str):
            raise CheckpointIntegrityError(
                f"Checkpoint input_sha256 must be a string: {path}"
            )
        if stored_input_sha256 != input_sha256:
            raise CheckpointIntegrityError(f"Checkpoint input SHA-256 mismatch: {path}")
        output = payload.get("output")
        if not isinstance(output, dict):
            raise CheckpointIntegrityError(f"Checkpoint output must be a JSON object: {path}")
        output_sha256 = payload.get("output_sha256")
        if not isinstance(output_sha256, str):
            raise CheckpointIntegrityError(
                f"Checkpoint output_sha256 must be a string: {path}"
            )
        if output_sha256 != stable_sha256(output):
            raise CheckpointIntegrityError(f"Checkpoint output SHA-256 mismatch: {path}")
        try:
            validated = validator(copy.deepcopy(output))
        except Exception as exc:
            raise CheckpointIntegrityError(
                f"Checkpoint output contract validation failed for {path}: {exc}"
            ) from exc
        if not isinstance(validated, dict):
            raise CheckpointIntegrityError(f"Checkpoint validator returned a non-object: {path}")
        if stable_sha256(validated) != output_sha256:
            raise CheckpointIntegrityError(
                f"Checkpoint output changed during contract validation: {path}"
            )
        return validated, output_sha256

    def _record_event(
        self,
        *,
        stage: str,
        status: str,
        path: Path,
        input_sha256: str,
        output_sha256: str = "",
    ) -> None:
        event = {
            "stage": stage,
            "status": status,
            "path": str(path),
            "input_sha256": input_sha256,
        }
        if output_sha256:
            event["output_sha256"] = output_sha256
        self._events.append(event)
        if self.event_callback is not None:
            self.event_callback(copy.deepcopy(event))


def file_fingerprint(path: str | Path | None) -> dict[str, Any]:
    if path is None or not str(path):
        return {"path": "", "exists": False}
    candidate = Path(path).expanduser()
    fingerprint: dict[str, Any] = {"path": str(candidate), "exists": candidate.is_file()}
    if candidate.is_file():
        fingerprint.update(
            {
                "size_bytes": candidate.stat().st_size,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
        )
    return fingerprint


def llm_route_fingerprint(client: Any, options: dict[str, Any]) -> dict[str, Any]:
    llm = getattr(getattr(client, "config", None), "llm", None)
    if llm is None:
        defaults: dict[str, Any] = {}
    elif is_dataclass(llm):
        defaults = asdict(llm)
    else:
        defaults = {
            key: getattr(llm, key)
            for key in (
                "provider",
                "model",
                "api_key_env",
                "base_url",
                "temperature",
                "seed",
                "chat_max_tokens",
            )
            if hasattr(llm, key)
        }
    return {
        "client_type": f"{type(client).__module__}.{type(client).__qualname__}",
        "defaults": defaults,
        "overrides": copy.deepcopy(options),
    }


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
