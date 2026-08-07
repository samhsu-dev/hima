"""Unit tests for hima_dht.web.records (GameSampler, fold_records).

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
- test_sampler_roundtrip_matches_folded_payload: records written by GameSampler
  fold back into the payload matching the stub game state.
- test_sampler_skips_iterations_between_intervals: off-interval iteration
  appends no frame record.
- test_sampler_finish_without_step_writes_end_only: finish on an unstarted
  sampler yields a file holding only the end record.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hima_dht.web.records import GameSampler, fold_lines, fold_records


@dataclass
class StubPosition:
    x: float
    y: float


@dataclass
class StubUnit:
    name: str
    radius: float
    is_structure: bool
    position: StubPosition
    health_percentage: float


@dataclass
class StubArea:
    x: int
    y: int
    width: int
    height: int


@dataclass
class StubGameInfo:
    map_name: str
    playable_area: StubArea


@dataclass
class StubAI:
    game_info: StubGameInfo
    time: float = 0.0
    minerals: int = 50
    vespene: int = 0
    supply_used: float = 12.0
    supply_cap: float = 15.0
    mineral_field: list = field(default_factory=list)
    vespene_geyser: list = field(default_factory=list)
    units: list = field(default_factory=list)
    structures: list = field(default_factory=list)
    enemy_units: list = field(default_factory=list)
    enemy_structures: list = field(default_factory=list)


def make_stub_ai() -> StubAI:
    return StubAI(
        game_info=StubGameInfo("TestMap", StubArea(2, 2, 100, 120)),
        mineral_field=[StubUnit("MineralField", 1.1, False, StubPosition(10.0, 20.0), 1.0)],
        vespene_geyser=[StubUnit("VespeneGeyser", 1.2, False, StubPosition(12.0, 22.0), 1.0)],
        units=[StubUnit("SCV", 0.38, False, StubPosition(30.0, 40.0), 1.0)],
        structures=[StubUnit("CommandCenter", 2.75, True, StubPosition(31.0, 41.0), 0.8)],
        enemy_units=[StubUnit("Zergling", 0.38, False, StubPosition(50.0, 60.0), 0.5)],
    )


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


def test_sampler_roundtrip_matches_folded_payload(tmp_path: Path) -> None:
    ai = make_stub_ai()
    sampler = GameSampler(tmp_path / "frames.jsonl", sample_interval=8)

    sampler.step(ai, 0)
    ai.time = 5.7
    sampler.step(ai, 8)
    sampler.finish("Defeat")

    payload = fold_records(sampler.path)
    assert payload["meta"] == {"map": "TestMap", "playable": [2, 2, 100, 120]}
    assert payload["neutral"] == [[10.0, 20.0, "m"], [12.0, 22.0, "g"]]
    assert payload["types"] == ["SCV", "CommandCenter", "Zergling"]
    assert payload["type_meta"] == [{"r": 0.38, "s": 0}, {"r": 2.75, "s": 1}, {"r": 0.38, "s": 0}]
    assert [frame["t"] for frame in payload["frames"]] == [0.0, 5.7]
    assert payload["frames"][1]["u"] == [
        [0, 30.0, 40.0, 1, 1.0],
        [1, 31.0, 41.0, 1, 0.8],
        [2, 50.0, 60.0, 2, 0.5],
    ]
    assert payload["result"] == "Defeat"


def test_sampler_skips_iterations_between_intervals(tmp_path: Path) -> None:
    ai = make_stub_ai()
    sampler = GameSampler(tmp_path / "frames.jsonl", sample_interval=8)

    sampler.step(ai, 0)
    sampler.step(ai, 3)
    sampler.finish("Tie")

    payload = fold_records(sampler.path)
    assert len(payload["frames"]) == 1


def test_sampler_finish_without_step_writes_end_only(tmp_path: Path) -> None:
    sampler = GameSampler(tmp_path / "frames.jsonl", sample_interval=8)

    sampler.finish("Defeat")

    payload = fold_records(sampler.path)
    assert payload == {"meta": {}, "types": [], "type_meta": [],
                       "neutral": [], "frames": [], "result": "Defeat"}
