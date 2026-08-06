"""Unit tests for cli.web.logs (parse_decisions, parse_commands).

Test cases:
- test_parse_decisions_reads_timestamp_and_summary: summary lines pair with the
  preceding timestamp into `{t, n, s}` records.
- test_parse_decisions_truncates_shown_actions_at_limit: more than
  MAX_SHOWN_ACTIONS actions truncate the shown string with an ellipsis.
- test_parse_decisions_missing_file_yields_empty_list: absent log returns [].
- test_parse_commands_reads_time_action_status: command lines parse into
  `{t, a, st}` with explicit status kept.
- test_parse_commands_defaults_status_to_ok: a line without status gets "ok".
- test_parse_commands_skips_non_matching_lines: prose lines produce no record.
- test_parse_commands_missing_file_yields_empty_list: absent log returns [].
"""
from pathlib import Path

from cli.web.logs import MAX_SHOWN_ACTIONS, parse_commands, parse_decisions


def write_log(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_decisions_reads_timestamp_and_summary(tmp_path: Path) -> None:
    path = write_log(tmp_path / "output.txt",
                     "1:05\nsome reasoning\nFinal Actions Summary:<TRAIN SCV> <BUILD DEPOT>\n")

    decisions = parse_decisions(path)

    assert decisions == [{"t": 65, "n": 2, "s": "<TRAIN SCV> <BUILD DEPOT>"}]


def test_parse_decisions_truncates_shown_actions_at_limit(tmp_path: Path) -> None:
    actions = " ".join(f"<A{index}>" for index in range(MAX_SHOWN_ACTIONS + 1))
    path = write_log(tmp_path / "output.txt", f"0:10\nFinal Actions Summary:{actions}\n")

    decisions = parse_decisions(path)

    assert decisions[0]["n"] == MAX_SHOWN_ACTIONS + 1
    assert decisions[0]["s"].endswith("…")


def test_parse_decisions_missing_file_yields_empty_list(tmp_path: Path) -> None:
    assert parse_decisions(tmp_path / "output.txt") == []


def test_parse_commands_reads_time_action_status(tmp_path: Path) -> None:
    path = write_log(tmp_path / "command.txt", "2:30 <ATTACK> done\n")

    commands = parse_commands(path)

    assert commands == [{"t": 150, "a": "ATTACK", "st": "done"}]


def test_parse_commands_defaults_status_to_ok(tmp_path: Path) -> None:
    path = write_log(tmp_path / "command.txt", "0:07 <TRAIN MARINE>\n")

    commands = parse_commands(path)

    assert commands == [{"t": 7, "a": "TRAIN MARINE", "st": "ok"}]


def test_parse_commands_skips_non_matching_lines(tmp_path: Path) -> None:
    path = write_log(tmp_path / "command.txt", "queue flushed\n0:07 <STOP>\n")

    commands = parse_commands(path)

    assert [command["a"] for command in commands] == ["STOP"]


def test_parse_commands_missing_file_yields_empty_list(tmp_path: Path) -> None:
    assert parse_commands(tmp_path / "command.txt") == []
