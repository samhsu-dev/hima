"""Service lifecycle orchestration: placement dispatch for up/down/status."""

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from hima_dht_cli.errors import CommandError
from hima_dht_cli.placement import Placement
from hima_dht_cli.workspace import SC2_APP, SERVICE_DIR
from hima_dht_web.server import DEFAULT_PORT as DEFAULT_WEBUI_PORT

from . import _docker, _host
from ._health import ADVISOR, WEBUI, leader_models, model_served, service_healthy
from ._manifest import (
    MANIFEST_FILE,
    ContainerService,
    HostService,
    ModelEndpoint,
    ServiceManifest,
    read_manifest,
    remove_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)

DEFAULT_ADVISOR_PORT = 8090
DEFAULT_LEADER_MODEL = "qwen3:8b"
# Ollama accepts any bearer token; a remote provider needs its real key.
DEFAULT_LEADER_API_KEY = "ollama"
# The OpenAI-compatible endpoint of a host Ollama on its own default port;
# the engine is operator-owned, hima only verifies this URL.
DEFAULT_LEADER_BASE_URL = "http://localhost:11434/v1"

# Serializes `up` and `down`; two concurrent runs would race on pid
# files and the manifest.
LOCK_FILE = SERVICE_DIR / "up-down.lock"


@dataclass(frozen=True)
class ServiceOptions:
    """Placement, service set, endpoints, and model for the managed services."""

    placement: Placement = Placement.HOST
    webui: bool = False
    advisor_port: int = DEFAULT_ADVISOR_PORT
    webui_port: int = DEFAULT_WEBUI_PORT
    model: str = DEFAULT_LEADER_MODEL
    leader_base_url: str = DEFAULT_LEADER_BASE_URL
    leader_api_key: str = DEFAULT_LEADER_API_KEY


def up(options: ServiceOptions, manifest_out: Path | None = None) -> None:
    """Start the managed services at the selected placement and record the manifest."""
    with _mutual_exclusion():
        if options.placement is Placement.CONTAINER:
            manifest = _up_container(options)
        else:
            manifest = _up_host(options)
        write_manifest(manifest)
        if manifest_out is not None:
            write_manifest(manifest, manifest_out)
    print(f"all services healthy; manifest: {MANIFEST_FILE}")


def down() -> None:
    """Stop the services recorded by the last `up` and remove the manifest."""
    with _mutual_exclusion():
        manifest = read_manifest()
        if manifest is not None and manifest.placement is Placement.CONTAINER:
            _docker.compose_stop(tuple(manifest.services))
        else:
            _stop_host(manifest)
        remove_manifest()


def _stop_host(manifest: ServiceManifest | None) -> None:
    if manifest is None:
        logger.info("no service manifest: sweeping host pid files")
    # Reverse launch order, and every known service: a pid file left by an
    # interrupted `up` is swept even when the manifest omits the service.
    for spec in (
        _host.webui_spec(DEFAULT_WEBUI_PORT),
        _host.advisor_spec(DEFAULT_ADVISOR_PORT),
    ):
        _host.stop_one(spec)


@contextmanager
def _mutual_exclusion() -> Iterator[None]:
    # flock releases on close or process exit, so a crashed holder never
    # wedges the lock.
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CommandError(
                "another `hima up` or `hima down` holds the service lock; wait for it to finish"
            ) from error
        yield


def status(options: ServiceOptions, game: Placement = Placement.CONTAINER) -> bool:
    """Print the manifest record and one line per check; True when all pass.

    `game` is the placement the next `hima run` will use; the game runtime
    check follows it, never the service placement — the two are
    independent axes.

    Raises:
        CommandError: the recorded manifest is corrupt or has an
            unreadable version.
    """
    manifest = read_manifest()
    if manifest is None:
        print("manifest: none (`hima up` has not recorded services)")
    else:
        print(
            f"manifest: placement={manifest.placement.value} "
            f"created={manifest.created} ({MANIFEST_FILE})"
        )
    checks = _collect_checks(options, manifest, game)
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"{mark} {name}: {detail}")
    return all(ok for _, ok, _ in checks)


def _collect_checks(
    options: ServiceOptions, manifest: ServiceManifest | None, game: Placement
) -> list[tuple[str, bool, str]]:
    # The manifest is the source of truth for what `up` started; options
    # only fill in when no `up` has recorded services.
    if manifest is None:
        return _option_checks(options, game)
    checks = [
        _service_check(name, entry.endpoint, entry) for name, entry in manifest.services.items()
    ]
    checks.append(_leader_check(manifest.endpoints.get("leader"), options.leader_api_key))
    checks.append(_game_runtime_check(game))
    return checks


def _option_checks(options: ServiceOptions, game: Placement) -> list[tuple[str, bool, str]]:
    endpoints = _endpoints(options)
    checks = [_service_check(name, endpoints[name], None) for name in _managed(options)]
    leader = ModelEndpoint(url=options.leader_base_url, model=options.model)
    checks.append(_leader_check(leader, options.leader_api_key))
    checks.append(_game_runtime_check(game))
    return checks


def _managed(options: ServiceOptions) -> tuple[str, ...]:
    """Names of the services this `up` manages, in launch order."""
    return (ADVISOR, WEBUI) if options.webui else (ADVISOR,)


def _leader_check(endpoint: ModelEndpoint | None, api_key: str) -> tuple[str, bool, str]:
    if endpoint is None:
        return ("leader", False, "no leader endpoint recorded in the manifest")
    served = leader_models(endpoint.url, api_key)
    if served is None:
        return ("leader", False, f"{endpoint.url} unreachable")
    if not model_served(endpoint.model, served):
        return ("leader", False, f"{endpoint.url} does not serve model {endpoint.model}")
    return ("leader", True, f"{endpoint.url} model={endpoint.model}")


def _game_runtime_check(game: Placement) -> tuple[str, bool, str]:
    if game is Placement.CONTAINER:
        present = _docker.game_image_present()
        detail = (
            _docker.GAME_IMAGE
            if present
            else f"image {_docker.GAME_IMAGE} absent — `hima run --game container` builds it"
        )
        return ("game image", present, detail)
    return ("StarCraft II", SC2_APP.exists(), str(SC2_APP))


def _service_check(
    name: str, endpoint: str, entry: HostService | ContainerService | None
) -> tuple[str, bool, str]:
    reachable = service_healthy(name, endpoint)
    if isinstance(entry, HostService):
        return _host_check(name, endpoint, reachable, entry)
    if isinstance(entry, ContainerService):
        return (name, reachable, f"{endpoint} container={entry.container}")
    return (name, reachable, endpoint)


def _host_check(
    name: str, endpoint: str, reachable: bool, entry: HostService
) -> tuple[str, bool, str]:
    # A reachable endpoint with a dead recorded pid is a foreign process
    # shadowing the service, not a healthy service.
    alive = psutil.pid_exists(entry.pid)
    if reachable and not alive:
        detail = f"{endpoint} answers but recorded pid {entry.pid} is gone (foreign process)"
        return (name, False, detail)
    suffix = "" if alive else " (exited)"
    return (name, reachable and alive, f"{endpoint} pid={entry.pid}{suffix}")


def _verify_leader_endpoint(options: ServiceOptions) -> None:
    served = leader_models(options.leader_base_url, options.leader_api_key)
    if served is None:
        raise CommandError(
            f"leader endpoint not reachable at {options.leader_base_url} — start an "
            f"OpenAI-compatible server there (e.g. `brew services start ollama`) or "
            f"point HIMA_LEADER_BASE_URL at your provider"
        )
    if not model_served(options.model, served):
        raise CommandError(
            f"leader model {options.model} not served at {options.leader_base_url} — "
            f"pull it there (`ollama pull {options.model}`) or check "
            f"--model / HIMA_LEADER_MODEL"
        )


def _up_host(options: ServiceOptions) -> ServiceManifest:
    # The leader engine is operator-owned at every placement; hima verifies
    # its endpoint and never spawns one (design-deployment.md).
    _verify_leader_endpoint(options)
    specs = {name: _spec(name, options) for name in _managed(options)}
    pids = {name: _host.ensure_service(spec) for name, spec in specs.items()}
    return _record(Placement.HOST, options, _host_entries(options, specs, pids))


def _spec(name: str, options: ServiceOptions) -> _host.ServiceSpec:
    if name == WEBUI:
        return _host.webui_spec(options.webui_port)
    return _host.advisor_spec(options.advisor_port)


def _host_entries(
    options: ServiceOptions, specs: dict[str, _host.ServiceSpec], pids: dict[str, int]
) -> dict[str, HostService | ContainerService]:
    endpoints = _endpoints(options)
    return {
        name: HostService(
            endpoint=endpoints[name],
            pid=pids[name],
            pid_file=str(spec.pid_file),
            log_file=str(spec.log_file),
        )
        for name, spec in specs.items()
    }


def _up_container(options: ServiceOptions) -> ServiceManifest:
    # The container placement never provisions the leader engine; every
    # leader URL is verified as an external endpoint (design-cli-services.md).
    _verify_leader_endpoint(options)
    names = _managed(options)
    _docker.compose_up(names)
    containers = _docker.container_names(names)
    endpoints = _endpoints(options)
    entries: dict[str, HostService | ContainerService] = {
        name: ContainerService(endpoint=endpoints[name], container=container)
        for name, container in containers.items()
    }
    return _record(Placement.CONTAINER, options, entries)


def _endpoints(options: ServiceOptions) -> dict[str, str]:
    return {
        ADVISOR: f"http://localhost:{options.advisor_port}",
        WEBUI: f"http://localhost:{options.webui_port}",
    }


def _record(
    placement: Placement,
    options: ServiceOptions,
    entries: dict[str, HostService | ContainerService],
) -> ServiceManifest:
    return ServiceManifest(
        placement=placement,
        created=datetime.now().astimezone().isoformat(timespec="seconds"),
        endpoints={"leader": ModelEndpoint(url=options.leader_base_url, model=options.model)},
        services=entries,
    )
