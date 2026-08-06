"""Build and open the standalone replay viewer HTML."""
import json
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from cli.errors import CommandError
from cli.export import export_frames
from cli.web.logs import COMMAND_LOG, DECISION_LOG, parse_commands, parse_decisions

DATA_PLACEHOLDER = "__HIMA_DATA_JSON__"
TEMPLATE_PATH = Path(__file__).with_name("player_template.html")


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
    data = export_frames(request.replay, request.sample_interval)
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


def render(data: dict) -> str:
    """Inject one game payload into the player template; returns the page HTML."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return template.replace(DATA_PLACEHOLDER, payload)


def _open(path: Path) -> None:
    print(f"opening {path}")
    webbrowser.open(path.resolve().as_uri())
