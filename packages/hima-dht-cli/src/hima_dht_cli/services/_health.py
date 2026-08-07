"""HTTP health probes for the managed services and the leader endpoint."""

import requests

DEFAULT_ADVISOR_HOST = "localhost"

# Single liveness probe; retries live in the callers' attempt loops.
HEALTH_TIMEOUT_S = 2
# Model listing parses a JSON body, slightly slower than a liveness probe.
QUERY_TIMEOUT_S = 3


def healthy(url: str) -> bool:
    try:
        return requests.get(url, timeout=HEALTH_TIMEOUT_S).status_code < 500
    except requests.RequestException:
        return False


def advisor_health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def advisor_healthy(host: str, port: int) -> bool:
    return healthy(advisor_health_url(host, port))


def ollama_url(port: int) -> str:
    return f"http://localhost:{port}"


def ollama_healthy(root: str) -> bool:
    return healthy(f"{root}/api/tags")


def leader_model_present(root: str, model: str) -> bool:
    try:
        response = requests.get(f"{root}/api/tags", timeout=QUERY_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException:
        return False
    names = [entry["name"] for entry in response.json().get("models", [])]
    return any(name == model or name.startswith(f"{model}:") for name in names)


def leader_models(base_url: str, api_key: str) -> list[str] | None:
    """Model ids served at an OpenAI-compatible endpoint; None when unreachable."""
    try:
        response = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=QUERY_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    return [entry["id"] for entry in response.json().get("data", [])]
