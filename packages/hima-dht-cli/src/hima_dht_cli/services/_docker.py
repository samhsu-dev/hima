"""Compose-delegated services and the game job: `docker compose` invocations."""

import json
import logging
import os
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

# Compose service (and profile) name of the containerized game job.
GAME_SERVICE = "game"


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


def ensure_game_image(sc2_license: str | None) -> None:
    """Build the game image when it is absent from the local image store.

    Args:
        sc2_license: Blizzard AI and Machine Learning License acceptance —
            the SC2 archive's unzip password. Consumed by the build only,
            never persisted.

    Raises:
        CommandError: the image is absent and `sc2_license` is None, or
            the build fails.
    """
    if game_image_present():
        return
    if sc2_license is None:
        raise CommandError(
            f"game image {GAME_IMAGE} absent and SC2_LICENSE is not set — building it "
            f"downloads the SC2 archive, whose unzip password is Blizzard's AI and "
            f"Machine Learning License acceptance; set SC2_LICENSE to accept and build"
        )
    logger.info("building game image: image=%s (first build downloads multiple GB)", GAME_IMAGE)
    _run_compose(
        ["--profile", GAME_SERVICE, "build", GAME_SERVICE],
        extra_env={"SC2_LICENSE": sc2_license},
    )


def run_game(game_args: list[str]) -> None:
    """Run one containerized game via `docker compose run`, streaming output.

    An empty `game_args` keeps the compose-file command; a non-empty list
    overrides it with `hima run <game_args>`.

    Raises:
        CommandError: the game exits non-zero, carrying the exit code.
    """
    args = ["--profile", GAME_SERVICE, "run", "--rm", GAME_SERVICE]
    if game_args:
        args += ["hima", "run", *game_args]
    exit_code = _invoke_compose(args)
    if exit_code != 0:
        raise CommandError(f"headless game exited with code {exit_code}")


def _run_compose(args: list[str], extra_env: dict[str, str] | None = None) -> None:
    exit_code = _invoke_compose(args, extra_env)
    if exit_code != 0:
        raise CommandError(f"`docker compose {' '.join(args)}` failed with code {exit_code}")


def _invoke_compose(args: list[str], extra_env: dict[str, str] | None = None) -> int:
    # Streams output and returns the exit code so `run_game` can report the
    # game's own exit distinctly from a compose failure. Start record at
    # INFO: `up --wait`, `build`, and `run` can run for minutes. The args
    # never carry secrets — `extra_env` stays out of every record.
    logger.info("docker compose starting: args=%s", args)
    started = time.monotonic()
    env = None if extra_env is None else os.environ | extra_env
    try:
        completed = subprocess.run(["docker", "compose", *args], cwd=RUN_ROOT, env=env)
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
    return completed.returncode


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
