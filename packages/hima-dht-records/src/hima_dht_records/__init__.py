"""Observation record contract shared by the record writer and readers."""
from hima_dht_records.records import (
    DEFAULT_SAMPLE_INTERVAL,
    FRAME_FIELDS,
    RECORD_FILE,
    RUNS_DIRNAME,
    TMP_DIRNAME,
    fold_lines,
    fold_records,
)

__all__ = [
    "DEFAULT_SAMPLE_INTERVAL",
    "FRAME_FIELDS",
    "RECORD_FILE",
    "RUNS_DIRNAME",
    "TMP_DIRNAME",
    "fold_lines",
    "fold_records",
]
