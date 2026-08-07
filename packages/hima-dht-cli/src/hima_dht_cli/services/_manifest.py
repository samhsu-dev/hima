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
# Bumped when the TOML layout changes; readers reject every other version.
MANIFEST_VERSION = 2


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
class ModelEndpoint:
    """One OpenAI-compatible model endpoint the deployment consumes.

    `url` is the base URL `up` verified from the host view. Never carries
    an API key — secrets stay in the environment chain.
    """

    url: str
    model: str


@dataclass(frozen=True)
class ServiceManifest:
    """Record of one successful `up`: backend, model endpoints, services.

    `endpoints` is keyed by role; today the single role is `leader`.
    """

    backend: ServiceBackend
    created: str
    endpoints: dict[str, ModelEndpoint]
    services: dict[str, NativeService | DockerService]


def write_manifest(manifest: ServiceManifest, path: Path = MANIFEST_FILE) -> None:
    """Serialize the manifest to TOML at `path`, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": MANIFEST_VERSION,
        "backend": manifest.backend.value,
        "created": manifest.created,
        "endpoints": {role: asdict(endpoint) for role, endpoint in manifest.endpoints.items()},
        "services": {name: asdict(entry) for name, entry in manifest.services.items()},
    }
    # Atomic replace: a crash mid-write must not leave a torn manifest.
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(tomli_w.dumps(document), encoding="utf-8")
    scratch.replace(path)


def read_manifest(path: Path = MANIFEST_FILE) -> ServiceManifest | None:
    """The recorded manifest, or None when no `up` has recorded one.

    Raises:
        CommandError: the file exists but does not parse as a manifest,
            or records a version this hima does not read.
    """
    if not path.exists():
        return None
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise CommandError(_corrupt_message(path, error)) from error
    version = document.get("version")
    if version != MANIFEST_VERSION:
        raise CommandError(
            f"service manifest {path} records version {version!r}; this hima reads "
            f"version {MANIFEST_VERSION} — delete the file and rerun `hima up`"
        )
    try:
        backend = ServiceBackend(document["backend"])
        return ServiceManifest(
            backend=backend,
            created=document["created"],
            endpoints={
                role: ModelEndpoint(**fields) for role, fields in document["endpoints"].items()
            },
            services={
                name: _entry(backend, fields) for name, fields in document["services"].items()
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommandError(_corrupt_message(path, error)) from error


def remove_manifest(path: Path = MANIFEST_FILE) -> None:
    """Delete the manifest; a missing file is not an error."""
    path.unlink(missing_ok=True)


def _corrupt_message(path: Path, error: Exception) -> str:
    return (
        f"corrupt service manifest {path}: {error!r} — delete the file and rerun "
        f"`hima up`; `hima down` without a manifest still sweeps native pid files"
    )


def _entry(backend: ServiceBackend, fields: dict[str, Any]) -> NativeService | DockerService:
    # The manifest-level backend discriminates the entry type; the dataclass
    # constructor validates the field set (TypeError on mismatch).
    if backend is ServiceBackend.DOCKER:
        return DockerService(**fields)
    return NativeService(**fields)
