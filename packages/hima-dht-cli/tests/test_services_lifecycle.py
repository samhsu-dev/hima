"""Unit tests for hima_dht_cli.services._lifecycle (up/down/status dispatch).

Test cases:
- test_up_native_ensures_services_in_dependency_order: the default leader
  base URL provisions ollama, the leader model, the advisor, then the
  webui, and records a native manifest.
- test_up_native_override_skips_provisioning_and_verifies: an overridden
  leader base URL provisions no ollama; the endpoint is verified and
  recorded in the manifest instead.
- test_up_native_override_unreachable_raises: an unreachable overridden
  endpoint aborts `up` naming HIMA_LEADER_BASE_URL.
- test_up_docker_records_container_manifest: the docker backend delegates
  to compose and records container entries with host endpoints.
- test_up_docker_published_port_divergence_raises: a compose-published
  ollama port differing from the requested one aborts `up` and points
  at HIMA_OLLAMA_PORT.
- test_up_manifest_out_writes_copy: --manifest-out writes the manifest to
  the default location and to the requested path.
- test_down_docker_stops_compose_and_removes_manifest: a docker manifest
  routes `down` to compose stop and removes the manifest.
- test_down_without_manifest_sweeps_native_in_reverse_order: no manifest
  sweeps webui, advisor, then ollama pid files.
- test_down_blocked_by_held_service_lock: a held service lock makes
  `down` raise instead of racing the holder.
- test_status_probes_manifest_endpoints: status probes every recorded
  service, checks the recorded leader endpoint via GET /models, and the
  game image on the docker backend — nothing from options.
- test_status_flags_foreign_endpoint_with_dead_pid: a reachable endpoint
  whose recorded pid is gone fails the check as a foreign process.
"""

import fcntl
from pathlib import Path
from types import SimpleNamespace

import pytest

from hima_dht_cli import services
from hima_dht_cli.errors import CommandError
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


def test_up_native_override_skips_provisioning_and_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    queried: dict[str, tuple[str, str]] = {}
    written: dict[str, services.ServiceManifest] = {}

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        queried["endpoint"] = (base_url, api_key)
        return ["qwen3:8b"]

    monkeypatch.setattr(_native, "ensure_service", lambda spec: order.append(spec.name) or 4321)
    monkeypatch.setattr(_lifecycle, "leader_models", fake_leader_models)
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )
    options = services.ServiceOptions(leader_base_url="http://127.0.0.1:11434/v1")

    services.up(options, skip_pull=True)

    assert order == ["advisor", "webui"]
    assert queried["endpoint"] == ("http://127.0.0.1:11434/v1", "ollama")
    assert written["manifest"].endpoints["leader"] == services.ModelEndpoint(
        url="http://127.0.0.1:11434/v1", model="qwen3:8b"
    )


def test_up_native_override_unreachable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_lifecycle, "leader_models", lambda base_url, api_key: None)

    with pytest.raises(CommandError, match="HIMA_LEADER_BASE_URL"):
        services.up(
            services.ServiceOptions(leader_base_url="https://api.example.com/v1"), skip_pull=True
        )


def test_up_docker_records_container_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, services.ServiceManifest] = {}
    monkeypatch.setattr(_docker, "compose_up", lambda: None)
    monkeypatch.setattr(_docker, "published_ollama_port", lambda: 11434)
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
    assert manifest.endpoints["leader"] == services.ModelEndpoint(
        url="http://localhost:11434/v1", model="qwen3:8b"
    )
    assert manifest.services["advisor"] == services.DockerService(
        endpoint="http://localhost:8090", container="hima-advisor-1"
    )


def test_up_docker_published_port_divergence_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_docker, "compose_up", lambda: None)
    monkeypatch.setattr(_docker, "published_ollama_port", lambda: 12345)

    with pytest.raises(CommandError, match="HIMA_OLLAMA_PORT"):
        services.up(services.ServiceOptions(backend=services.ServiceBackend.DOCKER), skip_pull=True)


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


def test_down_blocked_by_held_service_lock() -> None:
    # flock conflicts between two open file descriptions even within one
    # process, so holding the lock here blocks the `down` call.
    _lifecycle.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_lifecycle.LOCK_FILE, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(CommandError, match="service lock"):
            services.down()


def _docker_manifest(ollama_endpoint: str) -> services.ServiceManifest:
    return services.ServiceManifest(
        backend=services.ServiceBackend.DOCKER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": services.ModelEndpoint(url=f"{ollama_endpoint}/v1", model="qwen3:8b")},
        services={
            "ollama": services.DockerService(endpoint=ollama_endpoint, container="hima-ollama-1"),
            "advisor": services.DockerService(
                endpoint="http://localhost:8090", container="hima-advisor-1"
            ),
            "webui": services.DockerService(
                endpoint="http://localhost:8080", container="hima-webui-1"
            ),
        },
    )


def test_status_probes_manifest_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    probed: list[str] = []
    queried: list[tuple[str, str]] = []

    def fake_healthy(url: str) -> bool:
        probed.append(url)
        return True

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        queried.append((base_url, api_key))
        return ["qwen3:8b"]

    manifest = _docker_manifest("http://localhost:12345")
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_lifecycle, "healthy", fake_healthy)
    monkeypatch.setattr(_lifecycle, "leader_models", fake_leader_models)
    monkeypatch.setattr(_docker, "game_image_present", lambda: True)

    assert services.status(services.ServiceOptions()) is True
    assert probed == [
        "http://localhost:12345/api/tags",
        "http://localhost:8090/health",
        "http://localhost:8080/api/games",
    ]
    assert queried == [("http://localhost:12345/v1", "ollama")]


def test_status_flags_foreign_endpoint_with_dead_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A pid far above the platform pid limit is guaranteed dead.
    manifest = services.ServiceManifest(
        backend=services.ServiceBackend.NATIVE,
        created="2026-08-07T12:00:00+09:00",
        endpoints={
            "leader": services.ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")
        },
        services={
            "ollama": services.NativeService(
                endpoint="http://localhost:11434",
                pid=4_194_304,
                pid_file="tmp/services/ollama.pid",
                log_file="tmp/services/ollama.log",
            )
        },
    )
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_lifecycle, "healthy", lambda url: True)
    monkeypatch.setattr(_lifecycle, "leader_models", lambda base_url, api_key: ["qwen3:8b"])
    monkeypatch.setattr(_lifecycle, "SC2_APP", tmp_path)

    assert services.status(services.ServiceOptions()) is False
    assert "foreign process" in capsys.readouterr().out
