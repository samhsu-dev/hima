"""Unit tests for the hima_dht_cli.cli typer command surface.

Defaults resolve as CLI flag > exported environment > .env > code
default; `.env` loading happens in `main()`, so `app` sees only the
process environment.

Test cases:
- test_up_defaults_read_environment: `hima up` takes port, webui port,
  and model defaults from HIMA_* variables.
- test_up_service_placement_reads_environment: `hima up` takes its
  service placement default from HIMA_SERVICES.
- test_up_webui_reads_environment: the webui is off by default and opt-in
  through HIMA_WEBUI, independent of the service placement.
- test_up_leader_endpoint_reads_environment: `hima up` takes the leader
  base URL and API key defaults from HIMA_LEADER_* variables.
- test_flag_overrides_environment: an explicit --port beats
  HIMA_ADVISOR_PORT.
- test_run_defaults_read_environment: `hima run --game host` takes
  advisor host and leader base URL defaults from HIMA_* variables.
- test_run_game_placement_reads_environment: the game runs in a container
  by default and on the host through HIMA_GAME, at either placement of
  the services.
- test_run_ui_reads_environment: the observation surface comes from
  HIMA_UI and reaches both game placements.
- test_run_container_forwards_only_explicit_flags: a container game
  forwards command-line game flags into the override while
  environment-sourced values stay out of it.
- test_run_container_rejects_host_flags: a host-topology flag combined
  with a container game raises CommandError naming the HIMA_* key.
- test_run_container_reads_sc2_license_environment: a container game
  takes the license default from SC2_LICENSE.
- test_serve_defaults_read_environment: `hima serve` takes its bind host
  default from HIMA_WEBUI_HOST.
- test_invalid_port_environment_exits_usage_error: a non-integer
  HIMA_ADVISOR_PORT exits 2 with a usage error naming the variable.
- test_command_error_prints_message_and_exits_one: a CommandError from a
  command prints `hima: <message>` to stderr and main() returns 1.
- test_status_failing_check_exits_one: `hima status` exits 1 when any
  check fails.
- test_serve_bound_port_raises_command_error: serving on a bound port
  raises CommandError instead of exiting the process.
"""

import socket
import sys

import pytest
from typer.testing import CliRunner

from hima_dht_cli import cli, experiment, services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.placement import Placement

runner = CliRunner()


def test_up_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "9001")
    monkeypatch.setenv("HIMA_WEBUI_PORT", "9123")
    monkeypatch.setenv("HIMA_LEADER_MODEL", "qwen3:32b")
    captured: dict[str, services.ServiceOptions] = {}
    monkeypatch.setattr(
        services, "up", lambda options, manifest_out: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["up"])

    assert result.exit_code == 0
    assert captured["options"] == services.ServiceOptions(
        advisor_port=9001, webui_port=9123, model="qwen3:32b"
    )


def test_up_service_placement_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_SERVICES", "container")
    captured: dict[str, services.ServiceOptions] = {}
    monkeypatch.setattr(
        services, "up", lambda options, manifest_out: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["up"])

    assert result.exit_code == 0
    assert captured["options"].placement is Placement.CONTAINER


@pytest.mark.parametrize(
    "environment,webui",
    [
        ({}, False),  # the webui exists only when asked for
        ({"HIMA_WEBUI": "true"}, True),
    ],
)
def test_up_webui_reads_environment(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], webui: bool
) -> None:
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    captured: dict[str, services.ServiceOptions] = {}
    monkeypatch.setattr(
        services, "up", lambda options, manifest_out: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["up"])

    assert result.exit_code == 0
    assert captured["options"].webui is webui


def test_up_leader_endpoint_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_LEADER_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("HIMA_LEADER_API_KEY", "secret")
    captured: dict[str, services.ServiceOptions] = {}
    monkeypatch.setattr(
        services, "up", lambda options, manifest_out: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["up"])

    assert result.exit_code == 0
    assert (captured["options"].leader_base_url, captured["options"].leader_api_key) == (
        "https://api.example.com/v1",
        "secret",
    )


def test_flag_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "9001")
    captured: dict[str, services.ServiceOptions] = {}
    monkeypatch.setattr(
        services, "up", lambda options, manifest_out: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["up", "--port", "7000"])

    assert result.exit_code == 0
    assert captured["options"].advisor_port == 7000


def test_run_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_HOST", "advisor")
    monkeypatch.setenv("HIMA_LEADER_BASE_URL", "http://ollama:11434/v1")
    captured: dict[str, experiment.RunOptions] = {}
    monkeypatch.setattr(experiment, "run_host", lambda options: captured.update(options=options))

    result = runner.invoke(cli.app, ["run", "--game", "host"])

    assert result.exit_code == 0
    assert (captured["options"].advisor_host, captured["options"].base_url) == (
        "advisor",
        "http://ollama:11434/v1",
    )


@pytest.mark.parametrize(
    "environment,dispatched",
    [
        ({}, "run_container"),  # the container game is the default
        ({"HIMA_GAME": "host"}, "run_host"),
    ],
)
def test_run_game_placement_reads_environment(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], dispatched: str
) -> None:
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    called: list[str] = []
    monkeypatch.setattr(experiment, "run_host", lambda options: called.append("run_host"))
    monkeypatch.setattr(experiment, "run_container", lambda options: called.append("run_container"))

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert called == [dispatched]


@pytest.mark.parametrize("game", ["host", "container"])
def test_run_ui_reads_environment(monkeypatch: pytest.MonkeyPatch, game: str) -> None:
    monkeypatch.setenv("HIMA_UI", "web")
    captured: dict[str, experiment.RunOptions | experiment.ContainerRunOptions] = {}
    for command in ("run_host", "run_container"):
        monkeypatch.setattr(experiment, command, lambda options: captured.update(options=options))

    result = runner.invoke(cli.app, ["run", "--game", game])

    assert result.exit_code == 0
    assert captured["options"].observation.ui is experiment.ObservationUI.WEB


def test_run_container_forwards_only_explicit_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_LEADER_MODEL", "qwen3:32b")
    captured: dict[str, experiment.ContainerRunOptions] = {}
    monkeypatch.setattr(
        experiment, "run_container", lambda options: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["run", "--difficulty", "VeryHard", "--seed", "7"])

    assert result.exit_code == 0
    assert captured["options"].game_args == ["--difficulty", "VeryHard", "--seed", "7"]
    assert captured["options"].model == "qwen3:32b"


def test_run_container_rejects_host_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment, "run_container", lambda options: None)

    result = runner.invoke(cli.app, ["run", "--port", "9001"])

    assert isinstance(result.exception, CommandError)
    assert "HIMA_ADVISOR_PORT" in str(result.exception)


def test_run_container_reads_sc2_license_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SC2_LICENSE", "iagreetotheeula")
    captured: dict[str, experiment.ContainerRunOptions] = {}
    monkeypatch.setattr(
        experiment, "run_container", lambda options: captured.update(options=options)
    )

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert captured["options"].sc2_license == "iagreetotheeula"


def test_serve_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_WEBUI_HOST", "0.0.0.0")
    captured: dict[str, str] = {}
    monkeypatch.setattr(cli, "_serve", lambda host, port: captured.update(host=host))

    result = runner.invoke(cli.app, ["serve"])

    assert result.exit_code == 0
    assert captured["host"] == "0.0.0.0"


def test_invalid_port_environment_exits_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "eight")

    result = runner.invoke(cli.app, ["up"])

    assert result.exit_code == 2
    assert "HIMA_ADVISOR_PORT" in result.output + result.stderr


def test_command_error_prints_message_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["hima", "down"])
    monkeypatch.setattr(cli, "load_dotenv", lambda path: False)

    def broken_down() -> None:
        raise CommandError("boom")

    monkeypatch.setattr(services, "down", broken_down)

    assert cli.main() == 1
    assert "hima: boom" in capsys.readouterr().err


def test_status_failing_check_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "status", lambda options, game: False)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 1


def test_serve_bound_port_raises_command_error() -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        with pytest.raises(CommandError):
            cli._serve("127.0.0.1", port)
