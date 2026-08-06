"""Build and open the standalone replay viewer HTML."""
import json
import re
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from cli.errors import CommandError
from cli.export import export_frames

DATA_PLACEHOLDER = "__HIMA_DATA_JSON__"
TEMPLATE_PATH = Path(__file__).with_name("player_template.html")
TIMESTAMP_RE = re.compile(r"^(\d+):(\d{2})$")
COMMAND_RE = re.compile(r"^(\d+):(\d{2})\s+<([^>]+)>\s*(\S*)\s*$")
ACTION_RE = re.compile(r"<([^>]+)>")
SUMMARY_PREFIX = "Final Actions Summary:"
MAX_SHOWN_ACTIONS = 24


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
    data["decisions"] = _parse_decisions(logs_dir / "output.txt")
    data["commands"] = _parse_commands(logs_dir / "command.txt")
    target = request.out or request.replay.parent / f"{request.replay.stem}.viewer.html"
    target.write_text(_render(data), encoding="utf-8")
    return target


def view(path: Path, sample_interval: int) -> None:
    if path.suffix == ".html":
        _open(path)
        return
    target = path.parent / f"{path.stem}.viewer.html"
    if not target.exists():
        target = build(ExportRequest(path, sample_interval, None, None))
    _open(target)


def _render(data: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return template.replace(DATA_PLACEHOLDER, payload)


def _open(path: Path) -> None:
    print(f"opening {path}")
    webbrowser.open(path.resolve().as_uri())


def _parse_decisions(path: Path) -> list[dict]:
    if not path.exists():
        print(f"note: {path} missing — the viewer will have no decision timeline")
        return []
    decisions: list[dict] = []
    pending_time = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stamp = TIMESTAMP_RE.match(line.strip())
        if stamp:
            pending_time = int(stamp.group(1)) * 60 + int(stamp.group(2))
            continue
        if line.startswith(SUMMARY_PREFIX):
            decisions.append(_decision_entry(pending_time, line[len(SUMMARY_PREFIX):]))
    return decisions


def _decision_entry(seconds: int, actions_text: str) -> dict:
    actions = ACTION_RE.findall(actions_text)
    shown = " ".join(f"<{action}>" for action in actions[:MAX_SHOWN_ACTIONS])
    if len(actions) > MAX_SHOWN_ACTIONS:
        shown += " …"
    return {"t": seconds, "n": len(actions), "s": shown}


def _parse_commands(path: Path) -> list[dict]:
    if not path.exists():
        print(f"note: {path} missing — the viewer will have no command feed")
        return []
    commands: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = COMMAND_RE.match(line.strip())
        if not match:
            continue
        seconds = int(match.group(1)) * 60 + int(match.group(2))
        commands.append({"t": seconds, "a": match.group(3), "st": match.group(4) or "ok"})
    return commands
