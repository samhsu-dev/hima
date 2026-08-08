"""Run one experiment game and archive its outputs under runs/."""

import json
import logging
import shutil
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from hima_dht_cli import replay, services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.workspace import GAME_OUTPUTS, RUN_ROOT, RUNS_DIR, TMP_DIR

logger = logging.getLogger(__name__)


class ObservationUI(str, Enum):
    """How a human watches a run, independent of where the game runs."""

    NONE = "none"
    WEB = "web"
    PYGUI = "pygui"


class RunPhase(str, Enum):
    """Point in a run at which a surface is asked to open."""

    BEFORE = "before"
    AFTER = "after"


@dataclass(frozen=True)
class ObservationOptions:
    """The observation choice for one run, at either game placement."""

    ui: ObservationUI = ObservationUI.NONE
    webui_url: str = ""


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
    observation: ObservationOptions = ObservationOptions()


@dataclass(frozen=True)
class ContainerRunOptions:
    """One container game: forwarded flags and host-side precheck values.

    `game_args` holds only the game-semantic flags the user passed
    explicitly on the host command line; environment- and default-sourced
    values resolve inside the container, keeping the precedence chain
    intact. `sc2_license` is consumed by the image build only.
    """

    game_args: list[str]
    model: str
    api_key: str
    sc2_license: str | None
    observation: ObservationOptions = ObservationOptions()


def run_host(options: RunOptions) -> None:
    # A game runs for hours and can die silently; the start record makes a
    # missing summary record diagnosable.
    logger.info(
        "run starting: difficulty=%s enemy_race=%s seed=%d advisor=%s:%d "
        "leader=%s model=%s realtime=%s",
        options.difficulty,
        options.enemy_race,
        options.seed,
        options.advisor_host,
        options.port,
        options.base_url,
        options.model,
        options.realtime,
    )
    started = time.monotonic()
    try:
        run_dir = _play_and_archive(options)
    except CommandError as error:
        logger.warning("run failed: duration_s=%.0f error=%s", time.monotonic() - started, error)
        raise
    logger.info("run archived: run_dir=%s duration_s=%.0f", run_dir, time.monotonic() - started)
    _print_metric(run_dir)
    open_surface(options.observation, RunPhase.AFTER, run_dir)


def run_container(options: ContainerRunOptions) -> None:
    """Run one containerized game, the default game placement.

    The in-container `hima run` performs its own prechecks, archives the
    run under the bind-mounted `runs/`, and prints the metric summary;
    output streams to this console.

    Raises:
        CommandError: no manifest or an unreachable advisor, an
            unreachable leader endpoint or unserved model, a missing image
            without SC2_LICENSE, a failed build, or a non-zero game exit.
    """
    manifest = _require_manifest()
    advisor_host = services.advisor_address(manifest.placement)
    open_surface(options.observation, RunPhase.BEFORE, None)
    _require_recorded_advisor(manifest)
    _require_recorded_leader(manifest, options)
    services.ensure_game_image(options.sc2_license)
    services.run_game(options.game_args, advisor_host)
    open_surface(options.observation, RunPhase.AFTER, _newest_run_dir())


def open_surface(options: ObservationOptions, phase: RunPhase, run_dir: Path | None) -> None:
    """Open the requested observation surface when `phase` is its phase.

    Raises:
        CommandError: `WEB` finds no webui answering, or `PYGUI` finds no
            replay in `run_dir`.
    """
    if options.ui is ObservationUI.WEB and phase is RunPhase.BEFORE:
        _open_web(options.webui_url)
    if options.ui is ObservationUI.PYGUI and phase is RunPhase.AFTER:
        replay.play(_archived_replay(run_dir))


def _open_web(webui_url: str) -> None:
    # An observation the user asked for and cannot get is a failed
    # request, not a downgrade: never fall back to running unwatched.
    if not services.service_healthy(services.WEBUI, webui_url):
        raise CommandError(
            f"--ui web needs an observation server at {webui_url}, which does not "
            f"answer — run `hima up --webui` or check --webui-port / HIMA_WEBUI_PORT"
        )
    logger.info("observation surface opening: ui=web url=%s", webui_url)
    webbrowser.open(webui_url)


def _archived_replay(run_dir: Path | None) -> Path:
    replays = sorted(run_dir.glob("*.SC2Replay")) if run_dir is not None else []
    if not replays:
        raise CommandError(
            f"--ui pygui found no replay to open in {run_dir} — the game archived none"
        )
    return replays[0]


def _newest_run_dir() -> Path | None:
    archived = [path for path in RUNS_DIR.glob("*") if path.is_dir()]
    if not archived:
        return None
    return max(archived, key=lambda path: path.stat().st_mtime)


def _require_manifest() -> services.ServiceManifest:
    manifest = services.read_manifest()
    if manifest is None:
        raise CommandError(
            "a container game needs the advisor `hima up` recorded, and no manifest "
            "exists — run `hima up` first"
        )
    return manifest


def _require_recorded_advisor(manifest: services.ServiceManifest) -> None:
    # The recorded endpoint is the host view; the job reaches the same
    # server through the address `advisor_address` derives.
    entry = manifest.services.get(services.ADVISOR)
    if entry is None:
        raise CommandError("no advisor recorded in the manifest — run `hima up`")
    if not services.service_healthy(services.ADVISOR, entry.endpoint):
        raise CommandError(
            f"advisor server not healthy at {entry.endpoint} — run `hima down && hima up`"
        )


def _require_recorded_leader(
    manifest: services.ServiceManifest, options: ContainerRunOptions
) -> None:
    # The recorded URL is the host-view endpoint `up` verified; the game
    # container resolves its own HIMA_LEADER_BASE_URL at run time.
    endpoint = manifest.endpoints.get("leader")
    if endpoint is None:
        raise CommandError("no leader endpoint recorded in the manifest — run `hima up`")
    served = services.leader_models(endpoint.url, options.api_key)
    if served is None:
        raise CommandError(
            f"leader endpoint not reachable at {endpoint.url} — "
            "run `hima up` or check HIMA_LEADER_BASE_URL"
        )
    if not services.model_served(options.model, served):
        raise CommandError(
            f"leader model {options.model} not served at {endpoint.url} — "
            "pull it there or check --model / HIMA_LEADER_MODEL"
        )


def _play_and_archive(options: RunOptions) -> Path:
    open_surface(options.observation, RunPhase.BEFORE, None)
    _require_services(options)
    existing = set(TMP_DIR.glob("*.SC2Replay"))
    _invoke_game(options)
    return _archive(_newest_replay(existing))


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
    if not services.model_served(options.model, served):
        raise CommandError(
            f"leader model {options.model} not served at {options.base_url} — "
            "run `hima up` or check --model / HIMA_LEADER_MODEL"
        )
    logger.debug(
        "service prechecks passed: advisor=%s:%d leader=%s models=%d",
        options.advisor_host,
        options.port,
        options.base_url,
        len(served),
    )


def _invoke_game(options: RunOptions) -> None:
    # Start record at INFO: the subprocess can hang or die without output.
    # The argv itself stays out of the record — it carries the API key.
    logger.info("game subprocess starting: module=hima_dht_game")
    started = time.monotonic()
    completed = subprocess.run(_game_argv(options), cwd=RUN_ROOT)
    logger.info(
        "game subprocess exited: exit_code=%d duration_s=%.0f",
        completed.returncode,
        time.monotonic() - started,
    )
    if completed.returncode != 0:
        raise CommandError(f"hima_dht_game exited with code {completed.returncode}")


def _game_argv(options: RunOptions) -> list[str]:
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
    return argv


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
