"""Unit tests for hima_dht_cli.services (managed background services).

Test cases:
- test_ensure_leader_model_queries_local_ollama_root: the leader-model
  presence check runs against the local Ollama root that `hima up`
  manages.
- test_up_ensures_services_in_dependency_order: `hima up` ensures ollama,
  the leader model, the advisor, then the webui.
- test_down_stops_services_in_reverse_order: `hima down` stops the webui,
  the advisor, then ollama.
- test_leader_models_lists_openai_endpoint: the endpoint check GETs
  {base_url}/models with the bearer key and returns the served ids.
- test_leader_models_none_when_unreachable: a request failure yields None,
  distinct from an empty served list.
- test_wait_healthy_logs_service_and_attempts: reaching health emits one
  record carrying the service name and the attempt count.
- test_ensure_leader_model_logs_pull_exit: a pull emits an exit record
  carrying the model and the exit code.
- test_stop_one_logs_skip_without_pid_file: stopping a service that hima
  never started emits a skip record instead of touching any process.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from hima_dht_cli import services


def test_ensure_leader_model_queries_local_ollama_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried: dict = {}

    def fake_leader_model_present(root: str, model: str) -> bool:
        queried["endpoint"] = (root, model)
        return True

    monkeypatch.setattr(services, "leader_model_present", fake_leader_model_present)
    services._ensure_leader_model("qwen3:8b", skip_pull=True)

    assert queried["endpoint"] == (services.OLLAMA_URL, "qwen3:8b")


def test_up_ensures_services_in_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def fake_ensure_service(spec: services.ServiceSpec) -> None:
        order.append(spec.name)

    def fake_ensure_leader_model(model: str, skip_pull: bool) -> None:
        order.append("leader-model")

    monkeypatch.setattr(services, "_ensure_service", fake_ensure_service)
    monkeypatch.setattr(services, "_ensure_leader_model", fake_ensure_leader_model)
    services.up(services.ServiceOptions(), skip_pull=True)

    assert order == ["ollama", "leader-model", "advisor", "webui"]


def test_down_stops_services_in_reverse_order(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped: list[str] = []

    def fake_stop_one(spec: services.ServiceSpec) -> None:
        stopped.append(spec.name)

    monkeypatch.setattr(services, "_stop_one", fake_stop_one)
    services.down()

    assert stopped == ["webui", "advisor", "ollama"]


def test_leader_models_lists_openai_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "llama3:8b"}]}

    def fake_get(url: str, headers: dict, timeout: int) -> FakeResponse:
        requested["url"] = url
        requested["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(services.requests, "get", fake_get)
    served = services.leader_models("http://localhost:11434/v1", "secret")

    assert served == ["qwen3:8b", "llama3:8b"]
    assert requested["url"] == "http://localhost:11434/v1/models"
    assert requested["headers"] == {"Authorization": "Bearer secret"}


def test_leader_models_none_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, headers: dict, timeout: int) -> None:
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(services.requests, "get", fake_get)

    assert services.leader_models("http://localhost:11434/v1", "ollama") is None


def test_wait_healthy_logs_service_and_attempts(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services, "_healthy", lambda url: True)

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services"):
        services._wait_healthy(services.advisor_spec(8090))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("service healthy: service=advisor attempts=1") for message in messages
    )


def test_ensure_leader_model_logs_pull_exit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services, "leader_model_present", lambda root, model: False)
    monkeypatch.setattr(services.subprocess, "run", lambda argv: SimpleNamespace(returncode=0))

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services"):
        services._ensure_leader_model("qwen3:8b", skip_pull=False)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("leader model pull exited: model=qwen3:8b exit_code=0")
        for message in messages
    )


def test_stop_one_logs_skip_without_pid_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spec = services.ServiceSpec(
        name="advisor",
        argv=["true"],
        health_url="http://127.0.0.1:8090/health",
        pid_file=tmp_path / "advisor.pid",
        log_file=tmp_path / "advisor.log",
        process_keyword="uvicorn",
    )

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.services"):
        services._stop_one(spec)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["service stop skipped: service=advisor reason=no_pid_file"]
