"""Decision and command log parsing into observation records.

Record shapes: docs/design-observation.md. An absent log file yields an
empty list; the observation page renders without that panel.
"""
import re
from pathlib import Path

DECISION_LOG = "output.txt"
COMMAND_LOG = "command.txt"
TIMESTAMP_RE = re.compile(r"^(\d+):(\d{2})$")
COMMAND_RE = re.compile(r"^(\d+):(\d{2})\s+<([^>]+)>\s*(\S*)\s*$")
ACTION_RE = re.compile(r"<([^>]+)>")
SUMMARY_PREFIX = "Final Actions Summary:"
MAX_SHOWN_ACTIONS = 24


def parse_decisions(path: Path) -> list[dict]:
    """Parse leader decision records `{t, n, s}` from the decision log."""
    if not path.exists():
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


def parse_commands(path: Path) -> list[dict]:
    """Parse executed command records `{t, a, st}` from the command log."""
    if not path.exists():
        return []
    commands: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = COMMAND_RE.match(line.strip())
        if not match:
            continue
        seconds = int(match.group(1)) * 60 + int(match.group(2))
        commands.append({"t": seconds, "a": match.group(3), "st": match.group(4) or "ok"})
    return commands


def _decision_entry(seconds: int, actions_text: str) -> dict:
    actions = ACTION_RE.findall(actions_text)
    shown = " ".join(f"<{action}>" for action in actions[:MAX_SHOWN_ACTIONS])
    if len(actions) > MAX_SHOWN_ACTIONS:
        shown += " …"
    return {"t": seconds, "n": len(actions), "s": shown}
