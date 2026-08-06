"""Unit tests for cli.patches (site-packages source patches).

Test cases:
- test_patch_colors_pristine_wheel_line_patched: the exact colors.py line the
  PySC2 4.0.0 wheel ships (with its trailing comment) is found and replaced.
- test_patch_colors_already_patched_reports_noop: a marker-carrying file is
  left unchanged and reported as already patched.
"""
from pathlib import Path

from cli import patches

PRISTINE_COLORS = (
    "def shuffled_hue(scale):\n"
    "  palette = list(hue(scale))\n"
    "  random.shuffle(palette, lambda: 0.5)  # Return a fixed shuffle\n"
    "  return numpy.array(palette, dtype=numpy.uint8)\n"
)


def test_patch_colors_pristine_wheel_line_patched(tmp_path: Path) -> None:
    target = tmp_path / "colors.py"
    target.write_text(PRISTINE_COLORS, encoding="utf-8")

    message = patches._patch_colors(target)

    assert message == "colors.py: patched"
    assert patches._COLORS_MARKER in target.read_text(encoding="utf-8")


def test_patch_colors_already_patched_reports_noop(tmp_path: Path) -> None:
    target = tmp_path / "colors.py"
    target.write_text(PRISTINE_COLORS, encoding="utf-8")
    patches._patch_colors(target)
    patched = target.read_text(encoding="utf-8")

    message = patches._patch_colors(target)

    assert message == "colors.py: already patched"
    assert target.read_text(encoding="utf-8") == patched
