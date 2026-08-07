"""Unit tests for hima_dht_web.stream (live event tailing).

Test cases:
- test_live_events_forwards_records_until_end: a finished record file streams
  every record as an SSE event and the generator terminates after end.
- test_live_events_orders_end_last: log entries drained together with the end
  record are emitted before the end event.
- test_live_events_resumes_from_cursor: a cursor holding a byte offset and
  entry counts yields only records and log entries past it.
- test_live_events_picks_up_appended_records: records appended after the
  first drain arrive on a later poll.
- test_live_events_holds_back_partial_line: a trailing line without a newline
  is withheld until its newline arrives, then emitted whole.
"""
import asyncio
from pathlib import Path

import pytest

from hima_dht_web import stream
from hima_dht_web.stream import StreamCursor, live_events

META_LINE = '{"k":"meta","map":"TestMap","playable":[2,2,100,120],"neutral":[]}'
FRAME_LINE = '{"k":"frame","t":9.5,"m":50,"g":0,"su":12,"sc":15,"u":[]}'
END_LINE = '{"k":"end","result":"Victory"}'


def write_records(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "frames.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def collect(tmp_path: Path, cursor: StreamCursor) -> list[str]:
    async def run() -> list[str]:
        return [event async for event in live_events(tmp_path, cursor)]
    return asyncio.run(run())


def event_names(events: list[str]) -> list[str]:
    return [event.splitlines()[0] for event in events]


def test_live_events_forwards_records_until_end(tmp_path: Path) -> None:
    write_records(tmp_path, META_LINE, FRAME_LINE, END_LINE)

    events = collect(tmp_path, StreamCursor())

    assert event_names(events) == ["event: meta", "event: frame", "event: end"]


def test_live_events_orders_end_last(tmp_path: Path) -> None:
    write_records(tmp_path, META_LINE, FRAME_LINE, END_LINE)
    (tmp_path / "output.txt").write_text(
        "0:10\nFinal Actions Summary:<TRAIN SCV>\n", encoding="utf-8")
    (tmp_path / "command.txt").write_text("0:12 <TRAIN SCV>\n", encoding="utf-8")

    events = collect(tmp_path, StreamCursor())

    assert event_names(events) == [
        "event: meta", "event: frame", "event: decision", "event: command", "event: end"]


def test_live_events_resumes_from_cursor(tmp_path: Path) -> None:
    path = write_records(tmp_path, META_LINE, FRAME_LINE, END_LINE)
    (tmp_path / "command.txt").write_text(
        "0:12 <TRAIN SCV>\n0:40 <BUILD SUPPLYDEPOT>\n", encoding="utf-8")
    offset = len((META_LINE + "\n" + FRAME_LINE + "\n").encode("utf-8"))
    assert path.stat().st_size > offset

    events = collect(tmp_path, StreamCursor(records=offset, commands=1))

    assert event_names(events) == ["event: command", "event: end"]
    assert '"a":"BUILD SUPPLYDEPOT"' in events[0]


def test_live_events_picks_up_appended_records(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "POLL_INTERVAL", 0.01)
    path = write_records(tmp_path, META_LINE, FRAME_LINE)

    async def scenario() -> list[str]:
        events = []
        generator = live_events(tmp_path, StreamCursor())
        events.append(await generator.__anext__())
        events.append(await generator.__anext__())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(END_LINE + "\n")
        async for event in generator:
            events.append(event)
        return events

    events = asyncio.run(scenario())

    assert event_names(events) == ["event: meta", "event: frame", "event: end"]


def test_live_events_holds_back_partial_line(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "POLL_INTERVAL", 0.01)
    head, tail = END_LINE[:10], END_LINE[10:]
    path = tmp_path / "frames.jsonl"
    path.write_text(META_LINE + "\n" + head, encoding="utf-8")

    async def scenario() -> list[str]:
        events = []
        generator = live_events(tmp_path, StreamCursor())
        events.append(await generator.__anext__())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(tail + "\n")
        async for event in generator:
            events.append(event)
        return events

    events = asyncio.run(scenario())

    assert event_names(events) == ["event: meta", "event: end"]
    assert '"result":"Victory"' in events[1]
