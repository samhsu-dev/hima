"""Filesystem layout shared by every hima command."""
from pathlib import Path

# The run layout anchors to the invoking process's working directory; `hima`
# runs from the repository root or any chosen run directory.
RUN_ROOT = Path.cwd()
TMP_DIR = RUN_ROOT / "tmp"
RUNS_DIR = RUN_ROOT / "runs"
SERVICE_DIR = TMP_DIR / "services"
SC2_APP = Path("/Applications/StarCraft II")

RECORD_FILE = "frames.jsonl"
GAME_OUTPUTS = ("command.txt", "input.txt", "output.txt", "prompt.txt", "metric.json", RECORD_FILE)
