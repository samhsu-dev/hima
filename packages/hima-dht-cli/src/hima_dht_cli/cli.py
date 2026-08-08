"""hima console entry: argument parsing and delegation only.

Defaults resolve as: CLI flag > exported environment > `.env` in the
working directory (shared with docker compose interpolation) > code default.
Environment lookup is declared per option via typer `envvar`.
"""

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from dotenv import load_dotenv

# typer 0.27 vendors click as `typer._click` and re-exports no
# ParameterSource; the standalone `click` distribution's enum is a
# different class, so identity checks against it always fail.
from typer._click.core import ParameterSource
from uvicorn.config import STARTUP_FAILURE

from hima_dht_cli import experiment, services, viewer
from hima_dht_cli.errors import CommandError
from hima_dht_cli.metrics import report
from hima_dht_cli.placement import Placement
from hima_dht_cli.replay import play
from hima_dht_cli.services import (
    DEFAULT_ADVISOR_HOST,
    DEFAULT_ADVISOR_PORT,
    DEFAULT_LEADER_API_KEY,
    DEFAULT_LEADER_BASE_URL,
    DEFAULT_LEADER_MODEL,
)
from hima_dht_cli.workspace import RUN_ROOT
from hima_dht_records import DEFAULT_SAMPLE_INTERVAL
from hima_dht_web import server

# Environment keys shared with docker-compose.yml interpolation (.env.example).
ENV_ADVISOR_HOST = "HIMA_ADVISOR_HOST"
ENV_ADVISOR_PORT = "HIMA_ADVISOR_PORT"
ENV_WEBUI_HOST = "HIMA_WEBUI_HOST"
ENV_WEBUI_PORT = "HIMA_WEBUI_PORT"
ENV_LEADER_MODEL = "HIMA_LEADER_MODEL"
ENV_LEADER_BASE_URL = "HIMA_LEADER_BASE_URL"
ENV_LEADER_API_KEY = "HIMA_LEADER_API_KEY"
# One key per deployment axis; no value of one constrains another.
ENV_SERVICES = "HIMA_SERVICES"
ENV_WEBUI = "HIMA_WEBUI"
ENV_GAME = "HIMA_GAME"
ENV_UI = "HIMA_UI"
# Also read by the game process (hima_dht_game.main), which inherits this
# process's environment; the contract is documented in .env.example.
ENV_LOG_LEVEL = "HIMA_LOG_LEVEL"
# Blizzard AI and Machine Learning License acceptance, consumed only by the
# game-image build (docker/game.Dockerfile); no HIMA_ prefix — it is the
# compose build-arg name. No default, never persisted.
ENV_SC2_LICENSE = "SC2_LICENSE"

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class Difficulty(str, Enum):
    """SC2 built-in AI difficulty levels accepted by the game entry."""

    VeryEasy = "VeryEasy"
    Easy = "Easy"
    Medium = "Medium"
    MediumHard = "MediumHard"
    Hard = "Hard"
    Harder = "Harder"
    VeryHard = "VeryHard"
    CheatVision = "CheatVision"
    CheatMoney = "CheatMoney"
    CheatInsane = "CheatInsane"


class Race(str, Enum):
    """SC2 playable races accepted as the enemy race."""

    Protoss = "Protoss"
    Zerg = "Zerg"
    Terran = "Terran"


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    help="HIMA experiment automation",
)

AdvisorPortOption = Annotated[int, typer.Option(envvar=ENV_ADVISOR_PORT)]
WebuiPortOption = Annotated[int, typer.Option(envvar=ENV_WEBUI_PORT)]
LeaderModelOption = Annotated[str, typer.Option(envvar=ENV_LEADER_MODEL)]
LeaderBaseUrlOption = Annotated[str, typer.Option(envvar=ENV_LEADER_BASE_URL)]
LeaderApiKeyOption = Annotated[str, typer.Option(envvar=ENV_LEADER_API_KEY)]
ServicesOption = Annotated[Placement, typer.Option("--services", envvar=ENV_SERVICES)]
WebuiOption = Annotated[bool, typer.Option("--webui", envvar=ENV_WEBUI)]
GameOption = Annotated[Placement, typer.Option("--game", envvar=ENV_GAME)]
UiOption = Annotated[experiment.ObservationUI, typer.Option("--ui", envvar=ENV_UI)]


def main() -> int:
    load_dotenv(RUN_ROOT / ".env")
    logging.basicConfig(
        level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL),
        format=LOG_FORMAT,
    )
    try:
        app()
    except CommandError as error:
        print(f"hima: {error}", file=sys.stderr)
        return 1
    return 0


@app.command()
def up(
    placement: ServicesOption = Placement.HOST,
    webui: WebuiOption = False,
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    webui_port: WebuiPortOption = server.DEFAULT_PORT,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
    base_url: LeaderBaseUrlOption = DEFAULT_LEADER_BASE_URL,
    api_key: LeaderApiKeyOption = DEFAULT_LEADER_API_KEY,
    manifest_out: Annotated[Path | None, typer.Option("--manifest-out")] = None,
) -> None:
    """Launch the managed services and verify the leader endpoint."""
    services.up(
        services.ServiceOptions(
            placement=placement,
            webui=webui,
            advisor_port=port,
            webui_port=webui_port,
            model=model,
            leader_base_url=base_url,
            leader_api_key=api_key,
        ),
        manifest_out,
    )


@app.command()
def down() -> None:
    """Stop services started by hima."""
    services.down()


@app.command()
def status(
    webui: WebuiOption = False,
    game: GameOption = Placement.CONTAINER,
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    webui_port: WebuiPortOption = server.DEFAULT_PORT,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
    base_url: LeaderBaseUrlOption = DEFAULT_LEADER_BASE_URL,
    api_key: LeaderApiKeyOption = DEFAULT_LEADER_API_KEY,
) -> None:
    """Report service and game state; exit 1 when a check fails."""
    ok = services.status(
        services.ServiceOptions(
            webui=webui,
            advisor_port=port,
            webui_port=webui_port,
            model=model,
            leader_base_url=base_url,
            leader_api_key=api_key,
        ),
        game,
    )
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def run(
    ctx: typer.Context,
    difficulty: Annotated[Difficulty, typer.Option()] = Difficulty.Hard,
    enemy_race: Annotated[Race, typer.Option()] = Race.Zerg,
    seed: Annotated[int, typer.Option()] = 3,
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    advisor_host: Annotated[str, typer.Option(envvar=ENV_ADVISOR_HOST)] = DEFAULT_ADVISOR_HOST,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
    base_url: LeaderBaseUrlOption = DEFAULT_LEADER_BASE_URL,
    api_key: LeaderApiKeyOption = DEFAULT_LEADER_API_KEY,
    realtime: Annotated[bool, typer.Option("--realtime")] = False,
    game: GameOption = Placement.CONTAINER,
    ui: UiOption = experiment.ObservationUI.NONE,
    webui_port: WebuiPortOption = server.DEFAULT_PORT,
    sc2_license: Annotated[str | None, typer.Option(envvar=ENV_SC2_LICENSE)] = None,
) -> None:
    """Play one game and archive its outputs under runs/."""
    observation = experiment.ObservationOptions(ui=ui, webui_url=f"http://localhost:{webui_port}")
    options = experiment.RunOptions(
        difficulty=difficulty.value,
        enemy_race=enemy_race.value,
        seed=seed,
        port=port,
        advisor_host=advisor_host,
        model=model,
        base_url=base_url,
        api_key=api_key,
        realtime=realtime,
        observation=observation,
    )
    if game is Placement.CONTAINER:
        _reject_host_flags(ctx)
        experiment.run_container(
            experiment.ContainerRunOptions(
                game_args=_container_args(ctx, options),
                model=options.model,
                api_key=options.api_key,
                sc2_license=sc2_license,
                observation=observation,
            )
        )
        return
    experiment.run_host(options)


# Host-topology flags meaningless inside the game container, mapped to the
# HIMA_* key the container resolves instead (docker-compose.yml).
_HOST_FLAG_KEYS = {
    "port": ENV_ADVISOR_PORT,
    "advisor_host": ENV_ADVISOR_HOST,
    "base_url": ENV_LEADER_BASE_URL,
    "api_key": ENV_LEADER_API_KEY,
}


def _reject_host_flags(ctx: typer.Context) -> None:
    explicit = [
        (param, key)
        for param, key in _HOST_FLAG_KEYS.items()
        if ctx.get_parameter_source(param) is ParameterSource.COMMANDLINE
    ]
    if not explicit:
        return
    flags = ", ".join(f"--{param.replace('_', '-')}" for param, _ in explicit)
    keys = ", ".join(key for _, key in explicit)
    raise CommandError(
        f"{flags} cannot combine with --game container — the game container resolves "
        f"these from its environment; set {keys} in .env or export them instead"
    )


def _container_args(ctx: typer.Context, options: experiment.RunOptions) -> list[str]:
    # Only flags passed explicitly on the command line forward into the
    # container; environment- and default-sourced values resolve inside it,
    # keeping the precedence chain (flag > environment > .env > default).
    values = {
        "difficulty": options.difficulty,
        "enemy_race": options.enemy_race,
        "seed": str(options.seed),
        "model": options.model,
    }
    args = [
        part
        for param, value in values.items()
        if ctx.get_parameter_source(param) is ParameterSource.COMMANDLINE
        for part in (f"--{param.replace('_', '-')}", value)
    ]
    if ctx.get_parameter_source("realtime") is ParameterSource.COMMANDLINE:
        args.append("--realtime")
    return args


@app.command()
def metrics() -> None:
    """Aggregate metric.json across runs/."""
    report()


@app.command()
def replay(replay: Annotated[Path, typer.Argument()]) -> None:
    """Open a replay in the pysc2 renderer."""
    play(replay)


@app.command()
def export(
    replay: Annotated[Path, typer.Argument()],
    sample: Annotated[int, typer.Option()] = DEFAULT_SAMPLE_INTERVAL,
    logs: Annotated[Path | None, typer.Option()] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
) -> None:
    """Export a replay to a standalone HTML viewer."""
    target = viewer.build(viewer.ExportRequest(replay, sample, out, logs))
    print(f"viewer written: {target}")


@app.command()
def view(
    path: Annotated[Path, typer.Argument()],
    sample: Annotated[int, typer.Option()] = DEFAULT_SAMPLE_INTERVAL,
) -> None:
    """Export when needed, then open the HTML viewer."""
    viewer.view(path, sample)


@app.command()
def serve(
    host: Annotated[str, typer.Option(envvar=ENV_WEBUI_HOST)] = server.DEFAULT_HOST,
    port: Annotated[int, typer.Option(envvar=ENV_WEBUI_PORT)] = server.DEFAULT_PORT,
) -> None:
    """Serve the game observation web UI."""
    _serve(host, port)


def _serve(host: str, port: int) -> None:
    web_app = server.create_default_app()
    try:
        uvicorn.run(web_app, host=host, port=port)
    except SystemExit as error:
        if error.code != STARTUP_FAILURE:
            raise
        raise CommandError(f"cannot serve on {host}:{port}: address already in use") from error
