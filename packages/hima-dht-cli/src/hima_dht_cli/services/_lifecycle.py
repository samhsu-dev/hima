"""Service lifecycle orchestration: backend dispatch for up/down/status."""

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import SC2_APP, SERVICE_DIR
from hima_dht_web.server import DEFAULT_PORT as DEFAULT_WEBUI_PORT

from . import _docker, _native
from ._health import HEALTH_PATHS, healthy, leader_models, model_served, ollama_url
from ._manifest import (
    MANIFEST_FILE,
    DockerService,
    ModelEndpoint,
    NativeService,
    ServiceBackend,
    ServiceManifest,
    read_manifest,
    remove_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)

DEFAULT_ADVISOR_PORT = 8090
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_LEADER_MODEL = "qwen3:8b"
# Ollama accepts any bearer token; a remote provider needs its real key.
DEFAULT_LEADER_API_KEY = "ollama"

# Serializes `up` and `down`; two concurrent runs would race on pid
# files and the manifest.
LOCK_FILE = SERVICE_DIR / "up-down.lock"


def _local_leader_url(ollama_port: int) -> str:
    # The OpenAI-compatible base URL of a locally provisioned `ollama serve`.
    return f"http://localhost:{ollama_port}/v1"


DEFAULT_LEADER_BASE_URL = _local_leader_url(DEFAULT_OLLAMA_PORT)


@dataclass(frozen=True)
class ServiceOptions:
    """Backend, endpoint, and model selection for the managed services."""

    backend: ServiceBackend = ServiceBackend.NATIVE
    advisor_port: int = DEFAULT_ADVISOR_PORT
    webui_port: int = DEFAULT_WEBUI_PORT
    ollama_port: int = DEFAULT_OLLAMA_PORT
    model: str = DEFAULT_LEADER_MODEL
    leader_base_url: str = DEFAULT_LEADER_BASE_URL
    leader_api_key: str = DEFAULT_LEADER_API_KEY


def up(options: ServiceOptions, skip_pull: bool, manifest_out: Path | None = None) -> None:
    """Start the managed services on the selected backend and record the manifest."""
    with _mutual_exclusion():
        if options.backend is ServiceBackend.DOCKER:
            manifest = _up_docker(options)
        else:
            manifest = _up_native(options, skip_pull)
        write_manifest(manifest)
        if manifest_out is not None:
            write_manifest(manifest, manifest_out)
    print(f"all services healthy; manifest: {MANIFEST_FILE}")


def down() -> None:
    """Stop the services recorded by the last `up` and remove the manifest."""
    with _mutual_exclusion():
        manifest = read_manifest()
        if manifest is not None and manifest.backend is ServiceBackend.DOCKER:
            _docker.compose_stop()
        else:
            if manifest is None:
                logger.info("no service manifest: sweeping native pid files")
            for spec in (
                _native.webui_spec(DEFAULT_WEBUI_PORT),
                _native.advisor_spec(DEFAULT_ADVISOR_PORT),
                _native.ollama_spec(DEFAULT_OLLAMA_PORT),
            ):
                _native.stop_one(spec)
        remove_manifest()


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


def status(options: ServiceOptions) -> bool:
    """Print the manifest record and one line per check; True when all pass.

    Raises:
        CommandError: the recorded manifest is corrupt or has an
            unreadable version.
    """
    manifest = read_manifest()
    if manifest is None:
        print("manifest: none (`hima up` has not recorded services)")
    else:
        print(
            f"manifest: backend={manifest.backend.value} "
            f"created={manifest.created} ({MANIFEST_FILE})"
        )
    checks = _collect_checks(options, manifest)
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"{mark} {name}: {detail}")
    return all(ok for _, ok, _ in checks)


def _collect_checks(
    options: ServiceOptions, manifest: ServiceManifest | None
) -> list[tuple[str, bool, str]]:
    # The manifest is the source of truth for what `up` started; options
    # only fill in when no `up` has recorded services.
    if manifest is None:
        return _option_checks(options)
    checks = [
        _service_check(name, entry.endpoint, entry) for name, entry in manifest.services.items()
    ]
    checks.append(_leader_check(manifest.endpoints.get("leader"), options.leader_api_key))
    checks.append(_game_runtime_check(manifest.backend))
    return checks


def _option_checks(options: ServiceOptions) -> list[tuple[str, bool, str]]:
    endpoints = _endpoints(options)
    checks = [_service_check(name, endpoints[name], None) for name in ("advisor", "webui")]
    leader = ModelEndpoint(url=options.leader_base_url, model=options.model)
    checks.append(_leader_check(leader, options.leader_api_key))
    checks.append(_game_runtime_check(ServiceBackend.NATIVE))
    return checks


def _leader_check(endpoint: ModelEndpoint | None, api_key: str) -> tuple[str, bool, str]:
    if endpoint is None:
        return ("leader", False, "no leader endpoint recorded in the manifest")
    served = leader_models(endpoint.url, api_key)
    if served is None:
        return ("leader", False, f"{endpoint.url} unreachable")
    if not model_served(endpoint.model, served):
        return ("leader", False, f"{endpoint.url} does not serve model {endpoint.model}")
    return ("leader", True, f"{endpoint.url} model={endpoint.model}")


def _game_runtime_check(backend: ServiceBackend) -> tuple[str, bool, str]:
    if backend is ServiceBackend.DOCKER:
        present = _docker.game_image_present()
        detail = (
            _docker.GAME_IMAGE
            if present
            else f"image {_docker.GAME_IMAGE} absent — `hima run --headless` builds it"
        )
        return ("game image", present, detail)
    return ("StarCraft II", SC2_APP.exists(), str(SC2_APP))


def _service_check(
    name: str, endpoint: str, entry: NativeService | DockerService | None
) -> tuple[str, bool, str]:
    health = f"{endpoint}{HEALTH_PATHS[name]}"
    if isinstance(entry, NativeService):
        return _native_check(name, health, entry)
    if isinstance(entry, DockerService):
        return (name, healthy(health), f"{health} container={entry.container}")
    return (name, healthy(health), health)


def _native_check(name: str, health: str, entry: NativeService) -> tuple[str, bool, str]:
    # A reachable endpoint with a dead recorded pid is a foreign process
    # shadowing the service, not a healthy service.
    reachable = healthy(health)
    alive = psutil.pid_exists(entry.pid)
    if reachable and not alive:
        detail = f"{health} answers but recorded pid {entry.pid} is gone (foreign process)"
        return (name, False, detail)
    suffix = "" if alive else " (exited)"
    return (name, reachable and alive, f"{health} pid={entry.pid}{suffix}")


def _provisions_leader(options: ServiceOptions) -> bool:
    # Textual comparison is the contract: any override — even an equivalent
    # spelling of the local default — selects verify-only against an
    # external endpoint instead of provisioning `ollama serve`.
    return options.leader_base_url == _local_leader_url(options.ollama_port)


def _verify_leader_endpoint(options: ServiceOptions) -> None:
    served = leader_models(options.leader_base_url, options.leader_api_key)
    if served is None:
        raise CommandError(
            f"leader endpoint not reachable at {options.leader_base_url} — start an "
            f"OpenAI-compatible server there (e.g. `ollama serve`) or point "
            f"HIMA_LEADER_BASE_URL at your provider"
        )
    if not model_served(options.model, served):
        raise CommandError(
            f"leader model {options.model} not served at {options.leader_base_url} — "
            f"pull it there or check --model / HIMA_LEADER_MODEL"
        )


def _up_native(options: ServiceOptions, skip_pull: bool) -> ServiceManifest:
    specs: dict[str, _native.ServiceSpec] = {}
    pids: dict[str, int] = {}
    if _provisions_leader(options):
        specs["ollama"] = _native.ollama_spec(options.ollama_port)
        pids["ollama"] = _native.ensure_service(specs["ollama"])
        _native.ensure_leader_model(options.model, skip_pull, options.ollama_port)
    else:
        _verify_leader_endpoint(options)
    specs["advisor"] = _native.advisor_spec(options.advisor_port)
    specs["webui"] = _native.webui_spec(options.webui_port)
    pids["advisor"] = _native.ensure_service(specs["advisor"])
    pids["webui"] = _native.ensure_service(specs["webui"])
    return _record(ServiceBackend.NATIVE, options, _native_entries(options, specs, pids))


def _native_entries(
    options: ServiceOptions, specs: dict[str, _native.ServiceSpec], pids: dict[str, int]
) -> dict[str, NativeService | DockerService]:
    endpoints = _endpoints(options)
    return {
        name: NativeService(
            endpoint=endpoints[name],
            pid=pids[name],
            pid_file=str(spec.pid_file),
            log_file=str(spec.log_file),
        )
        for name, spec in specs.items()
    }


def _up_docker(options: ServiceOptions) -> ServiceManifest:
    # The docker backend never provisions the leader engine; every leader
    # URL is verified as an external endpoint (design-cli-services.md).
    _verify_leader_endpoint(options)
    _docker.compose_up()
    containers = _docker.container_names()
    endpoints = _endpoints(options)
    entries: dict[str, NativeService | DockerService] = {
        name: DockerService(endpoint=endpoints[name], container=container)
        for name, container in containers.items()
    }
    return _record(ServiceBackend.DOCKER, options, entries)


def _endpoints(options: ServiceOptions) -> dict[str, str]:
    return {
        "ollama": ollama_url(options.ollama_port),
        "advisor": f"http://localhost:{options.advisor_port}",
        "webui": f"http://localhost:{options.webui_port}",
    }


def _record(
    backend: ServiceBackend,
    options: ServiceOptions,
    entries: dict[str, NativeService | DockerService],
) -> ServiceManifest:
    return ServiceManifest(
        backend=backend,
        created=datetime.now().astimezone().isoformat(timespec="seconds"),
        endpoints={"leader": ModelEndpoint(url=options.leader_base_url, model=options.model)},
        services=entries,
    )
