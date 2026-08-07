"""Service start manifest: what `hima up` started, read by `down`/`status`."""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import tomli_w
import tomllib

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import SERVICE_DIR

MANIFEST_FILE = SERVICE_DIR / "manifest.toml"


class ServiceBackend(str, Enum):
    """Where the managed services run."""

    NATIVE = "native"
    DOCKER = "docker"


@dataclass(frozen=True)
class NativeService:
    """One natively spawned service as recorded in the manifest."""

    endpoint: str
    pid: int
    pid_file: str
    log_file: str


@dataclass(frozen=True)
class DockerService:
    """One compose-managed service as recorded in the manifest."""

    endpoint: str
    container: str


@dataclass(frozen=True)
class ServiceManifest:
    """Record of one successful `up`: backend, leader engine, services.

    `leader_endpoint` is the OpenAI-compatible URL of the leader engine
    `up` ensures; a `HIMA_LEADER_BASE_URL` override may point games at a
    different endpoint.
    """

    backend: ServiceBackend
    created: str
    leader_model: str
    leader_endpoint: str
    services: dict[str, NativeService | DockerService]


def write_manifest(manifest: ServiceManifest, path: Path = MANIFEST_FILE) -> None:
    """Serialize the manifest to TOML at `path`, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "backend": manifest.backend.value,
        "created": manifest.created,
        "leader": {"model": manifest.leader_model, "endpoint": manifest.leader_endpoint},
        "services": {name: asdict(entry) for name, entry in manifest.services.items()},
    }
    path.write_text(tomli_w.dumps(document), encoding="utf-8")


def read_manifest(path: Path = MANIFEST_FILE) -> ServiceManifest | None:
    """The recorded manifest, or None when no `up` has recorded one.

    Raises:
        CommandError: the file exists but does not parse as a manifest.
    """
    if not path.exists():
        return None
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        backend = ServiceBackend(document["backend"])
        return ServiceManifest(
            backend=backend,
            created=document["created"],
            leader_model=document["leader"]["model"],
            leader_endpoint=document["leader"]["endpoint"],
            services={
                name: _entry(backend, fields) for name, fields in document["services"].items()
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommandError(f"corrupt service manifest {path}: {error!r}") from error


def remove_manifest(path: Path = MANIFEST_FILE) -> None:
    """Delete the manifest; a missing file is not an error."""
    path.unlink(missing_ok=True)


def _entry(backend: ServiceBackend, fields: dict[str, Any]) -> NativeService | DockerService:
    # The manifest-level backend discriminates the entry type; the dataclass
    # constructor validates the field set (TypeError on mismatch).
    if backend is ServiceBackend.DOCKER:
        return DockerService(**fields)
    return NativeService(**fields)
