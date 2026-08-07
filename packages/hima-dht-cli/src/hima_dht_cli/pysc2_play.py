"""pysc2.bin.play launcher with in-process compatibility shims.

The pysc2 4.0.0 wheel predates Python 3.11 and SC2 5.0.16; the shims fix
both on the imported modules, so site-packages stays pristine and every
`uv sync` leaves the fixes intact. Runs as a subprocess of `hima replay`
(pysc2's absl flag parsing and the pygame window need their own process).
"""


def fixed_shuffle(items: list) -> None:
    """Shuffle in place exactly as `random.shuffle(items, lambda: 0.5)`
    did before Python 3.11 removed the `random` argument."""
    for i in reversed(range(1, len(items))):
        j = int(0.5 * (i + 1))
        items[i], items[j] = items[j], items[i]


def apply_shims() -> None:
    """Patch the imported pysc2 modules for Python 3.12 and retail replays.

    Must run before `pysc2.bin.play` is imported: its module chain builds
    feature palettes through `colors.shuffled_hue`.
    """
    import numpy
    from pysc2 import run_configs
    from pysc2.lib import colors

    def shuffled_hue(scale: int):
        palette = list(colors.smooth_hue_palette(scale))
        fixed_shuffle(palette)
        return numpy.array(palette)

    colors.shuffled_hue = shuffled_hue
    run_configs.get = version_tolerant_get(run_configs.get)


def version_tolerant_get(get):
    """Wrap `run_configs.get`: a replay version that postdates pysc2's
    version table falls back to the installed 'latest' build — the build
    that recorded local replays."""

    def wrapped(version=None):
        try:
            return get(version=version)
        except ValueError:
            return get()

    return wrapped


def main() -> None:
    apply_shims()
    from absl import app
    from pysc2.bin import play

    app.run(play.main)


if __name__ == "__main__":
    main()
