"""Observation record contract: schema constants and payload folding.

Record kinds and payload shape: docs/design-observation.md.
"""
import json
from pathlib import Path
from typing import Iterable

# One record file name shared by the writer (GameSampler) and every reader.
RECORD_FILE = "frames.jsonl"
# Run-layout directory names, resolved against each entry point's working
# directory.
RUNS_DIRNAME = "runs"
TMP_DIRNAME = "tmp"
DEFAULT_SAMPLE_INTERVAL = 8
FRAME_FIELDS = ("t", "m", "g", "su", "sc", "u")


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
