"""Unit tests for hima_dht_cli.cli argument defaults.

Defaults resolve as CLI flag > exported environment > .env > code
default; `.env` loading happens in `main()`, so `_build_parser` sees
only the process environment.

Test cases:
- test_up_defaults_read_environment: `hima up` takes port, webui port,
  and model defaults from HIMA_* variables.
- test_flag_overrides_environment: an explicit --port beats
  HIMA_ADVISOR_PORT.
- test_run_defaults_read_environment: `hima run` takes advisor host and
  leader base URL defaults from HIMA_* variables.
- test_serve_defaults_read_environment: `hima serve` takes its bind host
  default from HIMA_WEBUI_HOST.
- test_invalid_port_environment_raises_command_error: a non-integer
  HIMA_ADVISOR_PORT raises CommandError instead of a traceback.
- test_serve_bound_port_raises_command_error: serving on a bound port
  raises CommandError instead of exiting the process.
"""
import socket

import pytest

from hima_dht_cli import cli
from hima_dht_cli.errors import CommandError


def test_up_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "9001")
    monkeypatch.setenv("HIMA_WEBUI_PORT", "9123")
    monkeypatch.setenv("HIMA_LEADER_MODEL", "qwen3:32b")

    args = cli._build_parser().parse_args(["up"])

    assert (args.port, args.webui_port, args.model) == (9001, 9123, "qwen3:32b")


def test_flag_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "9001")

    args = cli._build_parser().parse_args(["up", "--port", "7000"])

    assert args.port == 7000


def test_run_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_HOST", "advisor")
    monkeypatch.setenv("HIMA_LEADER_BASE_URL", "http://ollama:11434/v1")

    args = cli._build_parser().parse_args(["run"])

    assert (args.advisor_host, args.base_url) == ("advisor", "http://ollama:11434/v1")


def test_serve_defaults_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_WEBUI_HOST", "0.0.0.0")

    args = cli._build_parser().parse_args(["serve"])

    assert args.host == "0.0.0.0"


def test_invalid_port_environment_raises_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIMA_ADVISOR_PORT", "eight")

    with pytest.raises(CommandError, match="HIMA_ADVISOR_PORT"):
        cli._build_parser()


def test_serve_bound_port_raises_command_error() -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        with pytest.raises(CommandError):
            cli._serve("127.0.0.1", port)
