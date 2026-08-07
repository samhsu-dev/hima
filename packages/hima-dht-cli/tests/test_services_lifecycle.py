"""Unit tests for hima_dht_cli.services._lifecycle (up/down/status dispatch).

Test cases:
- test_up_native_ensures_services_in_dependency_order: the native backend
  ensures ollama, the leader model, the advisor, then the webui, and
  records a native manifest.
- test_up_docker_records_container_manifest: the docker backend delegates
  to compose and records container entries with host endpoints.
- test_up_manifest_out_writes_copy: --manifest-out writes the manifest to
  the default location and to the requested path.
- test_down_docker_stops_compose_and_removes_manifest: a docker manifest
  routes `down` to compose stop and removes the manifest.
- test_down_without_manifest_sweeps_native_in_reverse_order: no manifest
  sweeps webui, advisor, then ollama pid files.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from hima_dht_cli import services
from hima_dht_cli.services import _docker, _lifecycle, _native


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
