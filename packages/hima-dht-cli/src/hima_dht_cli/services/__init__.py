"""Managed background services and the containerized game job."""

__all__ = [
    "ADVISOR",
    "DEFAULT_ADVISOR_HOST",
    "DEFAULT_ADVISOR_PORT",
    "DEFAULT_LEADER_API_KEY",
    "DEFAULT_LEADER_BASE_URL",
    "DEFAULT_LEADER_MODEL",
    "MANIFEST_FILE",
    "WEBUI",
    "ContainerService",
    "HostService",
    "ModelEndpoint",
    "ServiceManifest",
    "ServiceOptions",
    "ServiceSpec",
    "advisor_address",
    "advisor_healthy",
    "down",
    "ensure_game_image",
    "leader_models",
    "model_served",
    "read_manifest",
    "run_game",
    "service_healthy",
    "status",
    "up",
]

from ._docker import advisor_address, ensure_game_image, run_game
from ._health import (
    ADVISOR,
    DEFAULT_ADVISOR_HOST,
    WEBUI,
    advisor_healthy,
    leader_models,
    model_served,
    service_healthy,
)
from ._host import ServiceSpec
from ._lifecycle import (
    DEFAULT_ADVISOR_PORT,
    DEFAULT_LEADER_API_KEY,
    DEFAULT_LEADER_BASE_URL,
    DEFAULT_LEADER_MODEL,
    ServiceOptions,
    down,
    status,
    up,
)
from ._manifest import (
    MANIFEST_FILE,
    ContainerService,
    HostService,
    ModelEndpoint,
    ServiceManifest,
    read_manifest,
)
