"""Unit tests for hima_dht_cli.services._native (natively spawned services).

Test cases:
- test_ensure_service_foreign_endpoint_raises: an endpoint answered
  without an owned pid raises CommandError instead of skipping launch.
- test_ensure_service_owned_healthy_short_circuits: a live owned pid with
  a healthy endpoint returns without launching.
- test_ensure_leader_model_queries_ollama_port: the presence check runs
  against the Ollama root built from the given port.
- test_ensure_leader_model_logs_pull_exit: a pull emits an exit record
  carrying the model and the exit code.
- test_wait_healthy_logs_service_and_attempts: reaching health emits one
  record carrying the service name and the attempt count.
- test_stop_one_logs_skip_without_pid_file: stopping a service that hima
  never started emits a skip record instead of touching any process.
- test_ollama_spec_binds_port_via_env: the ollama spec carries OLLAMA_HOST
  for the requested port and probes the same port.
"""

import logging
import os
from pathlib import Path
from types import SimpleNamespace

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
    own_executable = psutil.Process(os.getpid()).cmdline()[0]
    spec = _spec(tmp_path, keyword=own_executable)
    spec.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(_native, "healthy", lambda url: True)
    monkeypatch.setattr(_native, "launch", lambda spec: pytest.fail("launch must not run"))

    assert _native.ensure_service(spec) == os.getpid()


def test_ensure_leader_model_queries_ollama_port(monkeypatch: pytest.MonkeyPatch) -> None:
    queried: dict[str, tuple[str, str]] = {}

    def fake_present(root: str, model: str) -> bool:
        queried["endpoint"] = (root, model)
        return True

    monkeypatch.setattr(_native, "leader_model_present", fake_present)

    _native.ensure_leader_model("qwen3:8b", skip_pull=True, ollama_port=12345)

    assert queried["endpoint"] == ("http://localhost:12345", "qwen3:8b")


def test_ensure_leader_model_logs_pull_exit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(_native, "leader_model_present", lambda root, model: False)
    monkeypatch.setattr(
        "hima_dht_cli.services._native.subprocess.run",
        lambda argv, env: SimpleNamespace(returncode=0),
    )

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services._native"):
        _native.ensure_leader_model("qwen3:8b", skip_pull=False, ollama_port=11434)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("leader model pull exited: model=qwen3:8b exit_code=0")
        for message in messages
    )


def test_wait_healthy_logs_service_and_attempts(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(_native, "healthy", lambda url: True)

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services._native"):
        _native.wait_healthy(_native.advisor_spec(8090))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("service healthy: service=advisor attempts=1") for message in messages
    )


def test_stop_one_logs_skip_without_pid_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services._native"):
        _native.stop_one(_spec(tmp_path))

    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["service stop skipped: service=advisor reason=no_pid_file"]


def test_ollama_spec_binds_port_via_env() -> None:
    spec = _native.ollama_spec(12345)

    assert spec.env == {"OLLAMA_HOST": "127.0.0.1:12345"}
    assert spec.health_url == "http://localhost:12345/api/tags"
