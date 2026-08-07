"""Filesystem layout shared by every hima command."""

from pathlib import Path

from hima_dht_records import RECORD_FILE, RUNS_DIRNAME, TMP_DIRNAME

# The run layout anchors to the invoking process's working directory; `hima`
# runs from the repository root or any chosen run directory.
RUN_ROOT = Path.cwd()
TMP_DIR = RUN_ROOT / TMP_DIRNAME
RUNS_DIR = RUN_ROOT / RUNS_DIRNAME
SERVICE_DIR = TMP_DIR / "services"
SC2_APP = Path("/Applications/StarCraft II")

GAME_OUTPUTS = ("command.txt", "input.txt", "output.txt", "prompt.txt", "metric.json", RECORD_FILE)
