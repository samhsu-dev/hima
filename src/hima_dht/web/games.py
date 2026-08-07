"""Game listing and payload assembly for the observation server.

Payload shape and error mapping: docs/design-observation.md.
"""
import json
from pathlib import Path

from hima_dht.web.logs import COMMAND_LOG, DECISION_LOG, parse_commands, parse_decisions
from hima_dht.web.records import fold_lines
from hima_dht.workspace import RECORD_FILE

LIVE_GAME_ID = "live"
END_SCAN_BYTES = 4096


class GameStore:
    """Enumerate observable games and assemble their payloads."""

    def __init__(self, runs_dir: Path, tmp_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.tmp_dir = tmp_dir

    def list_games(self) -> list[dict]:
        """List archived runs, newest first, preceded by the live game when
        one is in progress."""
        games = self._archived_entries()
        live = self._live_entry()
        if live is not None:
            games.insert(0, live)
        return games

    def payload(self, game_id: str) -> dict:
        """Assemble one game's payload.

        A live payload carries `stream.records`, the record-file byte offset
        the live stream continues from. Raises KeyError when the id names no
        game and FileNotFoundError when the game has no record file (the
        caller names the `hima export` fallback).
        """
        directory = self._game_dir(game_id)
        folded, record_offset = _fold_snapshot(directory / RECORD_FILE)
        payload = {
            "meta": {**folded["meta"], "replay": _replay_name(directory, game_id),
                     "result": folded["result"], "duration": _duration(folded["frames"])},
            "types": folded["types"],
            "type_meta": folded["type_meta"],
            "neutral": folded["neutral"],
            "frames": folded["frames"],
            "decisions": parse_decisions(directory / DECISION_LOG),
            "commands": parse_commands(directory / COMMAND_LOG),
            "live": game_id == LIVE_GAME_ID and folded["result"] is None,
        }
        if payload["live"]:
            payload["stream"] = {"records": record_offset}
        return payload

    def _game_dir(self, game_id: str) -> Path:
        if game_id == LIVE_GAME_ID:
            return self.tmp_dir
        directory = self.runs_dir / game_id
        if game_id != Path(game_id).name or not directory.is_dir():
            raise KeyError(game_id)
        return directory

    def _archived_entries(self) -> list[dict]:
        if not self.runs_dir.is_dir():
            return []
        names = sorted((entry.name for entry in self.runs_dir.iterdir() if entry.is_dir()),
                       reverse=True)
        return [self._archived_entry(name) for name in names]

    def _archived_entry(self, name: str) -> dict:
        metric_path = self.runs_dir / name / "metric.json"
        metric = json.loads(metric_path.read_text(encoding="utf-8")) if metric_path.exists() else {}
        return {"id": name, "result": metric.get("result"), "time": metric.get("time")}

    def _live_entry(self) -> dict | None:
        record_path = self.tmp_dir / RECORD_FILE
        if not record_path.exists() or _has_end_record(record_path):
            return None
        return {"id": LIVE_GAME_ID, "result": None, "time": None}


def _fold_snapshot(record_path: Path) -> tuple[dict, int]:
    """Fold the record file's complete lines; returns the fold and its byte length.

    A trailing line without a newline is still being written and stays out of
    both the fold and the offset, so the live stream replays it in full.
    """
    data = record_path.read_bytes()
    offset = data.rfind(b"\n") + 1
    return fold_lines(data[:offset].decode("utf-8").splitlines()), offset


def _has_end_record(record_path: Path) -> bool:
    with record_path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - END_SCAN_BYTES))
        tail = handle.read().decode("utf-8", errors="replace")
    lines = [line for line in tail.splitlines() if line.strip()]
    return bool(lines) and '"k":"end"' in lines[-1]


def _replay_name(directory: Path, game_id: str) -> str:
    replays = sorted(directory.glob("*.SC2Replay"))
    return replays[0].name if replays else game_id


def _duration(frames: list[dict]) -> float:
    return frames[-1]["t"] if frames else 0.0
