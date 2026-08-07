"""Live game tailing: server-sent events past a client's stream cursor.

Event kinds and the mid-join contract: docs/design-observation.md.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from hima_dht_records import RECORD_FILE
from hima_dht_web.logs import COMMAND_LOG, DECISION_LOG, parse_commands, parse_decisions

POLL_INTERVAL = 1.0
END_KIND = "end"


@dataclass
class StreamCursor:
    """Per-client progress: record-file byte offset and log entry counts."""

    records: int = 0
    decisions: int = 0
    commands: int = 0


async def live_events(tmp_dir: Path, cursor: StreamCursor) -> AsyncIterator[str]:
    """Yield SSE-framed record, decision, and command events appended past the
    cursor; ends after the `end` record is forwarded."""
    while True:
        events, ended = _drain(tmp_dir, cursor)
        for kind, data in events:
            yield f"event: {kind}\ndata: {data}\n\n"
        if ended:
            return
        await asyncio.sleep(POLL_INTERVAL)


def _drain(tmp_dir: Path, cursor: StreamCursor) -> tuple[list[tuple[str, str]], bool]:
    records, ended = _drain_records(tmp_dir / RECORD_FILE, cursor)
    logs = _drain_logs(tmp_dir, cursor)
    if not ended:
        return records + logs, False
    # The client closes its EventSource on `end`, so it must be the final event.
    body = [event for event in records if event[0] != END_KIND]
    tail = [event for event in records if event[0] == END_KIND]
    return body + logs + tail, True


def _drain_records(path: Path, cursor: StreamCursor) -> tuple[list[tuple[str, str]], bool]:
    text, consumed = _read_complete_lines(path, cursor.records)
    cursor.records += consumed
    events = [(json.loads(line)["k"], line) for line in text.splitlines()]
    return events, any(kind == END_KIND for kind, _ in events)


def _drain_logs(tmp_dir: Path, cursor: StreamCursor) -> list[tuple[str, str]]:
    decisions = parse_decisions(tmp_dir / DECISION_LOG)
    commands = parse_commands(tmp_dir / COMMAND_LOG)
    events = [("decision", _compact(entry)) for entry in decisions[cursor.decisions:]]
    events += [("command", _compact(entry)) for entry in commands[cursor.commands:]]
    cursor.decisions, cursor.commands = len(decisions), len(commands)
    return events


def _read_complete_lines(path: Path, offset: int) -> tuple[str, int]:
    """Read complete lines from a byte offset; returns the text and its length.

    A trailing line without a newline is still being written and is left for
    the next poll. An absent file reads as empty (the game has not started)."""
    if not path.exists():
        return "", 0
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    end = data.rfind(b"\n") + 1
    return data[:end].decode("utf-8"), end


def _compact(entry: dict) -> str:
    return json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
