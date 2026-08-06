"""Replay-to-frames export through the SC2 engine.

burnysc2 7.3.0 `run_replay()` accepts `observed_id` but never forwards it to
`_play_replay`, which then resolves Race.NoRace and crashes; the replay is
hosted directly here with an explicit player id.
"""
import asyncio
from itertools import chain
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import _play_replay, _setup_replay, get_replay_version
from sc2.observer_ai import ObserverAI
from sc2.sc2process import SC2Process
from sc2.unit import Unit

from cli.errors import CommandError

OBSERVED_PLAYER_ID = 1
DEFAULT_SAMPLE_INTERVAL = 8
OWNER_SELF = 1
OWNER_ENEMY = 2


class ReplayExporter(ObserverAI):
    """Record sampled game-state frames while the engine steps the replay."""

    def __init__(self, sample_interval: int) -> None:
        super().__init__()
        self.sample_interval = sample_interval
        self.frames: list[dict] = []
        self.type_names: list[str] = []
        self.type_meta: list[dict] = []
        self.neutral: list[list[float | str]] = []
        self.meta: dict = {}
        self._type_index: dict[str, int] = {}

    async def on_step(self, iteration: int) -> None:
        if iteration == 0:
            self._capture_static()
        if iteration % self.sample_interval:
            return
        self.frames.append(self._snapshot())

    def _capture_static(self) -> None:
        area = self.game_info.playable_area
        self.meta = {
            "map": self.game_info.map_name,
            "playable": [area.x, area.y, area.width, area.height],
        }
        for field in self.mineral_field:
            self.neutral.append([round(field.position.x, 1), round(field.position.y, 1), "m"])
        for geyser in self.vespene_geyser:
            self.neutral.append([round(geyser.position.x, 1), round(geyser.position.y, 1), "g"])

    def _snapshot(self) -> dict:
        own = (self._unit_tuple(unit, OWNER_SELF) for unit in chain(self.units, self.structures))
        enemy = (self._unit_tuple(unit, OWNER_ENEMY) for unit in chain(self.enemy_units, self.enemy_structures))
        return {
            "t": round(self.time, 1),
            "m": self.minerals,
            "g": self.vespene,
            "su": int(self.supply_used),
            "sc": int(self.supply_cap),
            "u": list(chain(own, enemy)),
        }

    # issue_events() fires the full BotAI event surface, but ObserverAI omits
    # these four handlers; the first morphing unit would otherwise abort the
    # replay with AttributeError.
    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        return

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        return

    async def on_enemy_unit_entered_vision(self, unit: Unit) -> None:
        return

    async def on_enemy_unit_left_vision(self, unit_tag: int) -> None:
        return

    def _unit_tuple(self, unit: Unit, owner: int) -> list:
        index = self._type_index.get(unit.name)
        if index is None:
            index = len(self.type_names)
            self._type_index[unit.name] = index
            self.type_names.append(unit.name)
            self.type_meta.append({"r": round(unit.radius, 2), "s": int(unit.is_structure)})
        return [
            index,
            round(unit.position.x, 1),
            round(unit.position.y, 1),
            owner,
            round(unit.health_percentage, 2),
        ]


def export_frames(replay_path: Path, sample_interval: int) -> dict:
    """Step the replay through the SC2 engine; return viewer-ready frame data."""
    # The SC2 process resolves the path from its own working directory, so a
    # relative path yields "Unable to open replay".
    replay_path = replay_path.resolve()
    if not replay_path.exists():
        raise CommandError(f"replay not found: {replay_path}")
    exporter = ReplayExporter(sample_interval)
    result = asyncio.run(_host(replay_path, exporter))
    duration = exporter.frames[-1]["t"] if exporter.frames else 0.0
    return {
        "meta": {
            **exporter.meta,
            "replay": replay_path.name,
            "result": _result_label(replay_path.stem, result),
            "duration": duration,
        },
        "types": exporter.type_names,
        "type_meta": exporter.type_meta,
        "neutral": exporter.neutral,
        "frames": exporter.frames,
    }


async def _host(replay_path: Path, exporter: ReplayExporter):
    base_build, data_version = get_replay_version(str(replay_path))
    async with SC2Process(fullscreen=False, base_build=base_build, data_hash=data_version) as server:
        client = await _setup_replay(server, str(replay_path), False, OBSERVED_PLAYER_ID)
        return await _play_replay(client, exporter, False, player_id=OBSERVED_PLAYER_ID)


def _result_label(replay_stem: str, engine_result: object) -> str:
    # HIMA names replays <stamp>_<difficulty>_<race>_<result>; the engine's
    # observer-side result is unreliable, the filename records the real one.
    tail = replay_stem.rsplit("_", 1)[-1]
    if tail in {"Victory", "Defeat", "Tie"}:
        return tail
    return str(engine_result).rsplit(".", 1)[-1]
