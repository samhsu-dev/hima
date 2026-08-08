"""Unit tests for hima_dht_cli.services._native (natively spawned services).

Test cases:
- test_ensure_service_foreign_endpoint_raises: an endpoint answered
  without an owned pid raises CommandError instead of skipping launch.
- test_ensure_service_owned_healthy_short_circuits: a live owned
  group-leader pid with a healthy endpoint returns without launching.
- test_wait_healthy_logs_service_and_attempts: reaching health emits one
  record carrying the service name and the attempt count.
- test_wait_healthy_dead_process_reports_log_tail: a process that exits
  before health fails immediately, quoting the service log.
- test_launch_rotates_oversized_log: a log beyond the rotation bound
  moves to a .log.1 backup before the new launch appends.
- test_stop_one_logs_skip_without_pid_file: stopping a service that hima
  never started emits a skip record instead of touching any process.
- test_stop_one_escalates_to_sigkill: a process ignoring SIGTERM gets
  SIGKILL after the stop wait, and the pid record is cleared.
- test_owned_pid_clears_corrupt_pid_file: an unparsable pid record is
  removed and reported as not owned.
- test_owned_pid_access_denied_clears_record: a pid reused by another
  user's process is treated as stale, not as an error.
"""

import logging
import signal
import subprocess
from pathlib import Path

import psutil
import pytest

from hima_dht_cli import services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import _native


def _spec(tmp_path: Path, keyword: str = "uvicorn") -> services.ServiceSpec:
    return services.ServiceSpec(
        name="advisor",
        argv=["true"],
        health_url="http://127.0.0.1:8090/health",
        pid_file=tmp_path / "advisor.pid",
        log_file=tmp_path / "advisor.log",
        process_keyword=keyword,
    )


def test_ensure_service_foreign_endpoint_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_native, "healthy", lambda url: True)

    with pytest.raises(CommandError, match="did not start"):
        _native.ensure_service(_spec(tmp_path))


def test_ensure_service_owned_healthy_short_circuits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        spec = _spec(tmp_path, keyword="sleep")
        spec.pid_file.write_text(str(child.pid), encoding="utf-8")
        monkeypatch.setattr(_native, "healthy", lambda url: True)
        monkeypatch.setattr(_native, "launch", lambda spec: pytest.fail("launch must not run"))

        assert _native.ensure_service(spec) == child.pid
    finally:
        child.kill()
        child.wait()


def test_wait_healthy_logs_service_and_attempts(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(_native, "healthy", lambda url: True)

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services._native"):
        _native.wait_healthy(_native.advisor_spec(8090), pid=4321)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("service healthy: service=advisor attempts=1") for message in messages
    )


def test_wait_healthy_dead_process_reports_log_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = _spec(tmp_path)
    spec.log_file.write_text("bind: address already in use\n", encoding="utf-8")
    monkeypatch.setattr(_native, "healthy", lambda url: False)
    child = subprocess.Popen(["true"])
    child.wait()

    with pytest.raises(CommandError, match="address already in use"):
        _native.wait_healthy(spec, child.pid)


def test_launch_rotates_oversized_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_native, "LOG_ROTATE_BYTES", 10)
    spec = _spec(tmp_path)
    spec.log_file.write_text("x" * 100, encoding="utf-8")

    _native.launch(spec)

    backup = spec.log_file.with_name("advisor.log.1")
    assert backup.read_text(encoding="utf-8") == "x" * 100


def test_stop_one_logs_skip_without_pid_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services._native"):
        _native.stop_one(_spec(tmp_path))

    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["service stop skipped: service=advisor reason=no_pid_file"]


def test_stop_one_escalates_to_sigkill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _spec(tmp_path, keyword="fake")
    spec.pid_file.write_text("4321", encoding="utf-8")
    signals: list[int] = []

    class FakeProcess:
        pid = 4321

        def wait(self, timeout: float) -> None:
            if signal.SIGKILL not in signals:
                raise psutil.TimeoutExpired(timeout)

    monkeypatch.setattr(_native, "_owned_process", lambda spec, pid: FakeProcess())
    monkeypatch.setattr(_native, "_signal_group", lambda pid, signum: signals.append(signum))

    _native.stop_one(spec)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert not spec.pid_file.exists()


def test_owned_pid_clears_corrupt_pid_file(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    spec.pid_file.write_text("not-a-pid", encoding="utf-8")

    assert _native.owned_pid(spec) is None
    assert not spec.pid_file.exists()


def test_owned_pid_access_denied_clears_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = _spec(tmp_path)
    spec.pid_file.write_text("4321", encoding="utf-8")

    def denied(pid: int) -> None:
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr("hima_dht_cli.services._native.psutil.Process", denied)

    assert _native.owned_pid(spec) is None
    assert not spec.pid_file.exists()
