"""Unit tests for hima_dht_game.sampler (GameSampler).

Test cases:
- test_sampler_roundtrip_matches_folded_payload: records written by GameSampler
  fold back into the payload matching the stub game state.
- test_sampler_skips_iterations_between_intervals: off-interval iteration
  appends no frame record.
- test_sampler_finish_without_step_writes_end_only: finish on an unstarted
  sampler yields a file holding only the end record.
"""
from dataclasses import dataclass, field
from pathlib import Path

from hima_dht_game.sampler import GameSampler
from hima_dht_records import fold_records


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
