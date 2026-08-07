"""Shared fixtures for the hima-dht-cli test suite."""

from pathlib import Path

import pytest

from hima_dht_cli.services import _lifecycle


@pytest.fixture(autouse=True)
def _isolated_service_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keeps up/down tests from contending on the repo's service lock file.
    monkeypatch.setattr(_lifecycle, "LOCK_FILE", tmp_path / "up-down.lock")
