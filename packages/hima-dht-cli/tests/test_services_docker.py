"""Unit tests for hima_dht_cli.services._docker (compose-delegated services).

Test cases:
- test_container_names_parses_json_array: pre-v2.21 compose emits one
  JSON array instead of NDJSON; both parse to the same mapping.
- test_container_names_missing_service_raises: compose listing no
  container for a managed service raises CommandError naming it.
- test_game_image_present_reflects_inspect_exit: `docker image inspect`
  exit 0 reports the image present; non-zero reports it absent.
- test_ensure_game_image_present_skips_build: an existing image runs no
  compose build.
- test_ensure_game_image_absent_without_license_raises: an absent image
  without SC2_LICENSE raises CommandError naming the variable.
- test_ensure_game_image_builds_with_license_environment: an absent image
  builds via the game profile with SC2_LICENSE in the build environment.
- test_run_game_appends_command_override: forwarded flags become the
  in-container `hima run` command override.
- test_run_game_empty_args_keeps_compose_command: no forwarded flags keep
  the compose-file command.
- test_run_game_nonzero_exit_raises: a non-zero game exit raises
  CommandError carrying the code.
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


def test_ensure_game_image_present_skips_build(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[list[str]] = []
    monkeypatch.setattr(_docker, "game_image_present", lambda: True)
    monkeypatch.setattr(_docker, "_run_compose", lambda args, extra_env=None: built.append(args))

    _docker.ensure_game_image("iagreetotheeula")

    assert built == []


def test_ensure_game_image_absent_without_license_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_docker, "game_image_present", lambda: False)

    with pytest.raises(CommandError, match="SC2_LICENSE"):
        _docker.ensure_game_image(None)


def test_ensure_game_image_builds_with_license_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: dict[str, object] = {}

    def fake_run_compose(args: list[str], extra_env: dict[str, str] | None = None) -> None:
        invoked.update(args=args, extra_env=extra_env)

    monkeypatch.setattr(_docker, "game_image_present", lambda: False)
    monkeypatch.setattr(_docker, "_run_compose", fake_run_compose)

    _docker.ensure_game_image("iagreetotheeula")

    assert invoked["args"] == ["--profile", "game", "build", "game"]
    assert invoked["extra_env"] == {"SC2_LICENSE": "iagreetotheeula"}


def test_run_game_appends_command_override(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked: dict[str, list[str]] = {}

    def fake_invoke(args: list[str], extra_env: dict[str, str] | None = None) -> int:
        invoked["args"] = args
        return 0

    monkeypatch.setattr(_docker, "_invoke_compose", fake_invoke)

    _docker.run_game(["--difficulty", "VeryHard", "--seed", "7"])

    assert invoked["args"] == [
        "--profile",
        "game",
        "run",
        "--rm",
        "game",
        "hima",
        "run",
        "--difficulty",
        "VeryHard",
        "--seed",
        "7",
    ]


def test_run_game_empty_args_keeps_compose_command(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked: dict[str, list[str]] = {}

    def fake_invoke(args: list[str], extra_env: dict[str, str] | None = None) -> int:
        invoked["args"] = args
        return 0

    monkeypatch.setattr(_docker, "_invoke_compose", fake_invoke)

    _docker.run_game([])

    assert invoked["args"] == ["--profile", "game", "run", "--rm", "game"]


def test_run_game_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_docker, "_invoke_compose", lambda args, extra_env=None: 3)

    with pytest.raises(CommandError, match="headless game exited with code 3"):
        _docker.run_game([])
