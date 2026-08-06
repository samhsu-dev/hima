"""Unit tests for cli.web.server (HTTP surface).

Test cases:
- test_index_page_links_archived_game: the index page lists an archived run
  with a link to its observation page.
- test_index_page_reports_empty_store: an empty store renders the no-games row.
- test_api_games_returns_game_list: /api/games returns the store listing.
- test_game_page_injects_payload: /games/{id} returns the template with the
  payload injected in place of the placeholder.
- test_api_game_returns_payload: /api/games/{id} returns the payload JSON.
- test_unknown_game_returns_404: an unknown id maps KeyError to HTTP 404.
- test_missing_record_returns_409_naming_export: a run without frames.jsonl
  maps FileNotFoundError to HTTP 409 with a detail naming `hima export`.
- test_serve_bound_port_raises_command_error: serving on a bound port raises
  CommandError instead of exiting the process.
- test_live_stream_replays_finished_game: /api/live/stream on a finished tmp
  record file returns every record as SSE events and closes.
- test_live_stream_resumes_from_query_offsets: records/decisions/commands
  query parameters skip the events the client already holds.
- test_live_page_injects_stream_offset: /games/live injects a payload with
  live true and the stream offset for the EventSource query.
"""
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cli.errors import CommandError
from cli.web.games import GameStore
from cli.web.server import create_app, serve

META_LINE = '{"k":"meta","map":"TestMap","playable":[2,2,100,120],"neutral":[]}'
FRAME_LINE = '{"k":"frame","t":9.5,"m":50,"g":0,"su":12,"sc":15,"u":[]}'
END_LINE = '{"k":"end","result":"Victory"}'


def make_run(runs_dir: Path, name: str) -> Path:
    directory = runs_dir / name
    directory.mkdir(parents=True)
    (directory / "metric.json").write_text(
        json.dumps({"result": "Victory", "time": "9:30"}), encoding="utf-8")
    (directory / "frames.jsonl").write_text(
        "\n".join([META_LINE, FRAME_LINE, END_LINE]) + "\n", encoding="utf-8")
    return directory


def make_client(tmp_path: Path) -> TestClient:
    (tmp_path / "tmp").mkdir(exist_ok=True)
    store = GameStore(tmp_path / "runs", tmp_path / "tmp")
    return TestClient(create_app(store))


def test_index_page_links_archived_game(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    make_run(tmp_path / "runs", "20260101_a")

    response = client.get("/")

    assert response.status_code == 200
    assert '<a href="/games/20260101_a">' in response.text


def test_index_page_reports_empty_store(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/")

    assert "no games recorded yet" in response.text


def test_api_games_returns_game_list(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    make_run(tmp_path / "runs", "20260101_a")

    response = client.get("/api/games")

    assert response.json() == [{"id": "20260101_a", "result": "Victory", "time": "9:30"}]


def test_game_page_injects_payload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    make_run(tmp_path / "runs", "20260101_a")

    response = client.get("/games/20260101_a")

    assert response.status_code == 200
    assert "__HIMA_DATA_JSON__" not in response.text
    assert '"map":"TestMap"' in response.text


def test_api_game_returns_payload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    make_run(tmp_path / "runs", "20260101_a")

    payload = client.get("/api/games/20260101_a").json()

    assert payload["meta"]["map"] == "TestMap"
    assert payload["live"] is False


def test_unknown_game_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/games/absent")

    assert response.status_code == 404


def test_missing_record_returns_409_naming_export(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_dir = make_run(tmp_path / "runs", "20260101_a")
    (run_dir / "frames.jsonl").unlink()

    response = client.get("/api/games/20260101_a")

    assert response.status_code == 409
    assert "hima export" in response.json()["detail"]


def write_live_game(tmp_path: Path, *record_lines: str) -> None:
    (tmp_path / "tmp" / "frames.jsonl").write_text(
        "".join(line + "\n" for line in record_lines), encoding="utf-8")
    (tmp_path / "tmp" / "output.txt").write_text(
        "0:10\nFinal Actions Summary:<TRAIN SCV>\n", encoding="utf-8")
    (tmp_path / "tmp" / "command.txt").write_text("0:12 <TRAIN SCV>\n", encoding="utf-8")


def test_live_stream_replays_finished_game(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    write_live_game(tmp_path, META_LINE, FRAME_LINE, END_LINE)

    response = client.get("/api/live/stream")

    assert response.headers["content-type"].startswith("text/event-stream")
    names = [line for line in response.text.splitlines() if line.startswith("event: ")]
    assert names == ["event: meta", "event: frame", "event: decision",
                     "event: command", "event: end"]


def test_live_stream_resumes_from_query_offsets(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    write_live_game(tmp_path, META_LINE, FRAME_LINE, END_LINE)
    offset = len((META_LINE + "\n" + FRAME_LINE + "\n").encode("utf-8"))

    response = client.get(
        f"/api/live/stream?records={offset}&decisions=1&commands=1")

    names = [line for line in response.text.splitlines() if line.startswith("event: ")]
    assert names == ["event: end"]


def test_live_page_injects_stream_offset(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    write_live_game(tmp_path, META_LINE, FRAME_LINE)

    response = client.get("/games/live")

    assert response.status_code == 200
    assert '"live":true' in response.text
    assert '"stream":{"records":' in response.text


def test_serve_bound_port_raises_command_error() -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        with pytest.raises(CommandError):
            serve("127.0.0.1", port)
