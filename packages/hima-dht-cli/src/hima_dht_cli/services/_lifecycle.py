"""Service lifecycle orchestration: backend dispatch for up/down/status."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hima_dht_cli.workspace import SC2_APP
from hima_dht_web.server import DEFAULT_PORT as DEFAULT_WEBUI_PORT

from . import _docker, _native
from ._health import healthy, leader_model_present, ollama_url
from ._manifest import (
    MANIFEST_FILE,
    DockerService,
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


@dataclass(frozen=True)
class ServiceOptions:
    """Backend, endpoint, and model selection for the managed services."""

    backend: ServiceBackend = ServiceBackend.NATIVE
    advisor_port: int = DEFAULT_ADVISOR_PORT
    webui_port: int = DEFAULT_WEBUI_PORT
    ollama_port: int = DEFAULT_OLLAMA_PORT
    model: str = DEFAULT_LEADER_MODEL


def up(options: ServiceOptions, skip_pull: bool, manifest_out: Path | None = None) -> None:
    """Start the service trio on the selected backend and record the manifest."""
    if options.backend is ServiceBackend.DOCKER:
        manifest = _up_docker(options, skip_pull)
    else:
        manifest = _up_native(options, skip_pull)
    write_manifest(manifest)
    if manifest_out is not None:
        write_manifest(manifest, manifest_out)
    print(f"all services healthy; manifest: {MANIFEST_FILE}")


def down() -> None:
    """Stop the services recorded by the last `up` and remove the manifest."""
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


def status(options: ServiceOptions) -> None:
    """Print the manifest record and one reachability line per prerequisite."""
    manifest = read_manifest()
    if manifest is None:
        print("manifest: none (`hima up` has not recorded services)")
    else:
        print(
            f"manifest: backend={manifest.backend.value} "
            f"created={manifest.created} ({MANIFEST_FILE})"
        )
    for name, ok, detail in _collect_checks(options):
        mark = "✓" if ok else "✗"
        print(f"{mark} {name}: {detail}")


def _collect_checks(options: ServiceOptions) -> list[tuple[str, bool, str]]:
    advisor_url = _native.advisor_spec(options.advisor_port).health_url
    webui_url = _native.webui_spec(options.webui_port).health_url
    ollama_root = ollama_url(options.ollama_port)
    return [
        ("advisor", healthy(advisor_url), advisor_url),
        ("webui", healthy(webui_url), webui_url),
        ("ollama", healthy(f"{ollama_root}/api/tags"), ollama_root),
        (
            "leader model",
            leader_model_present(ollama_root, options.model),
            options.model,
        ),
        ("StarCraft II", SC2_APP.exists(), str(SC2_APP)),
    ]


def _up_native(options: ServiceOptions, skip_pull: bool) -> ServiceManifest:
    specs = {
        "ollama": _native.ollama_spec(options.ollama_port),
        "advisor": _native.advisor_spec(options.advisor_port),
        "webui": _native.webui_spec(options.webui_port),
    }
    pids = {"ollama": _native.ensure_service(specs["ollama"])}
    _native.ensure_leader_model(options.model, skip_pull, options.ollama_port)
    pids["advisor"] = _native.ensure_service(specs["advisor"])
    pids["webui"] = _native.ensure_service(specs["webui"])
    endpoints = _endpoints(options)
    entries: dict[str, NativeService | DockerService] = {
        name: NativeService(
            endpoint=endpoints[name],
            pid=pids[name],
            pid_file=str(spec.pid_file),
            log_file=str(spec.log_file),
        )
        for name, spec in specs.items()
    }
    return _record(ServiceBackend.NATIVE, options, entries)


def _up_docker(options: ServiceOptions, skip_pull: bool) -> ServiceManifest:
    _docker.compose_up()
    _docker.ensure_leader_model(options.model, skip_pull, options.ollama_port)
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
        leader_model=options.model,
        leader_endpoint=f"{ollama_url(options.ollama_port)}/v1",
        services=entries,
    )
