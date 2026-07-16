from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_RUN_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "failed": {"queued"},
    "cancelled": {"queued"},
    "succeeded": set(),
}


def _strict_limit(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    return value


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_run(self, *, run_type: str, inputs: dict[str, Any], config_path: str = "") -> dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(run_id, run_type, status, created_at_utc, updated_at_utc, inputs_json, config_path)
                VALUES (?, ?, 'queued', ?, ?, ?, ?)
                """,
                (run_id, run_type, now, now, _json(inputs), config_path),
            )
        return self.get_run(run_id, include_children=False)

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = _strict_limit(limit)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_run_row(row) for row in rows]

    def get_run(self, run_id: str, *, include_children: bool = True) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            result = _run_row(row)
            if include_children:
                result["stages"] = [_stage_row(item) for item in conn.execute(
                    "SELECT * FROM stages WHERE run_id = ? ORDER BY stage_id", (run_id,)
                ).fetchall()]
                result["artifacts"] = [_artifact_row(item) for item in conn.execute(
                    "SELECT * FROM artifacts WHERE run_id = ? ORDER BY artifact_id", (run_id,)
                ).fetchall()]
        return result

    def transition_run(self, run_id: str, status: str, *, error: str = "") -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = str(row["status"])
            if status not in _RUN_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid run state transition: {current} -> {status}")
            conn.execute(
                "UPDATE runs SET status = ?, updated_at_utc = ?, error = ? WHERE run_id = ?",
                (status, _utc_now(), error, run_id),
            )
        return self.get_run(run_id, include_children=False)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self.transition_run(run_id, "cancelled")

    def retry_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT status, retry_count FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = str(row["status"])
            if "queued" not in _RUN_TRANSITIONS.get(current, set()):
                raise ValueError(f"Run cannot be retried from status: {current}")
            conn.execute(
                "UPDATE runs SET status = 'queued', retry_count = ?, updated_at_utc = ?, error = '' WHERE run_id = ?",
                (int(row["retry_count"]) + 1, _utc_now(), run_id),
            )
        return self.get_run(run_id, include_children=False)

    def start_stage(self, run_id: str, stage: str) -> dict[str, Any]:
        run = self.get_run(run_id, include_children=False)
        if run["status"] != "running":
            raise ValueError(f"Cannot start a stage while run status is {run['status']}")
        with self._connect() as conn:
            attempt = int(conn.execute(
                "SELECT COUNT(*) AS count FROM stages WHERE run_id = ? AND stage = ?", (run_id, stage)
            ).fetchone()["count"]) + 1
            cursor = conn.execute(
                """
                INSERT INTO stages(run_id, stage, status, attempt, started_at_utc, metrics_json)
                VALUES (?, ?, 'running', ?, ?, '{}')
                """,
                (run_id, stage, attempt, _utc_now()),
            )
            stage_id = int(cursor.lastrowid)
        return self.get_stage(stage_id)

    def get_stage(self, stage_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM stages WHERE stage_id = ?", (stage_id,)).fetchone()
        if row is None:
            raise KeyError(str(stage_id))
        return _stage_row(row)

    def finish_stage(
        self,
        stage_id: int,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError(f"Unsupported terminal stage status: {status}")
        with self._connect() as conn:
            current = conn.execute("SELECT status FROM stages WHERE stage_id = ?", (stage_id,)).fetchone()
            if current is None:
                raise KeyError(str(stage_id))
            if current["status"] != "running":
                raise ValueError(f"Stage is not running: {stage_id}")
            conn.execute(
                "UPDATE stages SET status = ?, finished_at_utc = ?, metrics_json = ?, error = ? WHERE stage_id = ?",
                (status, _utc_now(), _json(metrics or {}), error, stage_id),
            )
        return self.get_stage(stage_id)

    def add_artifact(
        self,
        run_id: str,
        *,
        stage: str,
        name: str,
        path: str,
        schema_version: str,
        sha256: str,
        media_type: str = "application/json",
    ) -> dict[str, Any]:
        self.get_run(run_id, include_children=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO artifacts(run_id, stage, name, path, schema_version, sha256, media_type, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, stage, name, path, schema_version, sha256, media_type, _utc_now()),
            )
            artifact_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        return _artifact_row(row)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    config_path TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS stages (
                    stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT NOT NULL DEFAULT '',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_stages_run_id ON stages(run_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "run_type": row["run_type"],
        "status": row["status"],
        "created_at_utc": row["created_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
        "inputs": json.loads(row["inputs_json"]),
        "config_path": row["config_path"],
        "retry_count": int(row["retry_count"]),
        "error": row["error"],
    }


def _stage_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "stage_id": int(row["stage_id"]),
        "run_id": row["run_id"],
        "stage": row["stage"],
        "status": row["status"],
        "attempt": int(row["attempt"]),
        "started_at_utc": row["started_at_utc"],
        "finished_at_utc": row["finished_at_utc"],
        "metrics": json.loads(row["metrics_json"]),
        "error": row["error"],
    }


def _artifact_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "artifact_id": int(row["artifact_id"]),
        "run_id": row["run_id"],
        "stage": row["stage"],
        "name": row["name"],
        "path": row["path"],
        "schema_version": row["schema_version"],
        "sha256": row["sha256"],
        "media_type": row["media_type"],
        "created_at_utc": row["created_at_utc"],
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
