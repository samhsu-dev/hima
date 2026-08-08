"""HTTP health probes for the managed services and the leader endpoint."""

import requests

DEFAULT_ADVISOR_HOST = "localhost"

# Single liveness probe; retries live in the callers' attempt loops.
HEALTH_TIMEOUT_S = 2
# Model listing parses a JSON body, slightly slower than a liveness probe.
QUERY_TIMEOUT_S = 3

# Managed service names: one vocabulary for the health table, the compose
# service names, the manifest entries, and the launch specs.
ADVISOR = "advisor"
WEBUI = "webui"

# Health probe path per managed service, fixed by each server's API.
# Service specs and status checks build their probe URLs from this table.
# The leader engine is not a managed service: it is checked through its
# OpenAI-compatible model list instead (`leader_models`).
HEALTH_PATHS = {ADVISOR: "/health", WEBUI: "/api/games"}


def healthy(url: str) -> bool:
    # Only a non-error status counts: a 404 from a foreign server on the
    # same port is not a healthy service.
    try:
        return requests.get(url, timeout=HEALTH_TIMEOUT_S).ok
    except requests.RequestException:
        return False


def service_healthy(name: str, endpoint: str) -> bool:
    """True when the managed service answers on its own health path."""
    return healthy(f"{endpoint}{HEALTH_PATHS[name]}")


def advisor_health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}{HEALTH_PATHS[ADVISOR]}"


def advisor_healthy(host: str, port: int) -> bool:
    return healthy(advisor_health_url(host, port))


def model_served(model: str, served: list[str]) -> bool:
    """True when `served` lists `model` exactly or with an extra tag suffix.

    Ollama may report `qwen3:8b` as `qwen3:8b:q4`; a bare family name is
    not the requested tag.
    """
    return any(name == model or name.startswith(f"{model}:") for name in served)


def leader_models(base_url: str, api_key: str) -> list[str] | None:
    """Model ids served at an OpenAI-compatible endpoint.

    None when the endpoint is unreachable or its response is not an
    OpenAI-compatible model list.
    """
    try:
        response = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=QUERY_TIMEOUT_S,
        )
        response.raise_for_status()
        return [entry["id"] for entry in response.json().get("data", [])]
    except (requests.RequestException, AttributeError, KeyError, TypeError):
        return None
