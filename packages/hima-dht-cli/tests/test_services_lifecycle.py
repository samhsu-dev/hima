"""Unit tests for hima_dht_cli.services._lifecycle (up/down/status dispatch).

Test cases:
- test_up_host_verifies_leader_then_starts_advisor_only: `up` verifies the
  leader endpoint, starts the advisor alone, and records the verified
  endpoint in a host manifest.
- test_up_host_with_webui_starts_both_services: `--webui` adds the
  observation server to the managed set, in launch order.
- test_up_host_unreachable_leader_raises: an unreachable leader endpoint
  aborts `up` naming HIMA_LEADER_BASE_URL, before any service starts.
- test_up_host_unserved_model_raises: a reachable endpoint not serving
  the requested model aborts `up` naming the model.
- test_up_container_records_container_manifest: the container placement
  verifies the leader endpoint, delegates the advisor to compose, and
  records container entries with host endpoints.
- test_up_container_with_webui_selects_both_services: `--webui` adds the
  webui to the compose invocation and to the manifest.
- test_up_manifest_out_writes_copy: --manifest-out writes the manifest to
  the default location and to the requested path.
- test_down_container_stops_recorded_services: a container manifest
  routes `down` to compose stop of the recorded services and removes the
  manifest.
- test_down_without_manifest_sweeps_host_in_reverse_order: no manifest
  sweeps the webui then the advisor pid file.
- test_down_blocked_by_held_service_lock: a held service lock makes
  `down` raise instead of racing the holder.
- test_status_probes_manifest_endpoints: status probes every recorded
  service and checks the recorded leader endpoint via GET /models —
  nothing from options.
- test_status_checks_the_game_placement_not_the_service_placement: host
  services with a container game check the game image, never the SC2
  installation.
- test_status_flags_foreign_endpoint_with_dead_pid: a reachable endpoint
  whose recorded pid is gone fails the check as a foreign process.
"""

import fcntl
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from hima_dht_cli import services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.placement import Placement
from hima_dht_cli.services import _docker, _host, _lifecycle


def _serving_leader(base_url: str, api_key: str) -> list[str]:
    return ["qwen3:8b"]


def test_up_host_verifies_leader_then_starts_advisor_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    queried: dict[str, tuple[str, str]] = {}
    written: dict[str, services.ServiceManifest] = {}

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        queried["endpoint"] = (base_url, api_key)
        return ["qwen3:8b"]

    def fake_ensure_service(spec: services.ServiceSpec) -> int:
        order.append(spec.name)
        return 4321

    monkeypatch.setattr(_host, "ensure_service", fake_ensure_service)
    monkeypatch.setattr(_lifecycle, "leader_models", fake_leader_models)
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions())

    assert order == ["advisor"]
    assert queried["endpoint"] == ("http://localhost:11434/v1", "ollama")
    assert written["manifest"].placement is Placement.HOST
    assert written["manifest"].endpoints["leader"] == services.ModelEndpoint(
        url="http://localhost:11434/v1", model="qwen3:8b"
    )


def test_up_host_with_webui_starts_both_services(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    written: dict[str, services.ServiceManifest] = {}

    def fake_ensure_service(spec: services.ServiceSpec) -> int:
        order.append(spec.name)
        return 4321

    monkeypatch.setattr(_host, "ensure_service", fake_ensure_service)
    monkeypatch.setattr(_lifecycle, "leader_models", _serving_leader)
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions(webui=True))

    assert order == ["advisor", "webui"]
    assert set(written["manifest"].services) == {"advisor", "webui"}


def test_up_host_unreachable_leader_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_lifecycle, "leader_models", lambda base_url, api_key: None)
    monkeypatch.setattr(
        _host, "ensure_service", lambda spec: pytest.fail("no service starts before verification")
    )

    with pytest.raises(CommandError, match="HIMA_LEADER_BASE_URL"):
        services.up(services.ServiceOptions(leader_base_url="https://api.example.com/v1"))


def test_up_host_unserved_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_lifecycle, "leader_models", lambda base_url, api_key: ["llama3:8b"])

    with pytest.raises(CommandError, match="qwen3:8b"):
        services.up(services.ServiceOptions())


def test_up_container_records_container_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, services.ServiceManifest] = {}
    started: list[Sequence[str]] = []

    monkeypatch.setattr(_lifecycle, "leader_models", _serving_leader)
    monkeypatch.setattr(_docker, "compose_up", lambda names: started.append(names))
    monkeypatch.setattr(
        _docker,
        "container_names",
        lambda names: {"advisor": "hima-advisor-1"},
    )
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions(placement=Placement.CONTAINER))

    manifest = written["manifest"]
    assert started == [("advisor",)]
    assert manifest.placement is Placement.CONTAINER
    assert manifest.services["advisor"] == services.ContainerService(
        endpoint="http://localhost:8090", container="hima-advisor-1"
    )


def test_up_container_with_webui_selects_both_services(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, services.ServiceManifest] = {}
    started: list[Sequence[str]] = []

    monkeypatch.setattr(_lifecycle, "leader_models", _serving_leader)
    monkeypatch.setattr(_docker, "compose_up", lambda names: started.append(names))
    monkeypatch.setattr(
        _docker,
        "container_names",
        lambda names: {"advisor": "hima-advisor-1", "webui": "hima-webui-1"},
    )
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=None: written.update(manifest=manifest),
    )

    services.up(services.ServiceOptions(placement=Placement.CONTAINER, webui=True))

    assert started == [("advisor", "webui")]
    assert set(written["manifest"].services) == {"advisor", "webui"}


def test_up_manifest_out_writes_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = SimpleNamespace(placement=Placement.HOST)
    paths: list[Path] = []
    monkeypatch.setattr(_lifecycle, "_up_host", lambda options: manifest)
    monkeypatch.setattr(
        _lifecycle,
        "write_manifest",
        lambda manifest, path=services.MANIFEST_FILE: paths.append(path),
    )

    services.up(services.ServiceOptions(), manifest_out=tmp_path / "m.toml")

    assert paths == [services.MANIFEST_FILE, tmp_path / "m.toml"]


def test_down_container_stops_recorded_services(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[object] = []
    manifest = SimpleNamespace(placement=Placement.CONTAINER, services={"advisor": None})
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_docker, "compose_stop", lambda names: events.append(names))
    monkeypatch.setattr(_lifecycle, "remove_manifest", lambda: events.append("remove"))

    services.down()

    assert events == [("advisor",), "remove"]


def test_down_without_manifest_sweeps_host_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped: list[str] = []
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: None)
    monkeypatch.setattr(_host, "stop_one", lambda spec: stopped.append(spec.name))
    monkeypatch.setattr(_lifecycle, "remove_manifest", lambda: None)

    services.down()

    assert stopped == ["webui", "advisor"]


def test_down_blocked_by_held_service_lock() -> None:
    # flock conflicts between two open file descriptions even within one
    # process, so holding the lock here blocks the `down` call.
    _lifecycle.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_lifecycle.LOCK_FILE, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(CommandError, match="service lock"):
            services.down()


def _container_manifest(leader_url: str) -> services.ServiceManifest:
    return services.ServiceManifest(
        placement=Placement.CONTAINER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": services.ModelEndpoint(url=leader_url, model="qwen3:8b")},
        services={
            "advisor": services.ContainerService(
                endpoint="http://localhost:8090", container="hima-advisor-1"
            ),
            "webui": services.ContainerService(
                endpoint="http://localhost:8080", container="hima-webui-1"
            ),
        },
    )


def test_status_probes_manifest_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    probed: list[str] = []
    queried: list[tuple[str, str]] = []

    def fake_service_healthy(name: str, endpoint: str) -> bool:
        probed.append(f"{endpoint} {name}")
        return True

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        queried.append((base_url, api_key))
        return ["qwen3:8b"]

    manifest = _container_manifest("http://localhost:12345/v1")
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_lifecycle, "service_healthy", fake_service_healthy)
    monkeypatch.setattr(_lifecycle, "leader_models", fake_leader_models)
    monkeypatch.setattr(_docker, "game_image_present", lambda: True)

    assert services.status(services.ServiceOptions()) is True
    assert probed == [
        "http://localhost:8090 advisor",
        "http://localhost:8080 webui",
    ]
    assert queried == [("http://localhost:12345/v1", "ollama")]


def test_status_checks_the_game_placement_not_the_service_placement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Host services with a container game: the runtime check follows the
    # game axis, so a machine without StarCraft II still passes.
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: None)
    monkeypatch.setattr(_lifecycle, "service_healthy", lambda name, endpoint: True)
    monkeypatch.setattr(_lifecycle, "leader_models", _serving_leader)
    monkeypatch.setattr(_docker, "game_image_present", lambda: True)

    assert services.status(services.ServiceOptions(), Placement.CONTAINER) is True
    assert "game image" in capsys.readouterr().out


def test_status_flags_foreign_endpoint_with_dead_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A pid far above the platform pid limit is guaranteed dead.
    manifest = services.ServiceManifest(
        placement=Placement.HOST,
        created="2026-08-07T12:00:00+09:00",
        endpoints={
            "leader": services.ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")
        },
        services={
            "advisor": services.HostService(
                endpoint="http://localhost:8090",
                pid=4_194_304,
                pid_file="tmp/services/advisor.pid",
                log_file="tmp/services/advisor.log",
            )
        },
    )
    monkeypatch.setattr(_lifecycle, "read_manifest", lambda: manifest)
    monkeypatch.setattr(_lifecycle, "service_healthy", lambda name, endpoint: True)
    monkeypatch.setattr(_lifecycle, "leader_models", lambda base_url, api_key: ["qwen3:8b"])
    monkeypatch.setattr(_lifecycle, "SC2_APP", tmp_path)

    assert services.status(services.ServiceOptions(), Placement.HOST) is False
    assert "foreign process" in capsys.readouterr().out
