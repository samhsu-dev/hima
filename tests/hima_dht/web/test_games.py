"""Unit tests for hima_dht.web.games (GameStore).

Test cases:
- test_list_games_returns_archived_runs_newest_first: archived entries carry
  id, result, and time from metric.json, sorted newest first.
- test_list_games_prepends_live_entry_without_end_record: an unfinished
  tmp record file yields a leading live entry.
- test_list_games_omits_live_entry_after_end_record: a finished tmp record
  file yields no live entry.
- test_payload_assembles_records_and_logs: payload folds records and parses
  logs into the exported-page shape with live False for archived games.
- test_payload_live_game_sets_live_flag: an unfinished live game reports
  live True.
- test_payload_live_game_carries_stream_offset: a live payload's stream
  offset covers exactly the folded complete lines; a partial trailing line
  stays out of both. Archived payloads carry no stream field.
- test_payload_unknown_id_raises_key_error: unknown id raises KeyError.
- test_payload_traversal_id_raises_key_error: a path-traversal id raises
  KeyError instead of escaping runs_dir.
- test_payload_without_record_file_raises_file_not_found: a run without
  frames.jsonl raises FileNotFoundError for the 409 mapping.
"""
import json
from pathlib import Path

import pytest

from hima_dht.web.games import GameStore

META_LINE = '{"k":"meta","map":"TestMap","playable":[2,2,100,120],"neutral":[]}'
FRAME_LINE = '{"k":"frame","t":9.5,"m":50,"g":0,"su":12,"sc":15,"u":[]}'
END_LINE = '{"k":"end","result":"Victory"}'


def make_run(runs_dir: Path, name: str, result: str) -> Path:
    directory = runs_dir / name
    directory.mkdir(parents=True)
    (directory / "metric.json").write_text(
        json.dumps({"result": result, "time": "9:30"}), encoding="utf-8")
    (directory / "frames.jsonl").write_text(
        "\n".join([META_LINE, FRAME_LINE, END_LINE]) + "\n", encoding="utf-8")
    (directory / "output.txt").write_text(
        "0:10\nFinal Actions Summary:<TRAIN SCV>\n", encoding="utf-8")
    (directory / "command.txt").write_text("0:12 <TRAIN SCV>\n", encoding="utf-8")
    return directory


def make_store(tmp_path: Path) -> GameStore:
    (tmp_path / "tmp").mkdir(exist_ok=True)
    return GameStore(tmp_path / "runs", tmp_path / "tmp")


def test_list_games_returns_archived_runs_newest_first(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_run(store.runs_dir, "20260101_a", "Defeat")
    make_run(store.runs_dir, "20260202_b", "Victory")

    games = store.list_games()

    assert games == [{"id": "20260202_b", "result": "Victory", "time": "9:30"},
                     {"id": "20260101_a", "result": "Defeat", "time": "9:30"}]


def test_list_games_prepends_live_entry_without_end_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    (store.tmp_dir / "frames.jsonl").write_text(
        META_LINE + "\n" + FRAME_LINE + "\n", encoding="utf-8")

    games = store.list_games()

    assert games[0]["id"] == "live"


def test_list_games_omits_live_entry_after_end_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    (store.tmp_dir / "frames.jsonl").write_text(
        "\n".join([META_LINE, FRAME_LINE, END_LINE]) + "\n", encoding="utf-8")

    assert store.list_games() == []


def test_payload_assembles_records_and_logs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_run(store.runs_dir, "20260101_a", "Victory")

    payload = store.payload("20260101_a")

    assert payload["meta"] == {"map": "TestMap", "playable": [2, 2, 100, 120],
                               "replay": "20260101_a", "result": "Victory", "duration": 9.5}
    assert payload["frames"] == [{"t": 9.5, "m": 50, "g": 0, "su": 12, "sc": 15, "u": []}]
    assert payload["decisions"] == [{"t": 10, "n": 1, "s": "<TRAIN SCV>"}]
    assert payload["commands"] == [{"t": 12, "a": "TRAIN SCV", "st": "ok"}]
    assert payload["live"] is False


def test_payload_live_game_sets_live_flag(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    (store.tmp_dir / "frames.jsonl").write_text(
        META_LINE + "\n" + FRAME_LINE + "\n", encoding="utf-8")

    payload = store.payload("live")

    assert payload["live"] is True
    assert payload["meta"]["result"] is None


def test_payload_live_game_carries_stream_offset(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    complete = META_LINE + "\n" + FRAME_LINE + "\n"
    (store.tmp_dir / "frames.jsonl").write_text(
        complete + '{"k":"frame","t":10', encoding="utf-8")
    make_run(store.runs_dir, "20260101_a", "Victory")

    live = store.payload("live")
    archived = store.payload("20260101_a")

    assert live["stream"] == {"records": len(complete.encode("utf-8"))}
    assert len(live["frames"]) == 1
    assert "stream" not in archived


def test_payload_unknown_id_raises_key_error(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(KeyError):
        store.payload("absent")


def test_payload_traversal_id_raises_key_error(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    make_run(store.runs_dir, "20260101_a", "Victory")

    with pytest.raises(KeyError):
        store.payload("../runs/20260101_a")


def test_payload_without_record_file_raises_file_not_found(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    run_dir = make_run(store.runs_dir, "20260101_a", "Victory")
    (run_dir / "frames.jsonl").unlink()

    with pytest.raises(FileNotFoundError):
        store.payload("20260101_a")