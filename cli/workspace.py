"""Filesystem layout shared by every hima command."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / "tmp"
RUNS_DIR = REPO_ROOT / "runs"
SERVICE_DIR = TMP_DIR / "services"
SC2_APP = Path("/Applications/StarCraft II")

RECORD_FILE = "frames.jsonl"
GAME_OUTPUTS = ("command.txt", "input.txt", "output.txt", "prompt.txt", "metric.json", RECORD_FILE)
