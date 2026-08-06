"""hima console entry: argument parsing and delegation only."""
import argparse
import sys
from pathlib import Path

from cli import experiment, metrics, patches, replay, services, viewer
from cli.errors import CommandError
from cli.services import DEFAULT_ADVISOR_PORT, DEFAULT_LEADER_MODEL
from cli.web.records import DEFAULT_SAMPLE_INTERVAL

DEFAULT_LEADER_BASE_URL = "http://localhost:11434/v1"
DIFFICULTIES = (
    "VeryEasy", "Easy", "Medium", "MediumHard", "Hard", "Harder",
    "VeryHard", "CheatVision", "CheatMoney", "CheatInsane",
)
RACES = ("Protoss", "Zerg", "Terran")


def main() -> int:
    args = _build_parser().parse_args()
    try:
        args.func(args)
    except CommandError as error:
        print(f"hima: {error}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hima", description="HIMA experiment automation")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_setup(sub)
    _add_services(sub)
    _add_run(sub)
    _add_metrics(sub)
    _add_viewer(sub)
    return parser


def _add_setup(sub: "argparse._SubParsersAction") -> None:
    setup = sub.add_parser("setup", help="uv sync + site-packages patches + import check")
    setup.set_defaults(func=lambda args: patches.setup())


def _add_services(sub: "argparse._SubParsersAction") -> None:
    start = sub.add_parser("start", help="launch advisor server and Ollama, wait until healthy")
    start.add_argument("--port", type=int, default=DEFAULT_ADVISOR_PORT)
    start.add_argument("--model", default=DEFAULT_LEADER_MODEL)
    start.add_argument("--skip-pull", action="store_true")
    start.set_defaults(func=lambda args: services.start(args.port, args.model, args.skip_pull))

    stop = sub.add_parser("stop", help="stop services started by hima")
    stop.set_defaults(func=lambda args: services.stop())

    status = sub.add_parser("status", help="report service, game, and patch state")
    status.add_argument("--port", type=int, default=DEFAULT_ADVISOR_PORT)
    status.add_argument("--model", default=DEFAULT_LEADER_MODEL)
    status.set_defaults(func=lambda args: services.status(args.port, args.model))


def _add_run(sub: "argparse._SubParsersAction") -> None:
    run = sub.add_parser("run", help="play one game and archive its outputs under runs/")
    run.add_argument("--difficulty", default="Hard", choices=DIFFICULTIES)
    run.add_argument("--enemy-race", default="Zerg", choices=RACES)
    run.add_argument("--seed", type=int, default=3)
    run.add_argument("--port", type=int, default=DEFAULT_ADVISOR_PORT)
    run.add_argument("--model", default=DEFAULT_LEADER_MODEL)
    run.add_argument("--base-url", default=DEFAULT_LEADER_BASE_URL)
    run.add_argument("--realtime", action="store_true")
    run.set_defaults(func=_cmd_run)


def _cmd_run(args: argparse.Namespace) -> None:
    experiment.run(experiment.RunOptions(
        difficulty=args.difficulty,
        enemy_race=args.enemy_race,
        seed=args.seed,
        port=args.port,
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


def _cmd_export(args: argparse.Namespace) -> None:
    target = viewer.build(viewer.ExportRequest(args.replay, args.sample, args.out, args.logs))
    print(f"viewer written: {target}")
