"""Host-placed services: specs, ownership, launch, health wait, stop."""

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import RUN_ROOT, SERVICE_DIR

from ._health import ADVISOR, HEALTH_PATHS, WEBUI, advisor_health_url, healthy

logger = logging.getLogger(__name__)

HEALTH_ATTEMPTS = 120
HEALTH_INTERVAL_S = 2.0
STOP_WAIT_S = 10
# Grace after SIGKILL; only a process stuck in uninterruptible I/O survives it.
KILL_WAIT_S = 5
# Failure diagnostics quote this much of the end of the service log.
LOG_TAIL_BYTES = 2048
# A log beyond this size rotates to one .1 backup at the next launch.
LOG_ROTATE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ServiceSpec:
    """One host-placed background service.

    `process_keyword` guards `down`: a stored PID is killed only when its
    command line contains this keyword.
    """

    name: str
    argv: list[str]
    health_url: str
    pid_file: Path
    log_file: Path
    process_keyword: str


def advisor_spec(port: int) -> ServiceSpec:
    return ServiceSpec(
        name=ADVISOR,
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
        name=WEBUI,
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
        health_url=f"http://127.0.0.1:{port}{HEALTH_PATHS[WEBUI]}",
        pid_file=SERVICE_DIR / "webui.pid",
        log_file=SERVICE_DIR / "webui.log",
        process_keyword="uvicorn",
    )


def ensure_service(spec: ServiceSpec) -> int:
    """Pid of the healthy owned process, launched when absent.

    Raises:
        CommandError: the endpoint is answered by a process hima does not
            own, the process exits before health, or health is not
            reached within the attempt bound.
    """
    pid = owned_pid(spec)
    if pid is not None:
        if healthy(spec.health_url):
            logger.info(
                "service already healthy: service=%s pid=%d url=%s", spec.name, pid, spec.health_url
            )
            return pid
        wait_healthy(spec, pid)  # the owned process is still starting up
        return pid
    if healthy(spec.health_url):
        raise CommandError(
            f"{spec.name}: {spec.health_url} is answered by a process hima did not start "
            f"(no live pid in {spec.pid_file}); stop the foreign server "
            f"(a compose container: `docker compose stop {spec.name}`) "
            f"or run `hima up --services container`"
        )
    pid = launch(spec)
    wait_healthy(spec, pid)
    return pid


def owned_pid(spec: ServiceSpec) -> int | None:
    """Live pid recorded for the service; clears a stale record."""
    pid = _read_pid_file(spec)
    if pid is None:
        return None
    if _owned_process(spec, pid) is None:
        spec.pid_file.unlink()
        return None
    return pid


def launch(spec: ServiceSpec) -> int:
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_log(spec.log_file)
    try:
        with open(spec.log_file, "ab") as log:
            process = subprocess.Popen(
                spec.argv,
                cwd=RUN_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except FileNotFoundError as error:
        raise CommandError(f"{spec.name}: executable not found: {spec.argv[0]}") from error
    spec.pid_file.write_text(str(process.pid), encoding="utf-8")
    logger.info("service launched: service=%s pid=%d log=%s", spec.name, process.pid, spec.log_file)
    return process.pid


def wait_healthy(spec: ServiceSpec, pid: int) -> None:
    """Block until the health URL answers.

    Raises:
        CommandError: the process exited before answering, or the attempt
            bound is reached while it keeps running.
    """
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
        if _exited(pid):
            raise CommandError(
                f"{spec.name}: process {pid} exited before answering {spec.health_url}; "
                f"log tail ({spec.log_file}):\n{_log_tail(spec.log_file)}"
            )
        time.sleep(HEALTH_INTERVAL_S)
    raise CommandError(
        f"{spec.name}: no health response after {HEALTH_ATTEMPTS} checks; "
        f"the process keeps running — inspect {spec.log_file} and re-check with `hima status`"
    )


def stop_one(spec: ServiceSpec) -> None:
    """Stop the recorded service process group, escalating to SIGKILL."""
    pid = _read_pid_file(spec)
    if pid is None:
        logger.info("service stop skipped: service=%s reason=no_pid_file", spec.name)
        return
    process = _owned_process(spec, pid)
    if process is None:
        spec.pid_file.unlink()
        if psutil.pid_exists(pid):
            logger.warning(
                "service stop skipped: service=%s pid=%d reason=pid_reused", spec.name, pid
            )
        else:
            logger.info("service already exited: service=%s pid=%d", spec.name, pid)
        return
    _terminate_group(spec, process)
    spec.pid_file.unlink()
    logger.info("service stopped: service=%s pid=%d", spec.name, pid)


def _read_pid_file(spec: ServiceSpec) -> int | None:
    # A truncated or garbled record is stale state, not an error: clear it.
    if not spec.pid_file.exists():
        return None
    content = spec.pid_file.read_text(encoding="utf-8").strip()
    try:
        return int(content)
    except ValueError:
        spec.pid_file.unlink()
        logger.warning("pid file unreadable, cleared: service=%s content=%r", spec.name, content)
        return None


def _owned_process(spec: ServiceSpec, pid: int) -> psutil.Process | None:
    # hima spawns services with start_new_session, so an owned pid is its
    # own process-group leader. AccessDenied means another user's process
    # reused the pid; ZombieProcess (a NoSuchProcess subclass) means ours
    # exited unreaped. Both leave the record stale.
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline())
        group_leader = os.getpgid(pid) == pid
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        return None
    if spec.process_keyword not in cmdline or not group_leader:
        return None
    return process


def _exited(pid: int) -> bool:
    # A dead child lingers as a zombie until reaped; both forms are exits.
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _rotate_log(log_file: Path) -> None:
    # Bounds growth across launches; a single long run stays unrotated
    # because the running process keeps its open file handle.
    if log_file.exists() and log_file.stat().st_size > LOG_ROTATE_BYTES:
        log_file.replace(log_file.with_name(log_file.name + ".1"))


def _log_tail(log_file: Path) -> str:
    if not log_file.exists():
        return "(no log output)"
    data = log_file.read_bytes()[-LOG_TAIL_BYTES:]
    return data.decode("utf-8", errors="replace").strip()


def _terminate_group(spec: ServiceSpec, process: psutil.Process) -> None:
    # Signal the whole group: a uvicorn server keeps worker children.
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=STOP_WAIT_S)
        return
    except psutil.TimeoutExpired:
        logger.warning(
            "service ignored SIGTERM: service=%s pid=%d escalating=SIGKILL",
            spec.name,
            process.pid,
        )
    _signal_group(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=KILL_WAIT_S)
    except psutil.TimeoutExpired as error:
        raise CommandError(
            f"{spec.name}: pid {process.pid} survived SIGKILL; "
            f"the process is likely stuck in uninterruptible I/O"
        ) from error


def _signal_group(pid: int, signum: int) -> None:
    # The pid doubles as the group id (start_new_session at launch).
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        logger.debug("signal skipped, group gone: pid=%d signal=%d", pid, signum)
