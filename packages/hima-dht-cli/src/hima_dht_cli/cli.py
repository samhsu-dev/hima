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
from uvicorn.config import STARTUP_FAILURE

from hima_dht_cli import experiment, services, viewer
from hima_dht_cli.errors import CommandError
from hima_dht_cli.metrics import report
from hima_dht_cli.replay import play
from hima_dht_cli.services import (
    DEFAULT_ADVISOR_HOST,
    DEFAULT_ADVISOR_PORT,
    DEFAULT_LEADER_MODEL,
)
from hima_dht_cli.workspace import RUN_ROOT
from hima_dht_records import DEFAULT_SAMPLE_INTERVAL
from hima_dht_web import server

DEFAULT_LEADER_BASE_URL = "http://localhost:11434/v1"
# Ollama accepts any bearer token; a remote provider needs its real key.
DEFAULT_LEADER_API_KEY = "ollama"

# Environment keys shared with docker-compose.yml interpolation (.env.example).
ENV_ADVISOR_HOST = "HIMA_ADVISOR_HOST"
ENV_ADVISOR_PORT = "HIMA_ADVISOR_PORT"
ENV_WEBUI_HOST = "HIMA_WEBUI_HOST"
ENV_WEBUI_PORT = "HIMA_WEBUI_PORT"
ENV_LEADER_MODEL = "HIMA_LEADER_MODEL"
ENV_LEADER_BASE_URL = "HIMA_LEADER_BASE_URL"
ENV_LEADER_API_KEY = "HIMA_LEADER_API_KEY"
ENV_SERVICE_BACKEND = "HIMA_SERVICE_BACKEND"
ENV_OLLAMA_PORT = "HIMA_OLLAMA_PORT"
# Also read by the game process (hima_dht_game.main), which inherits this
# process's environment; the contract is documented in .env.example.
ENV_LOG_LEVEL = "HIMA_LOG_LEVEL"

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
BackendOption = Annotated[services.ServiceBackend, typer.Option(envvar=ENV_SERVICE_BACKEND)]
OllamaPortOption = Annotated[int, typer.Option(envvar=ENV_OLLAMA_PORT)]


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
    backend: BackendOption = services.ServiceBackend.NATIVE,
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    webui_port: WebuiPortOption = server.DEFAULT_PORT,
    ollama_port: OllamaPortOption = services.DEFAULT_OLLAMA_PORT,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
    skip_pull: Annotated[bool, typer.Option("--skip-pull")] = False,
    manifest_out: Annotated[Path | None, typer.Option("--manifest-out")] = None,
) -> None:
    """Launch advisor, Ollama, and the webui, wait until healthy."""
    services.up(
        services.ServiceOptions(
            backend=backend,
            advisor_port=port,
            webui_port=webui_port,
            ollama_port=ollama_port,
            model=model,
        ),
        skip_pull,
        manifest_out,
    )


@app.command()
def down() -> None:
    """Stop services started by hima."""
    services.down()


@app.command()
def status(
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    webui_port: WebuiPortOption = server.DEFAULT_PORT,
    ollama_port: OllamaPortOption = services.DEFAULT_OLLAMA_PORT,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
) -> None:
    """Report service and game state."""
    services.status(
        services.ServiceOptions(
            advisor_port=port,
            webui_port=webui_port,
            ollama_port=ollama_port,
            model=model,
        )
    )


@app.command()
def run(
    difficulty: Annotated[Difficulty, typer.Option()] = Difficulty.Hard,
    enemy_race: Annotated[Race, typer.Option()] = Race.Zerg,
    seed: Annotated[int, typer.Option()] = 3,
    port: AdvisorPortOption = DEFAULT_ADVISOR_PORT,
    advisor_host: Annotated[str, typer.Option(envvar=ENV_ADVISOR_HOST)] = DEFAULT_ADVISOR_HOST,
    model: LeaderModelOption = DEFAULT_LEADER_MODEL,
    base_url: Annotated[str, typer.Option(envvar=ENV_LEADER_BASE_URL)] = DEFAULT_LEADER_BASE_URL,
    api_key: Annotated[str, typer.Option(envvar=ENV_LEADER_API_KEY)] = DEFAULT_LEADER_API_KEY,
    realtime: Annotated[bool, typer.Option("--realtime")] = False,
) -> None:
    """Play one game and archive its outputs under runs/."""
    experiment.run(
        experiment.RunOptions(
            difficulty=difficulty.value,
            enemy_race=enemy_race.value,
            seed=seed,
            port=port,
            advisor_host=advisor_host,
            model=model,
            base_url=base_url,
            api_key=api_key,
            realtime=realtime,
        )
    )


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
