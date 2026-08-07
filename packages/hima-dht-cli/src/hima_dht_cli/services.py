"""Managed background services: advisor server, Ollama, and the webui."""

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import requests

from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import RUN_ROOT, SC2_APP, SERVICE_DIR
from hima_dht_web.server import DEFAULT_PORT as DEFAULT_WEBUI_PORT

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
DEFAULT_ADVISOR_HOST = "localhost"
DEFAULT_ADVISOR_PORT = 8090
DEFAULT_LEADER_MODEL = "qwen3:8b"
HEALTH_ATTEMPTS = 120
HEALTH_INTERVAL_S = 2.0
STOP_WAIT_S = 10


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    argv: list[str]
    health_url: str
    pid_file: Path
    log_file: Path
    process_keyword: str


@dataclass(frozen=True)
class ServiceOptions:
    """Endpoint and model selection for the managed services."""

    advisor_port: int = DEFAULT_ADVISOR_PORT
    webui_port: int = DEFAULT_WEBUI_PORT
    model: str = DEFAULT_LEADER_MODEL


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
        health_url=_advisor_health_url("127.0.0.1", port),
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


def ollama_spec() -> ServiceSpec:
    return ServiceSpec(
        name="ollama",
        argv=["ollama", "serve"],
        health_url=f"{OLLAMA_URL}/api/tags",
        pid_file=SERVICE_DIR / "ollama.pid",
        log_file=SERVICE_DIR / "ollama.log",
        process_keyword="ollama",
    )


def advisor_healthy(host: str, port: int) -> bool:
    return _healthy(_advisor_health_url(host, port))


def ollama_healthy(root: str) -> bool:
    return _healthy(f"{root}/api/tags")


def leader_model_present(root: str, model: str) -> bool:
    try:
        response = requests.get(f"{root}/api/tags", timeout=3)
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
            timeout=3,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    return [entry["id"] for entry in response.json().get("data", [])]


def _advisor_health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def up(options: ServiceOptions, skip_pull: bool) -> None:
    _ensure_service(ollama_spec())
    _ensure_leader_model(options.model, skip_pull)
    _ensure_service(advisor_spec(options.advisor_port))
    _ensure_service(webui_spec(options.webui_port))
    print("all services healthy")


def down() -> None:
    for spec in (
        webui_spec(DEFAULT_WEBUI_PORT),
        advisor_spec(DEFAULT_ADVISOR_PORT),
        ollama_spec(),
    ):
        _stop_one(spec)


def status(options: ServiceOptions) -> None:
    for label, ok, detail in _collect_checks(options):
        mark = "✓" if ok else "✗"
        print(f" {mark} {label:<40} {detail}")


def _collect_checks(options: ServiceOptions) -> list[tuple[str, bool, str]]:
    advisor = advisor_spec(options.advisor_port)
    webui = webui_spec(options.webui_port)
    model = options.model
    checks = [
        ("advisor server", _healthy(advisor.health_url), advisor.health_url),
        ("webui server", _healthy(webui.health_url), webui.health_url),
        ("ollama server", ollama_healthy(OLLAMA_URL), OLLAMA_URL),
        (
            f"leader model {model}",
            leader_model_present(OLLAMA_URL, model),
            "ollama tags",
        ),
        ("SC2 installation", SC2_APP.exists(), str(SC2_APP)),
    ]
    return checks


def _healthy(url: str) -> bool:
    try:
        return requests.get(url, timeout=2).status_code < 500
    except requests.RequestException:
        return False


def _ensure_service(spec: ServiceSpec) -> None:
    if _healthy(spec.health_url):
        logger.info("service already healthy: service=%s url=%s", spec.name, spec.health_url)
        return
    _launch(spec)
    _wait_healthy(spec)


def _launch(spec: ServiceSpec) -> None:
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
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


def _wait_healthy(spec: ServiceSpec) -> None:
    started = time.monotonic()
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        if _healthy(spec.health_url):
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


def _ensure_leader_model(model: str, skip_pull: bool) -> None:
    if leader_model_present(OLLAMA_URL, model):
        logger.debug("leader model present: model=%s", model)
        return
    if skip_pull:
        raise CommandError(f"leader model {model} absent; run `ollama pull {model}`")
    # Start record at INFO: the pull downloads gigabytes and can stall.
    logger.info("leader model pull starting: model=%s", model)
    started = time.monotonic()
    completed = subprocess.run(["ollama", "pull", model])
    logger.info(
        "leader model pull exited: model=%s exit_code=%d duration_s=%.0f",
        model,
        completed.returncode,
        time.monotonic() - started,
    )
    if completed.returncode != 0:
        raise CommandError(f"ollama pull {model} failed with code {completed.returncode}")


def _stop_one(spec: ServiceSpec) -> None:
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
