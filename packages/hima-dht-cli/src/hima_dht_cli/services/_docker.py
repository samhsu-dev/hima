"""Compose-delegated services: `docker compose` invocations for the docker backend."""

import json
import logging
import subprocess
import time
from typing import cast

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import RUN_ROOT

from ._health import leader_model_present, ollama_url

logger = logging.getLogger(__name__)

# Launch set for the docker backend; order follows the native dependency order.
COMPOSE_SERVICES = ("ollama", "advisor", "webui")

# Container-side ollama port, fixed by docker-compose.yml.
CONTAINER_OLLAMA_PORT = 11434


def compose_up() -> None:
    """Start the service trio and block until compose healthchecks pass."""
    _run_compose(["up", "-d", "--wait", *COMPOSE_SERVICES])


def compose_stop() -> None:
    _run_compose(["stop", *reversed(COMPOSE_SERVICES)])


def container_names() -> dict[str, str]:
    """Service name → container name for the running trio.

    Raises:
        CommandError: compose lists no container for one of the services.
    """
    output = _read_compose(["ps", "--format", "json", *COMPOSE_SERVICES])
    names = {row["Service"]: row["Name"] for row in _ps_rows(output)}
    missing = [service for service in COMPOSE_SERVICES if service not in names]
    if missing:
        raise CommandError(f"docker compose ps lists no container for: {', '.join(missing)}")
    return names


def published_ollama_port() -> int:
    """Host port compose actually published for the ollama container.

    Raises:
        CommandError: compose reports no binding or an unparsable one.
    """
    output = _read_compose(["port", "ollama", str(CONTAINER_OLLAMA_PORT)]).strip()
    try:
        return int(output.rsplit(":", 1)[1])
    except (IndexError, ValueError) as error:
        raise CommandError(
            f"cannot parse `docker compose port ollama {CONTAINER_OLLAMA_PORT}` output: {output!r}"
        ) from error


def _ps_rows(output: str) -> list[dict[str, str]]:
    # compose < v2.21 emits one JSON array; newer versions emit NDJSON.
    if output.lstrip().startswith("["):
        return cast(list[dict[str, str]], json.loads(output))
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def ensure_leader_model(model: str, skip_pull: bool, ollama_port: int) -> None:
    """Ensure the model in the containerized Ollama store, pulling when absent."""
    if leader_model_present(ollama_url(ollama_port), model):
        logger.debug("leader model present: model=%s", model)
        return
    if skip_pull:
        raise CommandError(
            f"leader model {model} absent; run `docker compose exec ollama ollama pull {model}`"
        )
    _run_compose(["exec", "-T", "ollama", "ollama", "pull", model])


def _run_compose(args: list[str]) -> None:
    # Start record at INFO: `up --wait` and `pull` can run for minutes.
    logger.info("docker compose starting: args=%s", args)
    started = time.monotonic()
    try:
        completed = subprocess.run(["docker", "compose", *args], cwd=RUN_ROOT)
    except FileNotFoundError as error:
        raise CommandError(
            "docker executable not found; the docker backend needs Docker"
        ) from error
    logger.info(
        "docker compose exited: args=%s exit_code=%d duration_s=%.0f",
        args,
        completed.returncode,
        time.monotonic() - started,
    )
    if completed.returncode != 0:
        raise CommandError(
            f"`docker compose {' '.join(args)}` failed with code {completed.returncode}"
        )


def _read_compose(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["docker", "compose", *args], cwd=RUN_ROOT, capture_output=True, text=True
        )
    except FileNotFoundError as error:
        raise CommandError(
            "docker executable not found; the docker backend needs Docker"
        ) from error
    if completed.returncode != 0:
        raise CommandError(
            f"`docker compose {' '.join(args)}` failed with code {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout
