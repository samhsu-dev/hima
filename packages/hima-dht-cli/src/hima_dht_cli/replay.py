"""Open a replay in the pysc2 human renderer."""

import subprocess
import sys
from pathlib import Path

from hima_dht_cli.errors import CommandError


def play(replay_path: Path) -> None:
    if not replay_path.exists():
        raise CommandError(f"replay not found: {replay_path}")
    argv = [
        # pysc2.bin.play behind the in-process compatibility shims
        # (pysc2_play); site-packages carries no patches.
        sys.executable,
        "-m",
        "hima_dht_cli.pysc2_play",
        "--replay",
        str(replay_path.resolve()),
        # The macOS retail client crashes on the RGB render interface; feature
        # layers only.
        "--rgb_screen_size",
        "0",
        "--rgb_minimap_size",
        "0",
    ]
    subprocess.run(argv)
