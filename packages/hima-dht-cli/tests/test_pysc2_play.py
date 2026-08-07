"""Unit tests for hima_dht_cli.pysc2_play (pysc2 compatibility shims).

Test cases:
- test_fixed_shuffle_replicates_pre_311_shuffle: the in-place permutation
  equals what random.shuffle(items, lambda: 0.5) produced before 3.11.
- test_version_tolerant_get_passes_known_version: a version the table
  knows resolves through the wrapped lookup unchanged.
- test_version_tolerant_get_falls_back_on_unknown_version: a version
  missing from the table falls back to the no-version default lookup.
"""
from hima_dht_cli.pysc2_play import fixed_shuffle, version_tolerant_get


def test_fixed_shuffle_replicates_pre_311_shuffle() -> None:
    items = list(range(8))

    fixed_shuffle(items)

    assert items == [0, 5, 1, 7, 2, 6, 3, 4]


def test_version_tolerant_get_passes_known_version() -> None:
    get = version_tolerant_get(lambda version=None: ("config", version))

    assert get(version="5.0.16") == ("config", "5.0.16")


def test_version_tolerant_get_falls_back_on_unknown_version() -> None:
    def table_lookup(version=None):
        if version is not None:
            raise ValueError(f"unknown version: {version}")
        return ("config", "latest")

    get = version_tolerant_get(table_lookup)

    assert get(version="9.9.99") == ("config", "latest")
