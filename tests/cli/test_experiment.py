"""Unit tests for cli.experiment (game invocation).

Test cases:
- test_invoke_game_forwards_advisor_host: the advisor host in RunOptions
  reaches main.py as --advisor_host.
- test_invoke_game_defaults_to_localhost_advisor: the default advisor host
  stays localhost, keeping the host-native run unchanged.
"""
from types import SimpleNamespace

import pytest

from cli import experiment
from cli.experiment import RunOptions
from cli.services import DEFAULT_ADVISOR_HOST


def make_options(advisor_host: str) -> RunOptions:
    return RunOptions(difficulty="Hard", enemy_race="Zerg", seed=3, port=8090,
                      advisor_host=advisor_host, model="qwen3:8b",
                      base_url="http://localhost:11434/v1", realtime=False)


def invoke_argv(monkeypatch: pytest.MonkeyPatch, options: RunOptions) -> list[str]:
    captured: dict = {}

    def fake_run(argv: list[str], cwd) -> SimpleNamespace:
        captured["argv"] = argv
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(experiment.subprocess, "run", fake_run)
    experiment._invoke_game(options)
    return captured["argv"]


def test_invoke_game_forwards_advisor_host(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = invoke_argv(monkeypatch, make_options("advisor"))

    assert argv[argv.index("--advisor_host") + 1] == "advisor"


def test_invoke_game_defaults_to_localhost_advisor(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = invoke_argv(monkeypatch, make_options(DEFAULT_ADVISOR_HOST))

    assert argv[argv.index("--advisor_host") + 1] == "localhost"
