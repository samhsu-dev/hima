"""Build and open the standalone replay viewer HTML."""
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from hima_dht.errors import CommandError
from hima_dht.export import export_frames
from hima_dht_records import RECORD_FILE
from hima_dht_web.logs import COMMAND_LOG, DECISION_LOG, parse_commands, parse_decisions
from hima_dht_web.server import render


@dataclass(frozen=True)
class ExportRequest:
    replay: Path
    sample_interval: int
    out: Path | None
    logs_dir: Path | None


def build(request: ExportRequest) -> Path:
    if not request.replay.exists():
        raise CommandError(f"replay not found: {request.replay}")
    logs_dir = request.logs_dir or request.replay.parent
    data = export_frames(request.replay, request.sample_interval, logs_dir / RECORD_FILE)
    data["decisions"] = parse_decisions(logs_dir / DECISION_LOG)
    data["commands"] = parse_commands(logs_dir / COMMAND_LOG)
    target = request.out or request.replay.parent / f"{request.replay.stem}.viewer.html"
    target.write_text(render(data), encoding="utf-8")
    return target


def view(path: Path, sample_interval: int) -> None:
    if path.suffix == ".html":
        _open(path)
        return
    target = path.parent / f"{path.stem}.viewer.html"
    if not target.exists():
        target = build(ExportRequest(path, sample_interval, None, None))
    _open(target)


def _open(path: Path) -> None:
    print(f"opening {path}")
    webbrowser.open(path.resolve().as_uri())
