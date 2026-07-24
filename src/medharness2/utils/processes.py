from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SECRET_FLAGS = {
    "--api-key",
    "--api_key",
    "--authorization",
    "--password",
    "--secret",
    "--token",
}


def run_isolated_process(
    args: Sequence[str | os.PathLike[str]],
    *,
    timeout: float | None,
    check: bool,
    cwd: str | os.PathLike[str] | None = None,
    env: MutableMapping[str, str] | None = None,
    terminate_grace_sec: float = 5.0,
    context: MutableMapping[str, Any] | None = None,
    capture_output: bool = False,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    if terminate_grace_sec < 0:
        raise ValueError("terminate_grace_sec must be non-negative")
    command = [os.fspath(part) for part in args]
    if not command:
        raise ValueError("args must not be empty")
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    started_at = _utc_now()
    provenance: dict[str, Any] = {
        "pid": None,
        "pgid": None,
        "pgid_verified": False,
        "ppid": os.getpid(),
        "started_at_utc": started_at,
        "completed_at_utc": None,
        "termination_reason": "running",
        "requested_device": None,
        "command": [],
        "returncode": None,
        "sigterm_sent": False,
        "sigkill_sent": False,
        "direct_sigterm_sent": False,
        "direct_sigkill_sent": False,
        "group_active_after_cleanup": None,
        "cleanup_errors": [],
    }
    pgid: int | None = None
    cleanup_attempted = False
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=text,
        start_new_session=True,
        shell=False,
    )
    try:
        provenance["pid"] = process.pid
        pgid = os.getpgid(process.pid)
        if pgid != process.pid:
            raise RuntimeError("isolated process did not create a dedicated process group")
        provenance["pgid"] = pgid
        provenance["pgid_verified"] = True
        provenance["command"] = _redacted_command(command)
        provenance["requested_device"] = (
            context.get("requested_device") if context is not None else None
        ) or _option_value(command, "--device")
        if context is not None:
            context["process_provenance"] = provenance
        stdout_value, stderr_value = process.communicate(timeout=timeout)
        returncode = process.poll()
        if returncode is None:
            raise RuntimeError("isolated process did not publish a return code")
        provenance["returncode"] = returncode
        provenance["termination_reason"] = "completed" if returncode == 0 else "nonzero_exit"
        if returncode:
            cleanup_attempted = True
            _safe_terminate_owned_process_group(
                process,
                pgid,
                terminate_grace_sec=terminate_grace_sec,
                provenance=provenance,
            )
        elif _process_group_active(pgid):
            provenance["termination_reason"] = "lingering_process_group_after_success"
            cleanup_attempted = True
            _safe_terminate_owned_process_group(
                process,
                pgid,
                terminate_grace_sec=terminate_grace_sec,
                provenance=provenance,
            )
        else:
            provenance["group_active_after_cleanup"] = False
        provenance["completed_at_utc"] = _utc_now()
        completed = subprocess.CompletedProcess(
            process.args,
            returncode,
            stdout_value,
            stderr_value,
        )
        completed.process_provenance = provenance
        if check and returncode:
            exc = subprocess.CalledProcessError(
                returncode,
                process.args,
                output=stdout_value,
                stderr=stderr_value,
            )
            _attach_process_provenance(exc, provenance)
            raise exc
        return completed
    except BaseException as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            provenance["termination_reason"] = "timeout"
        elif not provenance["pgid_verified"]:
            provenance["termination_reason"] = f"initialization_exception:{type(exc).__name__}"
        elif not cleanup_attempted:
            provenance["termination_reason"] = f"base_exception:{type(exc).__name__}"
        if not cleanup_attempted:
            cleanup_attempted = True
            if provenance["pgid_verified"] and pgid is not None:
                _safe_terminate_owned_process_group(
                    process,
                    pgid,
                    terminate_grace_sec=terminate_grace_sec,
                    provenance=provenance,
                )
            else:
                _safe_terminate_direct_process(
                    process,
                    terminate_grace_sec=terminate_grace_sec,
                    provenance=provenance,
                )
        provenance["returncode"] = _safe_process_poll(process, provenance)
        _set_completed_at(provenance)
        _attach_process_provenance(exc, provenance)
        raise


def _redacted_command(command: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for part in command:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        lowered = part.lower()
        flag, separator, _value = lowered.partition("=")
        if flag in _SECRET_FLAGS:
            redacted.append(f"{part.split('=', 1)[0]}=<redacted>" if separator else part)
            redact_next = not separator
            continue
        redacted.append(part)
    return redacted


def _option_value(command: Sequence[str], option: str) -> str | None:
    for index, part in enumerate(command):
        if part == option and index + 1 < len(command):
            return command[index + 1]
        prefix = f"{option}="
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


def _terminate_owned_process_group(
    process: subprocess.Popen[Any],
    pgid: int,
    *,
    terminate_grace_sec: float,
    provenance: MutableMapping[str, Any],
) -> None:
    if pgid != process.pid or pgid == os.getpgrp():
        raise RuntimeError("refusing to terminate a process group that is not owned")
    if _process_group_active(pgid):
        try:
            os.killpg(pgid, signal.SIGTERM)
            provenance["sigterm_sent"] = True
        except ProcessLookupError:
            pass
        except OSError as exc:
            _record_cleanup_error(provenance, "sigterm", exc)
        if not _wait_for_group_exit(pgid, terminate_grace_sec):
            try:
                os.killpg(pgid, signal.SIGKILL)
                provenance["sigkill_sent"] = True
            except ProcessLookupError:
                pass
            except OSError as exc:
                _record_cleanup_error(provenance, "sigkill", exc)
            _wait_for_group_exit(pgid, max(terminate_grace_sec, 0.2))
    if process.poll() is None:
        try:
            process.wait(timeout=max(terminate_grace_sec, 0.2))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    provenance["group_active_after_cleanup"] = _process_group_active(pgid)


def _safe_terminate_owned_process_group(
    process: subprocess.Popen[Any],
    pgid: int,
    *,
    terminate_grace_sec: float,
    provenance: MutableMapping[str, Any],
) -> None:
    try:
        _terminate_owned_process_group(
            process,
            pgid,
            terminate_grace_sec=terminate_grace_sec,
            provenance=provenance,
        )
    except BaseException as exc:
        _record_cleanup_error(provenance, "process_group_cleanup", exc)
        _safe_terminate_direct_process(
            process,
            terminate_grace_sec=terminate_grace_sec,
            provenance=provenance,
        )


def _safe_terminate_direct_process(
    process: subprocess.Popen[Any],
    *,
    terminate_grace_sec: float,
    provenance: MutableMapping[str, Any],
) -> None:
    try:
        _terminate_direct_process(
            process,
            terminate_grace_sec=terminate_grace_sec,
            provenance=provenance,
        )
    except BaseException as exc:
        _record_cleanup_error(provenance, "direct_process_cleanup", exc)


def _terminate_direct_process(
    process: subprocess.Popen[Any],
    *,
    terminate_grace_sec: float,
    provenance: MutableMapping[str, Any],
) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        provenance["direct_sigterm_sent"] = True
    except ProcessLookupError:
        return
    except BaseException as exc:
        _record_cleanup_error(provenance, "direct_sigterm", exc)
    try:
        process.wait(timeout=max(terminate_grace_sec, 0.2))
        return
    except subprocess.TimeoutExpired:
        pass
    except BaseException as exc:
        _record_cleanup_error(provenance, "direct_wait_after_sigterm", exc)
    try:
        process.kill()
        provenance["direct_sigkill_sent"] = True
    except ProcessLookupError:
        return
    except BaseException as exc:
        _record_cleanup_error(provenance, "direct_sigkill", exc)
    try:
        process.wait(timeout=max(terminate_grace_sec, 0.2))
    except BaseException as exc:
        _record_cleanup_error(provenance, "direct_wait_after_sigkill", exc)


def _record_cleanup_error(
    provenance: MutableMapping[str, Any],
    operation: str,
    exc: BaseException,
) -> None:
    errors = provenance.setdefault("cleanup_errors", [])
    if isinstance(errors, list):
        errors.append(f"{operation}:{type(exc).__name__}: {exc}")


def _attach_process_provenance(
    value: BaseException,
    provenance: MutableMapping[str, Any],
) -> None:
    try:
        value.process_provenance = provenance
    except BaseException:
        pass


def _safe_process_poll(
    process: subprocess.Popen[Any],
    provenance: MutableMapping[str, Any],
) -> int | None:
    try:
        return process.poll()
    except BaseException as exc:
        _record_cleanup_error(provenance, "process_poll", exc)
        return None


def _set_completed_at(provenance: MutableMapping[str, Any]) -> None:
    try:
        provenance["completed_at_utc"] = _utc_now()
    except BaseException as exc:
        _record_cleanup_error(provenance, "completed_timestamp", exc)


def _wait_for_group_exit(pgid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_group_active(pgid):
            return True
        time.sleep(0.02)
    return not _process_group_active(pgid)


def _process_group_active(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return True
    for stat_path in proc_root.glob("[0-9]*/stat"):
        try:
            fields = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[-1].strip().split()
            state = fields[0]
            process_group = int(fields[2])
        except (OSError, ValueError, IndexError):
            continue
        if process_group == pgid and state != "Z":
            return True
    return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
