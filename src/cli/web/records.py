"""Observation record schema: sampling during play, folding into a payload.

Record kinds and payload shape: docs/design-observation.md.
"""
import json
from itertools import chain
from pathlib import Path
from typing import Iterable, TextIO

from sc2.bot_ai_internal import BotAIInternal
from sc2.unit import Unit

DEFAULT_SAMPLE_INTERVAL = 8
OWNER_SELF = 1
OWNER_ENEMY = 2
FRAME_FIELDS = ("t", "m", "g", "su", "sc", "u")


class GameSampler:
    """Write the JSONL record file for one game while an AI object steps.

    `step` opens the file on its first call and appends `meta`, `type`, and
    `frame` records; `finish` appends the `end` record and closes the file.
    """

    def __init__(self, path: Path, sample_interval: int = DEFAULT_SAMPLE_INTERVAL) -> None:
        self.path = path
        self.sample_interval = sample_interval
        self._type_index: dict[str, int] = {}
        self._handle: TextIO | None = None

    def step(self, ai: BotAIInternal, iteration: int) -> None:
        if self._handle is None:
            self._begin(ai)
        if iteration % self.sample_interval:
            return
        self._write(self._frame_record(ai))

    def finish(self, result: str) -> None:
        if self._handle is None:
            self._handle = self.path.open("w", encoding="utf-8")
        self._write({"k": "end", "result": result})
        self._handle.close()
        self._handle = None

    def _begin(self, ai: BotAIInternal) -> None:
        self._handle = self.path.open("w", encoding="utf-8")
        area = ai.game_info.playable_area
        self._write({
            "k": "meta",
            "map": ai.game_info.map_name,
            "playable": [area.x, area.y, area.width, area.height],
            "neutral": _neutral_entries(ai),
        })

    def _frame_record(self, ai: BotAIInternal) -> dict:
        own = (self._unit_entry(unit, OWNER_SELF) for unit in chain(ai.units, ai.structures))
        enemy = (self._unit_entry(unit, OWNER_ENEMY)
                 for unit in chain(ai.enemy_units, ai.enemy_structures))
        return {
            "k": "frame",
            "t": round(ai.time, 1),
            "m": ai.minerals,
            "g": ai.vespene,
            "su": int(ai.supply_used),
            "sc": int(ai.supply_cap),
            "u": list(chain(own, enemy)),
        }

    def _unit_entry(self, unit: Unit, owner: int) -> list:
        index = self._type_index.get(unit.name)
        if index is None:
            index = len(self._type_index)
            self._type_index[unit.name] = index
            self._write({"k": "type", "name": unit.name,
                         "r": round(unit.radius, 2), "s": int(unit.is_structure)})
        return [index, round(unit.position.x, 1), round(unit.position.y, 1),
                owner, round(unit.health_percentage, 2)]

    def _write(self, record: dict) -> None:
        assert self._handle is not None
        self._handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._handle.flush()


def _neutral_entries(ai: BotAIInternal) -> list[list[float | str]]:
    minerals = [[round(f.position.x, 1), round(f.position.y, 1), "m"] for f in ai.mineral_field]
    geysers = [[round(g.position.x, 1), round(g.position.y, 1), "g"] for g in ai.vespene_geyser]
    return minerals + geysers


def fold_records(path: Path) -> dict:
    """Fold one record file into the game payload parts.

    Returns `{meta, types, type_meta, neutral, frames, result}`; `result` stays
    None while the file has no `end` record. Raises FileNotFoundError when the
    record file does not exist and ValueError on an unknown record kind.
    """
    with path.open(encoding="utf-8") as handle:
        return fold_lines(handle)


def fold_lines(lines: Iterable[str]) -> dict:
    """Fold record lines into the same payload parts as `fold_records`.

    Raises ValueError on an unknown record kind.
    """
    payload: dict = {"meta": {}, "types": [], "type_meta": [],
                     "neutral": [], "frames": [], "result": None}
    for line in lines:
        _fold_line(payload, json.loads(line))
    return payload


def _fold_line(payload: dict, record: dict) -> None:
    kind = record["k"]
    if kind == "meta":
        payload["meta"] = {"map": record["map"], "playable": record["playable"]}
        payload["neutral"] = record["neutral"]
    elif kind == "type":
        payload["types"].append(record["name"])
        payload["type_meta"].append({"r": record["r"], "s": record["s"]})
    elif kind == "frame":
        payload["frames"].append({field: record[field] for field in FRAME_FIELDS})
    elif kind == "end":
        payload["result"] = record["result"]
    else:
        raise ValueError(f"unknown record kind {kind!r}")
