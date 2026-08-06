"""Managed background services: the advisor FastAPI server and Ollama."""
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import requests

from cli import patches
from cli.errors import CommandError
from cli.workspace import REPO_ROOT, SC2_APP, SERVICE_DIR

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


def advisor_spec(port: int) -> ServiceSpec:
    return ServiceSpec(
        name="advisor",
        argv=[sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        health_url=f"http://127.0.0.1:{port}/health",
        pid_file=SERVICE_DIR / "advisor.pid",
        log_file=SERVICE_DIR / "advisor.log",
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


def advisor_healthy(port: int) -> bool:
    return _healthy(advisor_spec(port).health_url)


def ollama_healthy() -> bool:
    return _healthy(ollama_spec().health_url)


def leader_model_present(model: str) -> bool:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        response.raise_for_status()
    except requests.RequestException:
        return False
    names = [entry["name"] for entry in response.json().get("models", [])]
    return any(name == model or name.startswith(f"{model}:") for name in names)


def start(port: int, model: str, skip_pull: bool) -> None:
    _ensure_service(ollama_spec())
    _ensure_leader_model(model, skip_pull)
    _ensure_service(advisor_spec(port))
    print("all services healthy")


def stop() -> None:
    for spec in (advisor_spec(DEFAULT_ADVISOR_PORT), ollama_spec()):
        print(_stop_one(spec))


def status(port: int, model: str) -> None:
    for label, ok, detail in _collect_checks(port, model):
        mark = "✓" if ok else "✗"
        print(f" {mark} {label:<40} {detail}")


def _collect_checks(port: int, model: str) -> list[tuple[str, bool, str]]:
    advisor = advisor_spec(port)
    checks = [
        ("advisor server", _healthy(advisor.health_url), advisor.health_url),
        ("ollama server", ollama_healthy(), OLLAMA_URL),
        (f"leader model {model}", leader_model_present(model), "ollama tags"),
        ("SC2 installation", SC2_APP.exists(), str(SC2_APP)),
    ]
    checks.extend((label, ok, "site-packages") for label, ok in patches.patch_states())
    return checks


def _healthy(url: str) -> bool:
    try:
        return requests.get(url, timeout=2).status_code < 500
    except requests.RequestException:
        return False


def _ensure_service(spec: ServiceSpec) -> None:
    if _healthy(spec.health_url):
        print(f"{spec.name}: already healthy")
        return
    _launch(spec)
    _wait_healthy(spec)
    print(f"{spec.name}: started (log: {spec.log_file})")


def _launch(spec: ServiceSpec) -> None:
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(spec.log_file, "ab") as log:
            process = subprocess.Popen(
                spec.argv, cwd=REPO_ROOT,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
    except FileNotFoundError as error:
        raise CommandError(f"{spec.name}: executable not found: {spec.argv[0]}") from error
    spec.pid_file.write_text(str(process.pid), encoding="utf-8")


def _wait_healthy(spec: ServiceSpec) -> None:
    for _ in range(HEALTH_ATTEMPTS):
        if _healthy(spec.health_url):
            return
        time.sleep(HEALTH_INTERVAL_S)
    raise CommandError(
        f"{spec.name}: no health response after {HEALTH_ATTEMPTS} checks; "
        f"the process keeps running — inspect {spec.log_file} and re-check with `hima status`"
    )


def _ensure_leader_model(model: str, skip_pull: bool) -> None:
    if leader_model_present(model):
        return
    if skip_pull:
        raise CommandError(f"leader model {model} absent; run `ollama pull {model}`")
    print(f"pulling leader model {model} ...")
    completed = subprocess.run(["ollama", "pull", model])
    if completed.returncode != 0:
        raise CommandError(f"ollama pull {model} failed with code {completed.returncode}")


def _stop_one(spec: ServiceSpec) -> str:
    if not spec.pid_file.exists():
        return f"{spec.name}: no pid file — not started by hima"
    pid = int(spec.pid_file.read_text(encoding="utf-8").strip())
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline())
    except psutil.NoSuchProcess:
        spec.pid_file.unlink()
        return f"{spec.name}: already exited"
    if spec.process_keyword not in cmdline:
        return f"{spec.name}: pid {pid} now belongs to another process — skipped"
    process.terminate()
    process.wait(timeout=STOP_WAIT_S)
    spec.pid_file.unlink()
    return f"{spec.name}: stopped (pid {pid})"
