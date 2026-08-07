"""Unit tests for hima_dht_cli.services (managed background services).

Test cases:
- test_up_native_ensures_services_in_dependency_order: the native backend
  ensures ollama, the leader model, the advisor, then the webui, and
  records a native manifest.
- test_up_docker_records_container_manifest: the docker backend delegates
  to compose and records container entries with host endpoints.
- test_up_manifest_out_writes_copy: --manifest-out writes the manifest to
  the default location and to the requested path.
- test_ensure_service_foreign_endpoint_raises: an endpoint answered
  without an owned pid raises CommandError instead of skipping launch.
- test_ensure_service_owned_healthy_short_circuits: a live owned pid with
  a healthy endpoint returns without launching.
- test_ensure_leader_model_queries_ollama_port: the presence check runs
  against the Ollama root built from the given port.
- test_ensure_leader_model_logs_pull_exit: a pull emits an exit record
  carrying the model and the exit code.
- test_docker_leader_model_absent_skip_pull_raises: the docker backend
  with --skip-pull raises when the model is absent.
- test_down_docker_stops_compose_and_removes_manifest: a docker manifest
  routes `down` to compose stop and removes the manifest.
- test_down_without_manifest_sweeps_native_in_reverse_order: no manifest
  sweeps webui, advisor, then ollama pid files.
- test_leader_models_lists_openai_endpoint: the endpoint check GETs
  {base_url}/models with the bearer key and returns the served ids.
- test_leader_models_none_when_unreachable: a request failure yields None,
  distinct from an empty served list.
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
import requests

from hima_dht_cli import services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import _docker, _lifecycle, _native


def _spec(tmp_path: Path, keyword: str = "uvicorn") -> services.ServiceSpec:
    return services.ServiceSpec(
        name="advisor",
        argv=["true"],
        health_url="http://127.0.0.1:8090/health",
        pid_file=tmp_path / "advisor.pid",
        log_file=tmp_path / "advisor.log",
        process_keyword=keyword,
    )


def test_up_native_ensures_services_in_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    written: dict[str, services.ServiceManifest] = {}

    def fake_ensure_service(spec: services.ServiceSpec) -> int:
        order.append(spec.name)
        return 4321

    monkeypatch.setattr(_native, "ensure_service", fake_ensure_service)
    monkeypatch.setattr(
        _native,
        "ensure_leader_model",
        lambda model, skip_pull, ollama_port: order.append("leader-model"),
    )
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions(), skip_pull=True)

    assert order == ["ollama", "leader-model", "advisor", "webui"]
    assert written["manifest"].backend is services.ServiceBackend.NATIVE


def test_up_docker_records_container_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, services.ServiceManifest] = {}
    monkeypatch.setattr(_docker, "compose_up", lambda: None)
    monkeypatch.setattr(_docker, "ensure_leader_model", lambda model, skip_pull, ollama_port: None)
    monkeypatch.setattr(
        _docker,
        "container_names",
        lambda: {"ollama": "hima-ollama-1", "advisor": "hima-advisor-1", "webui": "hima-webui-1"},
    )
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions(backend=services.ServiceBackend.DOCKER), skip_pull=True)

    manifest = written["manifest"]
    assert manifest.backend is services.ServiceBackend.DOCKER
    assert manifest.leader_endpoint == "http://localhost:11434/v1"
    assert manifest.services["advisor"] == services.DockerService(
        endpoint="http://localhost:8090", container="hima-advisor-1"
    )


def test_up_manifest_out_writes_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = SimpleNamespace(backend=services.ServiceBackend.NATIVE)
    paths: list[Path] = []
    monkeypatch.setattr(_lifecycle, "_up_native", lambda options, skip_pull: manifest)
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=services.MANIFEST_FILE: paths.append(path),
    )

    services.up(services.ServiceOptions(), skip_pull=True, manifest_out=tmp_path / "m.toml")

    assert paths == [services.MANIFEST_FILE, tmp_path / "m.toml"]


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


def test_docker_leader_model_absent_skip_pull_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_docker, "leader_model_present", lambda root, model: False)

    with pytest.raises(CommandError, match="docker compose exec"):
        _docker.ensure_leader_model("qwen3:8b", skip_pull=True, ollama_port=11434)


def test_down_docker_stops_compose_and_removes_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manifest = SimpleNamespace(backend=services.ServiceBackend.DOCKER)
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_docker, "compose_stop", lambda: events.append("compose-stop"))
    monkeypatch.setattr(_lifecycle, "remove_manifest", lambda: events.append("remove"))

    services.down()

    assert events == ["compose-stop", "remove"]


def test_down_without_manifest_sweeps_native_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped: list[str] = []
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: None)
    monkeypatch.setattr(_native, "stop_one", lambda spec: stopped.append(spec.name))
    monkeypatch.setattr(_lifecycle, "remove_manifest", lambda: None)

    services.down()

    assert stopped == ["webui", "advisor", "ollama"]


def test_leader_models_lists_openai_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "llama3:8b"}]}

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        requested["url"] = url
        requested["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("hima_dht_cli.services._health.requests.get", fake_get)

    served = services.leader_models("http://localhost:11434/v1", "secret")

    assert served == ["qwen3:8b", "llama3:8b"]
    assert requested["url"] == "http://localhost:11434/v1/models"
    assert requested["headers"] == {"Authorization": "Bearer secret"}


def test_leader_models_none_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, headers: dict[str, str], timeout: int) -> None:
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("hima_dht_cli.services._health.requests.get", fake_get)

    assert services.leader_models("http://localhost:11434/v1", "ollama") is None


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
