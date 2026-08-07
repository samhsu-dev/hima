"""hima console entry: argument parsing and delegation only.

Defaults resolve as: CLI flag > exported environment > `.env` in the
working directory (shared with docker compose interpolation) > code default.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from hima_dht import experiment, metrics, patches, replay, services, viewer
from hima_dht.errors import CommandError
from hima_dht.services import DEFAULT_ADVISOR_HOST, DEFAULT_ADVISOR_PORT, DEFAULT_LEADER_MODEL
from hima_dht.web import server
from hima_dht.web.records import DEFAULT_SAMPLE_INTERVAL
from hima_dht.workspace import RUN_ROOT

DEFAULT_LEADER_BASE_URL = "http://localhost:11434/v1"
DIFFICULTIES = (
    "VeryEasy", "Easy", "Medium", "MediumHard", "Hard", "Harder",
    "VeryHard", "CheatVision", "CheatMoney", "CheatInsane",
)
RACES = ("Protoss", "Zerg", "Terran")

# Environment keys shared with docker-compose.yml interpolation (.env.example).
ENV_ADVISOR_HOST = "HIMA_ADVISOR_HOST"
ENV_ADVISOR_PORT = "HIMA_ADVISOR_PORT"
ENV_WEBUI_HOST = "HIMA_WEBUI_HOST"
ENV_WEBUI_PORT = "HIMA_WEBUI_PORT"
ENV_LEADER_MODEL = "HIMA_LEADER_MODEL"
ENV_LEADER_BASE_URL = "HIMA_LEADER_BASE_URL"


def main() -> int:
    load_dotenv(RUN_ROOT / ".env")
    try:
        args = _build_parser().parse_args()
        args.func(args)
    except CommandError as error:
        print(f"hima: {error}", file=sys.stderr)
        return 1
    return 0


def _env_str(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    try:
        return int(raw)
    except ValueError as error:
        raise CommandError(f"{name} must be an integer, got {raw!r}") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hima", description="HIMA experiment automation")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_setup(sub)
    _add_services(sub)
    _add_run(sub)
    _add_metrics(sub)
    _add_viewer(sub)
    _add_serve(sub)
    return parser


def _add_setup(sub: "argparse._SubParsersAction") -> None:
    setup = sub.add_parser("setup", help="uv sync + site-packages patches + import check")
    setup.set_defaults(func=lambda args: patches.setup())


def _add_services(sub: "argparse._SubParsersAction") -> None:
    up = sub.add_parser("up", help="launch advisor, Ollama, and the webui, wait until healthy")
    _add_service_options(up)
    up.add_argument("--skip-pull", action="store_true")
    up.set_defaults(func=lambda args: services.up(_service_options(args), args.skip_pull))

    down = sub.add_parser("down", help="stop services started by hima")
    down.set_defaults(func=lambda args: services.down())

    status = sub.add_parser("status", help="report service, game, and patch state")
    _add_service_options(status)
    status.set_defaults(func=lambda args: services.status(_service_options(args)))


def _add_service_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int,
                        default=_env_int(ENV_ADVISOR_PORT, DEFAULT_ADVISOR_PORT))
    parser.add_argument("--webui-port", type=int,
                        default=_env_int(ENV_WEBUI_PORT, server.DEFAULT_PORT))
    parser.add_argument("--model", default=_env_str(ENV_LEADER_MODEL, DEFAULT_LEADER_MODEL))


def _service_options(args: argparse.Namespace) -> services.ServiceOptions:
    return services.ServiceOptions(
        advisor_port=args.port, webui_port=args.webui_port, model=args.model)


def _add_run(sub: "argparse._SubParsersAction") -> None:
    run = sub.add_parser("run", help="play one game and archive its outputs under runs/")
    run.add_argument("--difficulty", default="Hard", choices=DIFFICULTIES)
    run.add_argument("--enemy-race", default="Zerg", choices=RACES)
    run.add_argument("--seed", type=int, default=3)
    run.add_argument("--port", type=int, default=_env_int(ENV_ADVISOR_PORT, DEFAULT_ADVISOR_PORT))
    run.add_argument("--advisor-host", default=_env_str(ENV_ADVISOR_HOST, DEFAULT_ADVISOR_HOST))
    run.add_argument("--model", default=_env_str(ENV_LEADER_MODEL, DEFAULT_LEADER_MODEL))
    run.add_argument("--base-url", default=_env_str(ENV_LEADER_BASE_URL, DEFAULT_LEADER_BASE_URL))
    run.add_argument("--realtime", action="store_true")
    run.set_defaults(func=_cmd_run)


def _cmd_run(args: argparse.Namespace) -> None:
    experiment.run(experiment.RunOptions(
        difficulty=args.difficulty,
        enemy_race=args.enemy_race,
        seed=args.seed,
        port=args.port,
        advisor_host=args.advisor_host,
        model=args.model,
        base_url=args.base_url,
        realtime=args.realtime,
    ))


def _add_metrics(sub: "argparse._SubParsersAction") -> None:
    table = sub.add_parser("metrics", help="aggregate metric.json across runs/")
    table.set_defaults(func=lambda args: metrics.report())


def _add_viewer(sub: "argparse._SubParsersAction") -> None:
    play = sub.add_parser("replay", help="open a replay in the pysc2 renderer")
    play.add_argument("replay", type=Path)
    play.set_defaults(func=lambda args: replay.play(args.replay))

    export = sub.add_parser("export", help="export a replay to a standalone HTML viewer")
    export.add_argument("replay", type=Path)
    export.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_INTERVAL)
    export.add_argument("--logs", type=Path, default=None)
    export.add_argument("-o", "--out", type=Path, default=None)
    export.set_defaults(func=_cmd_export)

    show = sub.add_parser("view", help="export when needed, then open the HTML viewer")
    show.add_argument("path", type=Path)
    show.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_INTERVAL)
    show.set_defaults(func=lambda args: viewer.view(args.path, args.sample))


def _add_serve(sub: "argparse._SubParsersAction") -> None:
    observe = sub.add_parser("serve", help="serve the game observation web UI")
    observe.add_argument("--host", default=_env_str(ENV_WEBUI_HOST, server.DEFAULT_HOST))
    observe.add_argument("--port", type=int, default=_env_int(ENV_WEBUI_PORT, server.DEFAULT_PORT))
    observe.set_defaults(func=lambda args: server.serve(args.host, args.port))


def _cmd_export(args: argparse.Namespace) -> None:
    target = viewer.build(viewer.ExportRequest(args.replay, args.sample, args.out, args.logs))
    print(f"viewer written: {target}")
