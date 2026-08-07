"""Managed background services: advisor server, Ollama, and the webui."""

__all__ = [
    "DEFAULT_ADVISOR_HOST",
    "DEFAULT_ADVISOR_PORT",
    "DEFAULT_LEADER_MODEL",
    "DEFAULT_OLLAMA_PORT",
    "MANIFEST_FILE",
    "DockerService",
    "NativeService",
    "ServiceBackend",
    "ServiceManifest",
    "ServiceOptions",
    "ServiceSpec",
    "advisor_healthy",
    "down",
    "leader_model_present",
    "leader_models",
    "ollama_healthy",
    "read_manifest",
    "status",
    "up",
]

from ._health import (
    DEFAULT_ADVISOR_HOST,
    advisor_healthy,
    leader_model_present,
    leader_models,
    ollama_healthy,
)
from ._lifecycle import (
    DEFAULT_ADVISOR_PORT,
    DEFAULT_LEADER_MODEL,
    DEFAULT_OLLAMA_PORT,
    ServiceOptions,
    down,
    status,
    up,
)
from ._manifest import (
    MANIFEST_FILE,
    DockerService,
    NativeService,
    ServiceBackend,
    ServiceManifest,
    read_manifest,
)
from ._native import ServiceSpec
