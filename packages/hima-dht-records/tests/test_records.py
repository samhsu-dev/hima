"""Unit tests for hima_dht_records.records (fold_records, fold_lines).

Test cases:
- test_fold_records_synthetic_file_builds_payload: complete record file folds
  into the full payload shape.
- test_fold_records_without_end_record_keeps_none_result: live file (no end
  record) folds with result None.
- test_fold_records_missing_file_raises_file_not_found: absent path propagates
  FileNotFoundError.
- test_fold_records_unknown_kind_raises_value_error: unknown `k` raises
  ValueError.
- test_fold_lines_matches_fold_records: folding in-memory lines yields the
  same payload as folding the file they were written to.
"""
from pathlib import Path

import pytest

from hima_dht_records import fold_lines, fold_records


def write_records(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


COMPLETE_LINES = [
    '{"k":"meta","map":"TestMap","playable":[2,2,100,120],"neutral":[[10.0,20.0,"m"]]}',
    '{"k":"type","name":"SCV","r":0.38,"s":0}',
    '{"k":"frame","t":1.0,"m":50,"g":0,"su":12,"sc":15,"u":[[0,30.0,40.0,1,1.0]]}',
    '{"k":"end","result":"Victory"}',
]


def test_fold_records_synthetic_file_builds_payload(tmp_path: Path) -> None:
    path = write_records(tmp_path / "frames.jsonl", COMPLETE_LINES)

    payload = fold_records(path)

    assert payload == {
        "meta": {"map": "TestMap", "playable": [2, 2, 100, 120]},
        "types": ["SCV"],
        "type_meta": [{"r": 0.38, "s": 0}],
        "neutral": [[10.0, 20.0, "m"]],
        "frames": [{"t": 1.0, "m": 50, "g": 0, "su": 12, "sc": 15, "u": [[0, 30.0, 40.0, 1, 1.0]]}],
        "result": "Victory",
    }


def test_fold_lines_matches_fold_records(tmp_path: Path) -> None:
    path = write_records(tmp_path / "frames.jsonl", COMPLETE_LINES)

    assert fold_lines(COMPLETE_LINES) == fold_records(path)


def test_fold_records_without_end_record_keeps_none_result(tmp_path: Path) -> None:
    path = write_records(tmp_path / "frames.jsonl", COMPLETE_LINES[:-1])

    payload = fold_records(path)

    assert payload["result"] is None


def test_fold_records_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fold_records(tmp_path / "absent.jsonl")


def test_fold_records_unknown_kind_raises_value_error(tmp_path: Path) -> None:
    path = write_records(tmp_path / "frames.jsonl", ['{"k":"bogus"}'])

    with pytest.raises(ValueError, match="bogus"):
        fold_records(path)
