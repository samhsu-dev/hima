"""Managed background services and the containerized game job."""

__all__ = [
    "DEFAULT_ADVISOR_HOST",
    "DEFAULT_ADVISOR_PORT",
    "DEFAULT_LEADER_API_KEY",
    "DEFAULT_LEADER_BASE_URL",
    "DEFAULT_LEADER_MODEL",
    "DEFAULT_OLLAMA_PORT",
    "MANIFEST_FILE",
    "DockerService",
    "ModelEndpoint",
    "NativeService",
    "ServiceBackend",
    "ServiceManifest",
    "ServiceOptions",
    "ServiceSpec",
    "advisor_healthy",
    "down",
    "ensure_game_image",
    "leader_models",
    "model_served",
    "read_manifest",
    "run_game",
    "status",
    "up",
]

from ._docker import ensure_game_image, run_game
from ._health import (
    DEFAULT_ADVISOR_HOST,
    advisor_healthy,
    leader_models,
    model_served,
)
from ._lifecycle import (
    DEFAULT_ADVISOR_PORT,
    DEFAULT_LEADER_API_KEY,
    DEFAULT_LEADER_BASE_URL,
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
    ModelEndpoint,
    NativeService,
    ServiceBackend,
    ServiceManifest,
    read_manifest,
)
from ._native import ServiceSpec
