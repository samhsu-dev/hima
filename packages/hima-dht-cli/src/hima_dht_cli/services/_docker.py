"""Compose-delegated services: `docker compose` invocations for the docker backend."""

import json
import logging
import subprocess
import time
from typing import cast

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import RUN_ROOT

logger = logging.getLogger(__name__)

# Managed launch set for the docker backend. The leader engine is never a
# managed compose service; the `leader` profile is an operator opt-in
# consumed via HIMA_LEADER_BASE_URL (design-deployment.md).
COMPOSE_SERVICES = ("advisor", "webui")

# Image tag of the containerized game, fixed by docker-compose.yml.
GAME_IMAGE = "hima-game"


def game_image_present() -> bool:
    """True when the game image exists in the local image store."""
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", GAME_IMAGE], capture_output=True, text=True
        )
    except FileNotFoundError as error:
        raise CommandError(
            "docker executable not found; the docker backend needs Docker"
        ) from error
    return completed.returncode == 0


def compose_up() -> None:
    """Start the managed services and block until compose healthchecks pass."""
    _run_compose(["up", "-d", "--wait", *COMPOSE_SERVICES])


def compose_stop() -> None:
    _run_compose(["stop", *reversed(COMPOSE_SERVICES)])


def container_names() -> dict[str, str]:
    """Service name → container name for the managed services.

    Raises:
        CommandError: compose lists no container for one of the services.
    """
    output = _read_compose(["ps", "--format", "json", *COMPOSE_SERVICES])
    names = {row["Service"]: row["Name"] for row in _ps_rows(output)}
    missing = [service for service in COMPOSE_SERVICES if service not in names]
    if missing:
        raise CommandError(f"docker compose ps lists no container for: {', '.join(missing)}")
    return names


def _ps_rows(output: str) -> list[dict[str, str]]:
    # compose < v2.21 emits one JSON array; newer versions emit NDJSON.
    if output.lstrip().startswith("["):
        return cast(list[dict[str, str]], json.loads(output))
    return [json.loads(line) for line in output.splitlines() if line.strip()]


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
