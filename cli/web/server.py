"""HTTP surface of the observation server.

Routes and error mapping: docs/design-observation.md.
"""
import html

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from uvicorn.config import STARTUP_FAILURE

from cli.errors import CommandError
from cli.viewer import render
from cli.web.games import GameStore
from cli.web.stream import StreamCursor, live_events
from cli.workspace import RUNS_DIR, TMP_DIR

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8123
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
MISSING_RECORD_DETAIL = (
    "game has no record file; run `hima export <replay>` to build a standalone viewer")
LIVE_RESULT_LABEL = "in progress"
EVENT_STREAM_MEDIA_TYPE = "text/event-stream"
INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>hima games</title></head>
<body>
<h1>hima games</h1>
<ul>
{rows}</ul>
</body>
</html>
"""
EMPTY_ROW = "<li>no games recorded yet</li>\n"


def create_app(store: GameStore) -> FastAPI:
    """Build the observation app over one GameStore."""
    app = FastAPI(title="hima observation")
    _register_pages(app, store)
    _register_api(app, store)
    _register_stream(app, store)
    return app


def create_default_app() -> FastAPI:
    """Build the app over the workspace layout; `hima up`'s uvicorn factory target."""
    return create_app(GameStore(RUNS_DIR, TMP_DIR))


def serve(host: str, port: int) -> None:
    """Serve games from the workspace layout; CommandError when the port is bound."""
    app = create_default_app()
    try:
        uvicorn.run(app, host=host, port=port)
    except SystemExit as error:
        if error.code != STARTUP_FAILURE:
            raise
        raise CommandError(f"cannot serve on {host}:{port}: address already in use") from error


def _register_pages(app: FastAPI, store: GameStore) -> None:
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _index_page(store.list_games())

    @app.get("/games/{game_id}", response_class=HTMLResponse)
    def game_page(game_id: str) -> str:
        return render(_payload(store, game_id))


def _register_api(app: FastAPI, store: GameStore) -> None:
    @app.get("/api/games")
    def list_games() -> list[dict]:
        return store.list_games()

    @app.get("/api/games/{game_id}")
    def game_payload(game_id: str) -> dict:
        return _payload(store, game_id)


def _register_stream(app: FastAPI, store: GameStore) -> None:
    @app.get("/api/live/stream")
    def live_stream(records: int = 0, decisions: int = 0, commands: int = 0) -> StreamingResponse:
        cursor = StreamCursor(records=records, decisions=decisions, commands=commands)
        return StreamingResponse(live_events(store.tmp_dir, cursor),
                                 media_type=EVENT_STREAM_MEDIA_TYPE)


def _payload(store: GameStore, game_id: str) -> dict:
    try:
        return store.payload(game_id)
    except KeyError as error:
        raise HTTPException(HTTP_NOT_FOUND, f"unknown game: {game_id}") from error
    except FileNotFoundError as error:
        raise HTTPException(HTTP_CONFLICT, MISSING_RECORD_DETAIL) from error


def _index_page(games: list[dict]) -> str:
    rows = "".join(_game_row(game) for game in games)
    return INDEX_TEMPLATE.format(rows=rows or EMPTY_ROW)


def _game_row(game: dict) -> str:
    game_id = html.escape(game["id"], quote=True)
    label = " ".join(part for part in (game["result"] or LIVE_RESULT_LABEL, game["time"]) if part)
    return f'<li><a href="/games/{game_id}">{game_id}</a> — {html.escape(label)}</li>\n'
