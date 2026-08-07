"""Source patches for site-packages that a fresh `uv sync` wipes.

Three installed libraries predate Python 3.12 or SC2 5.0.16 and need local
fixes; each patch is marker-guarded so reapplying is a no-op.
"""
import subprocess
import sys
import sysconfig
from pathlib import Path

from hima_dht.errors import CommandError

_COLORS_TARGET = "random.shuffle(palette, lambda: 0.5)  # Return a fixed shuffle"
_COLORS_MARKER = "replicate the"
_PLAY_TARGET = "run_config = run_configs.get(version=version)  # Replace the run config."
_PLAY_MARKER = "postdates pysc2's version table"
_S2PROTOCOL_MARKER = "importlib.util"

_S2PROTOCOL_VERSIONS = '''
import importlib.util
import os
import re
import sys


def _import_protocol(base_path, protocol_module_name):
    """
    Import a module from a base path, used to import protocol modules.

    The imp module this file originally used was removed in Python 3.12;
    importlib.util is the documented replacement.
    """

    # Try to return the module if it's been loaded already
    try:
        return sys.modules[protocol_module_name]
    except KeyError:
        pass

    spec = importlib.util.spec_from_file_location(
        protocol_module_name, os.path.join(base_path, protocol_module_name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[protocol_module_name] = module
    spec.loader.exec_module(module)
    return module


def list_all(base_path=None):
    """
    Returns a list of the current protocol version file names in the versions module sorted by name.
    """
    if base_path is None:
        base_path = os.path.dirname(__file__)
    pattern = re.compile('.*protocol[0-9]+.py$')
    files = [ f for f in os.listdir(base_path) \\
        if pattern.match(f) ]
    files.sort()
    return files


def latest():
    """
    Import the latest protocol version in the versions module (directory)
    """
    # Find matchng protocol version files
    base_path = os.path.dirname(__file__)
    files = list_all(base_path)

    # Sort using version number, take latest
    latest_version = files[-1]

    # Convert file to module name
    module_name = latest_version.split('.')[0]

    # Perform the import
    return _import_protocol(base_path, module_name)



def build(build_version):
    """
    Get the module for a specific build version
    """
    base_path = os.path.dirname(__file__)
    return _import_protocol(base_path, 'protocol{0:05d}'.format(build_version))
'''


def setup() -> None:
    """Make a fresh checkout runnable: sync dependencies, patch, verify imports."""
    _run_uv_sync()
    for line in apply_patches():
        print(line)
    _verify_imports()
    print("setup complete")


def apply_patches() -> list[str]:
    site = _site_packages()
    return [
        _patch_colors(site / "pysc2" / "lib" / "colors.py"),
        _patch_play(site / "pysc2" / "bin" / "play.py"),
        _patch_s2protocol(site / "s2protocol" / "versions" / "__init__.py"),
    ]


def patch_states() -> list[tuple[str, bool]]:
    site = _site_packages()
    return [
        ("pysc2 colors.py (py3.12 shuffle)", _has_marker(site / "pysc2" / "lib" / "colors.py", _COLORS_MARKER)),
        ("pysc2 play.py (replay version fallback)", _has_marker(site / "pysc2" / "bin" / "play.py", _PLAY_MARKER)),
        ("s2protocol (py3.12 importlib)", _has_marker(site / "s2protocol" / "versions" / "__init__.py", _S2PROTOCOL_MARKER)),
    ]


def _site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def _has_marker(path: Path, marker: str) -> bool:
    return path.exists() and marker in path.read_text(encoding="utf-8")


def _read_target(path: Path) -> str:
    if not path.exists():
        raise CommandError(f"patch target missing: {path} — run `uv sync` first")
    return path.read_text(encoding="utf-8")


def _patch_colors(path: Path) -> str:
    text = _read_target(path)
    if _COLORS_MARKER in text:
        return "colors.py: already patched"
    replaced = _replace_line(text, _COLORS_TARGET, _colors_block, path)
    path.write_text(replaced, encoding="utf-8")
    return "colors.py: patched"


def _colors_block(indent: str) -> str:
    return (
        f"{indent}# random.shuffle's `random` arg was removed in Python 3.11; replicate the\n"
        f"{indent}# fixed shuffle that shuffle(palette, lambda: 0.5) produced.\n"
        f"{indent}for i in reversed(range(1, len(palette))):\n"
        f"{indent}  j = int(0.5 * (i + 1))\n"
        f"{indent}  palette[i], palette[j] = palette[j], palette[i]\n"
    )


def _patch_play(path: Path) -> str:
    text = _read_target(path)
    if _PLAY_MARKER in text:
        return "play.py: already patched"
    replaced = _replace_line(text, _PLAY_TARGET, _play_block, path)
    path.write_text(replaced, encoding="utf-8")
    return "play.py: patched"


def _play_block(indent: str) -> str:
    return (
        f"{indent}try:\n"
        f"{indent}  {_PLAY_TARGET}\n"
        f"{indent}except ValueError:\n"
        f"{indent}  # Replay version postdates pysc2's version table; the installed\n"
        f"{indent}  # 'latest' build is the one that recorded local replays.\n"
        f"{indent}  pass\n"
    )


def _patch_s2protocol(path: Path) -> str:
    text = _read_target(path)
    if _S2PROTOCOL_MARKER in text:
        return "s2protocol: already patched"
    path.write_text(_S2PROTOCOL_VERSIONS, encoding="utf-8")
    return "s2protocol: patched"


def _replace_line(text: str, target: str, block, path: Path):
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() != target:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        lines[index] = block(indent)
        return "".join(lines)
    raise CommandError(f"expected line not found in {path}: {target}")


def _run_uv_sync() -> None:
    try:
        # uv discovers the workspace by walking up from the working directory.
        completed = subprocess.run(["uv", "sync"])
    except FileNotFoundError as error:
        raise CommandError("uv not found on PATH — install from https://docs.astral.sh/uv/") from error
    if completed.returncode != 0:
        raise CommandError(f"uv sync failed with code {completed.returncode}")


def _verify_imports() -> None:
    check = subprocess.run(
        [sys.executable, "-c", "import sc2, pysc2, s2protocol, mpyq"],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        raise CommandError(f"post-setup import check failed:\n{check.stderr.strip()}")
