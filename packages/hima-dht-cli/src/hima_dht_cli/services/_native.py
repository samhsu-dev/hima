"""Natively spawned services: specs, ownership, launch, health wait, stop."""

import logging
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import RUN_ROOT, SERVICE_DIR

from ._health import advisor_health_url, healthy, leader_model_present, ollama_url

logger = logging.getLogger(__name__)

HEALTH_ATTEMPTS = 120
HEALTH_INTERVAL_S = 2.0
STOP_WAIT_S = 10


@dataclass(frozen=True)
class ServiceSpec:
    """One natively spawned background service.

    `process_keyword` guards `down`: a stored PID is killed only when its
    command line contains this keyword. `env` is extra spawn environment
    merged over the inherited one.
    """

    name: str
    argv: list[str]
    health_url: str
    pid_file: Path
    log_file: Path
    process_keyword: str
    env: Mapping[str, str] = field(default_factory=dict)


def advisor_spec(port: int) -> ServiceSpec:
    return ServiceSpec(
        name="advisor",
        argv=[
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "hima_dht_game.app:create_default_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        health_url=advisor_health_url("127.0.0.1", port),
        pid_file=SERVICE_DIR / "advisor.pid",
        log_file=SERVICE_DIR / "advisor.log",
        process_keyword="uvicorn",
    )


def webui_spec(port: int) -> ServiceSpec:
    return ServiceSpec(
        name="webui",
        argv=[
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "hima_dht_web.server:create_default_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        health_url=f"http://127.0.0.1:{port}/api/games",
        pid_file=SERVICE_DIR / "webui.pid",
        log_file=SERVICE_DIR / "webui.log",
        process_keyword="uvicorn",
    )


def ollama_spec(port: int) -> ServiceSpec:
    return ServiceSpec(
        name="ollama",
        argv=["ollama", "serve"],
        health_url=f"{ollama_url(port)}/api/tags",
        pid_file=SERVICE_DIR / "ollama.pid",
        log_file=SERVICE_DIR / "ollama.log",
        process_keyword="ollama",
        env=_ollama_env(port),
    )


def ensure_service(spec: ServiceSpec) -> int:
    """Pid of the healthy owned process, launched when absent.

    Raises:
        CommandError: the endpoint is answered by a process hima does not
            own, or health is not reached within the attempt bound.
    """
    pid = owned_pid(spec)
    if pid is not None:
        if healthy(spec.health_url):
            logger.info(
                "service already healthy: service=%s pid=%d url=%s", spec.name, pid, spec.health_url
            )
            return pid
        wait_healthy(spec)  # the owned process is still starting up
        return pid
    if healthy(spec.health_url):
        raise CommandError(
            f"{spec.name}: {spec.health_url} is answered by a process hima did not start "
            f"(no live pid in {spec.pid_file}); stop the foreign server "
            f"(a compose container: `docker compose stop {spec.name}`) "
            f"or run `hima up --backend docker`"
        )
    pid = launch(spec)
    wait_healthy(spec)
    return pid


def owned_pid(spec: ServiceSpec) -> int | None:
    """Live pid recorded for the service; clears a stale pid file."""
    if not spec.pid_file.exists():
        return None
    pid = int(spec.pid_file.read_text(encoding="utf-8").strip())
    try:
        cmdline = " ".join(psutil.Process(pid).cmdline())
    except psutil.NoSuchProcess:
        spec.pid_file.unlink()
        return None
    if spec.process_keyword not in cmdline:
        return None
    return pid


def launch(spec: ServiceSpec) -> int:
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(spec.log_file, "ab") as log:
            process = subprocess.Popen(
                spec.argv,
                cwd=RUN_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, **spec.env} if spec.env else None,
            )
    except FileNotFoundError as error:
        raise CommandError(f"{spec.name}: executable not found: {spec.argv[0]}") from error
    spec.pid_file.write_text(str(process.pid), encoding="utf-8")
    logger.info("service launched: service=%s pid=%d log=%s", spec.name, process.pid, spec.log_file)
    return process.pid


def wait_healthy(spec: ServiceSpec) -> None:
    started = time.monotonic()
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        if healthy(spec.health_url):
            logger.info(
                "service healthy: service=%s attempts=%d duration_s=%.0f",
                spec.name,
                attempt,
                time.monotonic() - started,
            )
            return
        time.sleep(HEALTH_INTERVAL_S)
    raise CommandError(
        f"{spec.name}: no health response after {HEALTH_ATTEMPTS} checks; "
        f"the process keeps running — inspect {spec.log_file} and re-check with `hima status`"
    )


def ensure_leader_model(model: str, skip_pull: bool, ollama_port: int) -> None:
    """Ensure the model in the native Ollama store, pulling when absent."""
    if leader_model_present(ollama_url(ollama_port), model):
        logger.debug("leader model present: model=%s", model)
        return
    if skip_pull:
        raise CommandError(f"leader model {model} absent; run `ollama pull {model}`")
    # Start record at INFO: the pull downloads gigabytes and can stall.
    logger.info("leader model pull starting: model=%s", model)
    started = time.monotonic()
    completed = subprocess.run(
        ["ollama", "pull", model], env={**os.environ, **_ollama_env(ollama_port)}
    )
    logger.info(
        "leader model pull exited: model=%s exit_code=%d duration_s=%.0f",
        model,
        completed.returncode,
        time.monotonic() - started,
    )
    if completed.returncode != 0:
        raise CommandError(f"ollama pull {model} failed with code {completed.returncode}")


def stop_one(spec: ServiceSpec) -> None:
    if not spec.pid_file.exists():
        logger.info("service stop skipped: service=%s reason=no_pid_file", spec.name)
        return
    pid = int(spec.pid_file.read_text(encoding="utf-8").strip())
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline())
    except psutil.NoSuchProcess:
        spec.pid_file.unlink()
        logger.info("service already exited: service=%s pid=%d", spec.name, pid)
        return
    if spec.process_keyword not in cmdline:
        logger.warning("service stop skipped: service=%s pid=%d reason=pid_reused", spec.name, pid)
        return
    process.terminate()
    process.wait(timeout=STOP_WAIT_S)
    spec.pid_file.unlink()
    logger.info("service stopped: service=%s pid=%d", spec.name, pid)


def _ollama_env(port: int) -> dict[str, str]:
    # OLLAMA_HOST is read by both `ollama serve` (bind address) and the
    # `ollama pull` client (target server).
    return {"OLLAMA_HOST": f"127.0.0.1:{port}"}
