"""HTTP surface of the observation server.

Routes and error mapping: docs/design-observation.md.
"""

import html
import json
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from hima_dht_records import RUNS_DIRNAME, TMP_DIRNAME
from hima_dht_web.games import GameEntry, GameStore
from hima_dht_web.stream import StreamCursor, live_events

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8123
# The injection marker inside player_template.html's payload script tag.
DATA_PLACEHOLDER = "__HIMA_DATA_JSON__"
TEMPLATE_RESOURCE = files("hima_dht_web") / "_resources" / "templates" / "player_template.html"
# The injection marker inside index_template.html's table body.
ROWS_PLACEHOLDER = "__HIMA_ROWS__"
INDEX_RESOURCE = files("hima_dht_web") / "_resources" / "templates" / "index_template.html"
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
MISSING_RECORD_DETAIL = (
    "game has no record file; run `hima export <replay>` to build a standalone viewer"
)
LIVE_RESULT_LABEL = "in progress"
EVENT_STREAM_MEDIA_TYPE = "text/event-stream"
EMPTY_ROW = '<tr><td colspan="3">no games recorded yet</td></tr>\n'


def create_app(store: GameStore) -> FastAPI:
    """Build the observation app over one GameStore."""
    app = FastAPI(title="hima observation")
    _register_pages(app, store)
    _register_api(app, store)
    _register_stream(app, store)
    return app


def create_default_app() -> FastAPI:
    """Build the app over the run layout at the working directory; the
    `uvicorn --factory` target for the webui."""
    root = Path.cwd()
    return create_app(GameStore(root / RUNS_DIRNAME, root / TMP_DIRNAME))


def render(data: dict) -> str:
    """Inject one game payload into the player template; returns the page HTML."""
    template = TEMPLATE_RESOURCE.read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return template.replace(DATA_PLACEHOLDER, payload)


def _register_pages(app: FastAPI, store: GameStore) -> None:
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _index_page(store.list_games())

    @app.get("/games/{game_id}", response_class=HTMLResponse)
    def game_page(game_id: str) -> str:
        return render(_payload(store, game_id))


def _register_api(app: FastAPI, store: GameStore) -> None:
    @app.get("/api/games")
    def list_games() -> list[GameEntry]:
        return store.list_games()

    @app.get("/api/games/{game_id}")
    def game_payload(game_id: str) -> dict:
        return _payload(store, game_id)


def _register_stream(app: FastAPI, store: GameStore) -> None:
    @app.get("/api/live/stream")
    def live_stream(records: int = 0, decisions: int = 0, commands: int = 0) -> StreamingResponse:
        cursor = StreamCursor(records=records, decisions=decisions, commands=commands)
        return StreamingResponse(
            live_events(store.tmp_dir, cursor), media_type=EVENT_STREAM_MEDIA_TYPE
        )


def _payload(store: GameStore, game_id: str) -> dict:
    try:
        return store.payload(game_id)
    except KeyError as error:
        raise HTTPException(HTTP_NOT_FOUND, f"unknown game: {game_id}") from error
    except FileNotFoundError as error:
        raise HTTPException(HTTP_CONFLICT, MISSING_RECORD_DETAIL) from error


def _index_page(games: list[GameEntry]) -> str:
    rows = "".join(_game_row(game) for game in games)
    template = INDEX_RESOURCE.read_text(encoding="utf-8")
    return template.replace(ROWS_PLACEHOLDER, rows or EMPTY_ROW)


def _game_row(game: GameEntry) -> str:
    game_id = html.escape(game["id"], quote=True)
    raw_result = game["result"]
    result = LIVE_RESULT_LABEL if raw_result is None else raw_result
    badge_class = "live" if raw_result is None else html.escape(raw_result, quote=True)
    duration = html.escape(game["time"] or "", quote=True)
    return (
        f'<tr><td class="k"><a href="/games/{game_id}">{game_id}</a></td>'
        f'<td><span class="badge {badge_class}">{html.escape(result)}</span></td>'
        f'<td class="num">{duration}</td></tr>\n'
    )
