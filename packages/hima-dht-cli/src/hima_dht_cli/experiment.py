"""Run one experiment game and archive its outputs under runs/."""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from hima_dht_cli import services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import GAME_OUTPUTS, RUN_ROOT, RUNS_DIR, TMP_DIR


@dataclass(frozen=True)
class RunOptions:
    difficulty: str
    enemy_race: str
    seed: int
    port: int
    advisor_host: str
    model: str
    base_url: str
    api_key: str
    realtime: bool


def run(options: RunOptions) -> None:
    _require_services(options)
    existing = set(TMP_DIR.glob("*.SC2Replay"))
    _invoke_game(options)
    replay = _newest_replay(existing)
    run_dir = _archive(replay)
    _print_metric(run_dir)


def _require_services(options: RunOptions) -> None:
    if not services.advisor_healthy(options.advisor_host, options.port):
        raise CommandError(
            f"advisor server not healthy at {options.advisor_host}:{options.port} — run `hima up`"
        )
    served = services.leader_models(options.base_url, options.api_key)
    if served is None:
        raise CommandError(
            f"leader endpoint not reachable at {options.base_url} — "
            "run `hima up` or check --base-url / HIMA_LEADER_BASE_URL"
        )
    if not _model_served(options.model, served):
        raise CommandError(
            f"leader model {options.model} not served at {options.base_url} — "
            "run `hima up` or check --model / HIMA_LEADER_MODEL"
        )


def _model_served(model: str, served: list[str]) -> bool:
    return any(name == model or name.startswith(f"{model}:") for name in served)


def _invoke_game(options: RunOptions) -> None:
    argv = [
        sys.executable,
        "-m",
        "hima_dht_game",
        "--mode",
        "bot",
        # --num_server 1 keeps bot.py's advisor port (seed % num_server + port)
        # equal to --port for every seed; hima manages a single advisor server.
        "--num_server",
        "1",
        "--port",
        str(options.port),
        "--advisor_host",
        options.advisor_host,
        "--LLM_api_text",
        options.model,
        "--LLM_base_url",
        options.base_url,
        "--LLM_api_key",
        options.api_key,
        "--difficulty",
        options.difficulty,
        "--enemy_race",
        options.enemy_race,
        "--seed",
        str(options.seed),
    ]
    if options.realtime:
        argv.append("--realtime")
    completed = subprocess.run(argv, cwd=RUN_ROOT)
    if completed.returncode != 0:
        raise CommandError(f"hima_dht_game exited with code {completed.returncode}")


def _newest_replay(existing: set[Path]) -> Path:
    fresh = [path for path in TMP_DIR.glob("*.SC2Replay") if path not in existing]
    if not fresh:
        raise CommandError("game finished but produced no new replay in tmp/")
    return max(fresh, key=lambda path: path.stat().st_mtime)


def _archive(replay: Path) -> Path:
    run_dir = RUNS_DIR / replay.stem
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(replay), run_dir / replay.name)
    for name in GAME_OUTPUTS:
        source = TMP_DIR / name
        if source.exists():
            shutil.move(str(source), run_dir / name)
    return run_dir


def _print_metric(run_dir: Path) -> None:
    metric_path = run_dir / "metric.json"
    if not metric_path.exists():
        print(f"archived to {run_dir} (no metric.json)")
        return
    metric = json.loads(metric_path.read_text(encoding="utf-8"))
    for key, value in metric.items():
        print(f"  {key}: {value}")
    print(f"archived to {run_dir}")
