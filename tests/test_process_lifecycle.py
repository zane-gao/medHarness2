from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

import medharness2.utils.processes as processes_module
from medharness2.utils.processes import run_isolated_process


def test_run_isolated_process_returns_completed_process_with_provenance():
    context: dict[str, object] = {}

    completed = run_isolated_process(
        [
            sys.executable,
            "-c",
            "print('ok')",
            "--device",
            "cuda:7",
            "--api-key",
            "secret-value",
        ],
        timeout=2,
        check=True,
        capture_output=True,
        text=True,
        terminate_grace_sec=0.1,
        context=context,
    )

    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.stdout == "ok\n"
    assert completed.stderr == ""
    provenance = context["process_provenance"]
    assert completed.process_provenance == provenance
    assert provenance["pid"] == provenance["pgid"]
    assert provenance["pgid"] != os.getpgrp()
    assert provenance["ppid"] == os.getpid()
    assert provenance["requested_device"] == "cuda:7"
    assert provenance["command"][-2:] == ["--api-key", "<redacted>"]
    assert provenance["termination_reason"] == "completed"
    assert provenance["sigterm_sent"] is False
    assert provenance["sigkill_sent"] is False
    assert datetime.fromisoformat(provenance["started_at_utc"]).tzinfo is not None
    assert datetime.fromisoformat(provenance["completed_at_utc"]).tzinfo is not None


def test_run_isolated_process_timeout_cleans_parent_and_child(tmp_path: Path):
    pid_path = tmp_path / "pids.txt"
    script = "\n".join(
        [
            "import os, pathlib, subprocess, sys, time",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
            "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()}\\n{child.pid}\\n')",
            "time.sleep(60)",
        ]
    )
    command = [sys.executable, "-c", script, str(pid_path)]
    context: dict[str, object] = {}

    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_isolated_process(
                command,
                timeout=0.3,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        assert caught.value.cmd == command
        assert caught.value.timeout == 0.3
        pids = [int(value) for value in pid_path.read_text().splitlines()]
        assert _wait_until(lambda: all(not _pid_is_running(pid) for pid in pids))
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert provenance["termination_reason"] == "timeout"
        assert provenance["sigterm_sent"] is True
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_escalates_to_sigkill_when_term_is_ignored():
    script = "\n".join(
        [
            "import signal, time",
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
            "time.sleep(60)",
        ]
    )
    context: dict[str, object] = {}

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_isolated_process(
                [sys.executable, "-c", script],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert provenance["termination_reason"] == "timeout"
        assert provenance["sigterm_sent"] is True
        assert provenance["sigkill_sent"] is True
        assert provenance["group_active_after_cleanup"] is False
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_nonzero_exit_cleans_background_descendant(tmp_path: Path):
    child_pid_path = tmp_path / "child.pid"
    script = "\n".join(
        [
            "import pathlib, subprocess, sys",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))",
            "print('leader stdout')",
            "print('leader stderr', file=sys.stderr)",
            "raise SystemExit(7)",
        ]
    )
    command = [sys.executable, "-c", script, str(child_pid_path)]
    context: dict[str, object] = {}

    try:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            run_isolated_process(
                command,
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        assert caught.value.cmd == command
        assert caught.value.returncode == 7
        assert caught.value.stdout == "leader stdout\n"
        assert caught.value.stderr == "leader stderr\n"
        child_pid = int(child_pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(child_pid))
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert caught.value.process_provenance == provenance
        assert provenance["termination_reason"] == "nonzero_exit"
        assert provenance["sigterm_sent"] is True
        assert provenance["group_active_after_cleanup"] is False
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_success_cleans_lingering_background_descendant(tmp_path: Path):
    child_pid_path = tmp_path / "child.pid"
    script = "\n".join(
        [
            "import pathlib, subprocess, sys",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))",
            "print('done')",
        ]
    )
    context: dict[str, object] = {}

    try:
        completed = run_isolated_process(
            [sys.executable, "-c", script, str(child_pid_path)],
            timeout=2,
            check=True,
            capture_output=True,
            text=True,
            terminate_grace_sec=0.1,
            context=context,
        )
        assert completed.returncode == 0
        assert completed.stdout == "done\n"
        child_pid = int(child_pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(child_pid))
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert provenance["termination_reason"] == "lingering_process_group_after_success"
        assert provenance["sigterm_sent"] is True
        assert provenance["group_active_after_cleanup"] is False
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_base_exception_cleans_owned_group(monkeypatch, tmp_path: Path):
    pid_path = tmp_path / "pids.txt"
    script = "\n".join(
        [
            "import os, pathlib, subprocess, sys, time",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
            "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()}\\n{child.pid}\\n')",
            "time.sleep(60)",
        ]
    )
    real_popen = subprocess.Popen

    class SyntheticCancellation(BaseException):
        pass

    class InterruptingPopen:
        def __init__(self, *args, **kwargs):
            self._process = real_popen(*args, **kwargs)

        def communicate(self, *args, **kwargs):
            assert _wait_until(pid_path.exists)
            raise SyntheticCancellation("cancelled")

        def __getattr__(self, name):
            return getattr(self._process, name)

    monkeypatch.setattr(processes_module.subprocess, "Popen", InterruptingPopen)
    context: dict[str, object] = {}

    try:
        with pytest.raises(SyntheticCancellation) as caught:
            run_isolated_process(
                [sys.executable, "-c", script, str(pid_path)],
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        pids = [int(value) for value in pid_path.read_text().splitlines()]
        assert _wait_until(lambda: all(not _pid_is_running(pid) for pid in pids))
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert caught.value.process_provenance == provenance
        assert provenance["termination_reason"] == "base_exception:SyntheticCancellation"
        assert provenance["sigterm_sent"] is True
        assert provenance["group_active_after_cleanup"] is False
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_does_not_touch_unrelated_process_group():
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    context: dict[str, object] = {}

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_isolated_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        assert unrelated.poll() is None
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert provenance["pgid"] != os.getpgid(unrelated.pid)
    finally:
        _kill_group_if_present(unrelated.pid)
        unrelated.wait()


def test_run_isolated_process_concurrent_groups_are_isolated():
    timeout_context: dict[str, object] = {}
    success_context: dict[str, object] = {}

    def timeout_task() -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            run_isolated_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=timeout_context,
            )

    def success_task() -> subprocess.CompletedProcess[str]:
        return run_isolated_process(
            [sys.executable, "-c", "import time; time.sleep(0.4); print('survived')"],
            timeout=2,
            check=True,
            capture_output=True,
            text=True,
            terminate_grace_sec=0.1,
            context=success_context,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        timeout_future = executor.submit(timeout_task)
        success_future = executor.submit(success_task)
        timeout_future.result()
        completed = success_future.result()

    assert completed.stdout == "survived\n"
    timeout_provenance = timeout_context["process_provenance"]
    success_provenance = success_context["process_provenance"]
    assert isinstance(timeout_provenance, dict)
    assert isinstance(success_provenance, dict)
    assert timeout_provenance["pgid"] != success_provenance["pgid"]
    assert timeout_provenance["termination_reason"] == "timeout"
    assert success_provenance["termination_reason"] == "completed"


def test_run_isolated_process_check_false_returns_nonzero_after_cleanup(tmp_path: Path):
    child_pid_path = tmp_path / "child.pid"
    script = "\n".join(
        [
            "import pathlib, subprocess, sys",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))",
            "print('dry-run stdout')",
            "print('dry-run stderr', file=sys.stderr)",
            "raise SystemExit(9)",
        ]
    )
    context: dict[str, object] = {}

    try:
        completed = run_isolated_process(
            [sys.executable, "-c", script, str(child_pid_path)],
            timeout=2,
            check=False,
            capture_output=True,
            text=True,
            terminate_grace_sec=0.1,
            context=context,
        )
        assert completed.returncode == 9
        assert completed.stdout == "dry-run stdout\n"
        assert completed.stderr == "dry-run stderr\n"
        child_pid = int(child_pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(child_pid))
        assert completed.process_provenance["termination_reason"] == "nonzero_exit"
        assert completed.process_provenance["group_active_after_cleanup"] is False
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_cleanup_error_does_not_mask_timeout(monkeypatch):
    real_killpg = os.killpg
    context: dict[str, object] = {}

    def failing_killpg(pgid: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            raise PermissionError("synthetic cleanup denial")
        real_killpg(pgid, sig)

    monkeypatch.setattr(processes_module.os, "killpg", failing_killpg)

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_isolated_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        provenance = context["process_provenance"]
        assert isinstance(provenance, dict)
        assert provenance["termination_reason"] == "timeout"
        assert provenance["cleanup_errors"] == [
            "sigterm:PermissionError: synthetic cleanup denial"
        ]
        assert _wait_until(lambda: not _pid_is_running(int(provenance["pid"])))
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            try:
                real_killpg(int(provenance["pgid"]), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_run_isolated_process_getpgid_failure_cleans_direct_child(monkeypatch, tmp_path: Path):
    pid_path = tmp_path / "leader.pid"
    script = "\n".join(
        [
            "import os, pathlib, sys, time",
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))",
            "time.sleep(60)",
        ]
    )

    def fail_getpgid(_pid: int) -> int:
        assert _wait_until(pid_path.exists)
        raise ProcessLookupError("synthetic PGID lookup failure")

    monkeypatch.setattr(processes_module.os, "getpgid", fail_getpgid)

    try:
        with pytest.raises(ProcessLookupError, match="synthetic PGID lookup failure"):
            run_isolated_process(
                [sys.executable, "-c", script, str(pid_path)],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
            )
        pid = int(pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(pid))
    finally:
        if pid_path.exists():
            _kill_group_if_present(int(pid_path.read_text()))


def test_run_isolated_process_initialization_cancellation_cleans_owned_group(tmp_path: Path):
    pid_path = tmp_path / "leader.pid"
    script = "\n".join(
        [
            "import os, pathlib, sys, time",
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))",
            "time.sleep(60)",
        ]
    )

    class SyntheticCancellation(BaseException):
        pass

    class InterruptingContext(dict[str, object]):
        def __setitem__(self, key: str, value: object) -> None:
            assert _wait_until(pid_path.exists)
            raise SyntheticCancellation("cancelled during provenance initialization")

    try:
        with pytest.raises(SyntheticCancellation, match="provenance initialization"):
            run_isolated_process(
                [sys.executable, "-c", script, str(pid_path)],
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=InterruptingContext(),
            )
        pid = int(pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(pid))
    finally:
        if pid_path.exists():
            _kill_group_if_present(int(pid_path.read_text()))


def test_run_isolated_process_provenance_construction_failure_cleans_child(
    monkeypatch,
    tmp_path: Path,
):
    pid_path = tmp_path / "leader.pid"
    script = "\n".join(
        [
            "import os, pathlib, sys, time",
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))",
            "time.sleep(60)",
        ]
    )

    def fail_redaction(_command):
        assert _wait_until(pid_path.exists)
        raise RuntimeError("synthetic provenance construction failure")

    monkeypatch.setattr(processes_module, "_redacted_command", fail_redaction)

    try:
        with pytest.raises(RuntimeError, match="provenance construction failure"):
            run_isolated_process(
                [sys.executable, "-c", script, str(pid_path)],
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
            )
        pid = int(pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(pid))
    finally:
        if pid_path.exists():
            _kill_group_if_present(int(pid_path.read_text()))


def test_run_isolated_process_pid_capture_failure_cleans_direct_child(
    monkeypatch,
    tmp_path: Path,
):
    pid_path = tmp_path / "leader.pid"
    script = "\n".join(
        [
            "import os, pathlib, sys, time",
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))",
            "time.sleep(60)",
        ]
    )
    real_popen = processes_module.subprocess.Popen

    class FailFirstPidRead:
        def __init__(self, process):
            self._process = process
            self._pid_reads = 0

        @property
        def pid(self):
            self._pid_reads += 1
            if self._pid_reads == 1:
                assert _wait_until(pid_path.exists)
                raise RuntimeError("synthetic pid capture failure")
            return self._process.pid

        def __getattr__(self, name):
            return getattr(self._process, name)

    def fake_popen(*args, **kwargs):
        return FailFirstPidRead(real_popen(*args, **kwargs))

    monkeypatch.setattr(processes_module.subprocess, "Popen", fake_popen)

    try:
        with pytest.raises(RuntimeError, match="pid capture failure"):
            run_isolated_process(
                [sys.executable, "-c", script, str(pid_path)],
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
            )
        pid = int(pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(pid))
    finally:
        if pid_path.exists():
            _kill_group_if_present(int(pid_path.read_text()))


def test_run_isolated_process_post_communicate_cancellation_cleans_descendant(
    monkeypatch,
    tmp_path: Path,
):
    child_pid_path = tmp_path / "child.pid"
    script = "\n".join(
        [
            "import pathlib, subprocess, sys",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))",
        ]
    )
    real_group_active = processes_module._process_group_active
    calls = 0

    class SyntheticCancellation(BaseException):
        pass

    def interrupt_first_group_check(pgid: int) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SyntheticCancellation("cancelled after communicate")
        return real_group_active(pgid)

    monkeypatch.setattr(
        processes_module,
        "_process_group_active",
        interrupt_first_group_check,
    )
    context: dict[str, object] = {}

    try:
        with pytest.raises(SyntheticCancellation, match="after communicate"):
            run_isolated_process(
                [sys.executable, "-c", script, str(child_pid_path)],
                timeout=2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        child_pid = int(child_pid_path.read_text())
        assert _wait_until(lambda: not _pid_is_running(child_pid))
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_direct_cleanup_failure_does_not_mask_timeout(monkeypatch):
    context: dict[str, object] = {}

    def fail_group_cleanup(*args, **kwargs):
        del args, kwargs
        raise PermissionError("synthetic group cleanup failure")

    def fail_direct_cleanup(*args, **kwargs):
        del args, kwargs
        raise ValueError("synthetic direct cleanup failure")

    monkeypatch.setattr(
        processes_module,
        "_terminate_owned_process_group",
        fail_group_cleanup,
    )
    monkeypatch.setattr(
        processes_module,
        "_terminate_direct_process",
        fail_direct_cleanup,
    )

    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_isolated_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        assert caught.value.process_provenance["termination_reason"] == "timeout"
        assert any(
            "synthetic direct cleanup failure" in error
            for error in caught.value.process_provenance["cleanup_errors"]
        )
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def test_run_isolated_process_timeout_preserves_subprocess_output_types():
    script = "\n".join(
        [
            "import sys, time",
            "print('partial stdout', flush=True)",
            "print('partial stderr', file=sys.stderr, flush=True)",
            "time.sleep(60)",
        ]
    )
    context: dict[str, object] = {}

    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_isolated_process(
                [sys.executable, "-c", script],
                timeout=0.2,
                check=True,
                capture_output=True,
                text=True,
                terminate_grace_sec=0.1,
                context=context,
            )
        assert caught.value.stdout == b"partial stdout\n"
        assert caught.value.stderr == b"partial stderr\n"
    finally:
        provenance = context.get("process_provenance")
        if isinstance(provenance, dict):
            _kill_group_if_present(int(provenance["pgid"]))


def _pid_is_running(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    fields = stat.rsplit(")", 1)[-1].strip().split()
    return bool(fields) and fields[0] != "Z"


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _kill_group_if_present(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
