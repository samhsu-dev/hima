"""Unit tests for hima_dht.experiment (game invocation).

Test cases:
- test_invoke_game_forwards_advisor_host: the advisor host in RunOptions
  reaches main.py as --advisor_host.
- test_invoke_game_defaults_to_localhost_advisor: the default advisor host
  stays localhost, keeping the host-native run unchanged.
- test_leader_root_strips_openai_suffix: the /v1 OpenAI-compat suffix is
  removed to reach the Ollama server root.
- test_leader_root_keeps_plain_root: a base URL without the suffix passes
  through unchanged.
- test_require_services_checks_advisor_at_host: the precheck polls the
  advisor at the configured host, not localhost.
"""
from types import SimpleNamespace

import pytest

from hima_dht import experiment
from hima_dht.experiment import RunOptions
from hima_dht.services import DEFAULT_ADVISOR_HOST


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


def test_leader_root_strips_openai_suffix() -> None:
    assert experiment._leader_root("http://ollama:11434/v1") == "http://ollama:11434"


def test_leader_root_keeps_plain_root() -> None:
    assert experiment._leader_root("http://localhost:11434") == "http://localhost:11434"


def test_require_services_checks_advisor_at_host(monkeypatch: pytest.MonkeyPatch) -> None:
    polled: dict = {}

    def fake_advisor_healthy(host: str, port: int) -> bool:
        polled["endpoint"] = (host, port)
        return True

    monkeypatch.setattr(experiment.services, "advisor_healthy", fake_advisor_healthy)
    monkeypatch.setattr(experiment.services, "ollama_healthy", lambda root: True)
    monkeypatch.setattr(experiment.services, "leader_model_present", lambda root, model: True)
    experiment._require_services(make_options("advisor"))

    assert polled["endpoint"] == ("advisor", 8090)
