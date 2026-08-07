"""Replay-to-frames export through the SC2 engine.

burnysc2 7.3.0 `run_replay()` accepts `observed_id` but never forwards it to
`_play_replay`, which then resolves Race.NoRace and crashes; the replay is
hosted directly here with an explicit player id.
"""
import asyncio
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import _play_replay, _setup_replay, get_replay_version
from sc2.observer_ai import ObserverAI
from sc2.sc2process import SC2Process
from sc2.unit import Unit

from hima_dht.errors import CommandError
from hima_dht_game.sampler import GameSampler
from hima_dht_records import fold_records

OBSERVED_PLAYER_ID = 1


class ReplayExporter(ObserverAI):
    """Drive a GameSampler while the engine steps the replay."""

    def __init__(self, sampler: GameSampler) -> None:
        super().__init__()
        self.sampler = sampler

    async def on_step(self, iteration: int) -> None:
        self.sampler.step(self, iteration)

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


def export_frames(replay_path: Path, sample_interval: int, record_path: Path) -> dict:
    """Step the replay through the SC2 engine; write the record file and
    return viewer-ready frame data folded from it."""
    # The SC2 process resolves the path from its own working directory, so a
    # relative path yields "Unable to open replay".
    replay_path = replay_path.resolve()
    if not replay_path.exists():
        raise CommandError(f"replay not found: {replay_path}")
    sampler = GameSampler(record_path, sample_interval)
    engine_result = asyncio.run(_host(replay_path, ReplayExporter(sampler)))
    sampler.finish(_result_label(replay_path.stem, engine_result))
    return _page_data(fold_records(record_path), replay_path.name)


def _page_data(payload: dict, replay_name: str) -> dict:
    duration = payload["frames"][-1]["t"] if payload["frames"] else 0.0
    return {
        "meta": {**payload["meta"], "replay": replay_name,
                 "result": payload["result"], "duration": duration},
        "types": payload["types"],
        "type_meta": payload["type_meta"],
        "neutral": payload["neutral"],
        "frames": payload["frames"],
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
