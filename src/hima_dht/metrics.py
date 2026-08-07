"""Aggregate metric.json across archived runs into one table."""
import json
from pathlib import Path

from hima_dht.workspace import RUNS_DIR, TMP_DIR

COLUMNS = ("result", "time", "agent_call", "apu", "rur", "pbr")


def report() -> None:
    rows = _collect()
    if not rows:
        print("no metric.json found — run `hima run` first")
        return
    _print_table(rows)


def _collect() -> list[tuple[str, dict]]:
    rows = []
    if RUNS_DIR.exists():
        for metric_path in sorted(RUNS_DIR.glob("*/metric.json")):
            rows.append((metric_path.parent.name, _load(metric_path)))
    unarchived = TMP_DIR / "metric.json"
    if unarchived.exists():
        rows.append(("(unarchived tmp)", _load(unarchived)))
    return rows


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _print_table(rows: list[tuple[str, dict]]) -> None:
    name_width = max(len(name) for name, _ in rows)
    header = "  ".join([f"{'run':<{name_width}}"] + [f"{column:>10}" for column in COLUMNS])
    print(header)
    print("-" * len(header))
    for name, metric in rows:
        cells = [f"{_format(metric.get(column)):>10}" for column in COLUMNS]
        print("  ".join([f"{name:<{name_width}}"] + cells))


def _format(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None:
        return "-"
    return str(value)
