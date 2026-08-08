"""Unit tests for hima_dht_cli.services._docker (compose-delegated services).

Test cases:
- test_container_names_parses_json_array: pre-v2.21 compose emits one
  JSON array instead of NDJSON; both parse to the same mapping.
- test_container_names_missing_service_raises: compose listing no
  container for a managed service raises CommandError naming it.
- test_game_image_present_reflects_inspect_exit: `docker image inspect`
  exit 0 reports the image present; non-zero reports it absent.
"""

import json
from types import SimpleNamespace

import pytest

from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import _docker


def test_container_names_parses_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"Service": "advisor", "Name": "hima-advisor-1"},
        {"Service": "webui", "Name": "hima-webui-1"},
    ]

    def fake_read(args: list[str]) -> str:
        return json.dumps(rows)

    monkeypatch.setattr(_docker, "_read_compose", fake_read)

    assert _docker.container_names() == {
        "advisor": "hima-advisor-1",
        "webui": "hima-webui-1",
    }


def test_container_names_missing_service_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(args: list[str]) -> str:
        return json.dumps([{"Service": "advisor", "Name": "hima-advisor-1"}])

    monkeypatch.setattr(_docker, "_read_compose", fake_read)

    with pytest.raises(CommandError, match="webui"):
        _docker.container_names()


@pytest.mark.parametrize(
    "exit_code,present",
    [
        (0, True),  # image found in the local store
        (1, False),  # inspect reports no such image
    ],
)
def test_game_image_present_reflects_inspect_exit(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, present: bool
) -> None:
    def fake_run(argv: list[str], capture_output: bool, text: bool) -> SimpleNamespace:
        assert argv == ["docker", "image", "inspect", _docker.GAME_IMAGE]
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(_docker.subprocess, "run", fake_run)

    assert _docker.game_image_present() is present
