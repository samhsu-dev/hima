"""Unit tests for hima_dht_cli.experiment (game invocation).

Test cases:
- test_invoke_game_forwards_advisor_host: the advisor host in RunOptions
  reaches main.py as --advisor_host.
- test_invoke_game_defaults_to_localhost_advisor: the default advisor host
  stays localhost, keeping the host-native run unchanged.
- test_invoke_game_forwards_api_key: the API key in RunOptions reaches
  main.py as --LLM_api_key.
- test_require_services_checks_advisor_at_host: the precheck polls the
  advisor at the configured host, not localhost.
- test_require_services_queries_leader_endpoint: the precheck queries the
  configured base URL with the configured API key.
- test_require_services_rejects_unreachable_leader: an unreachable leader
  endpoint raises CommandError naming the base URL.
- test_require_services_rejects_missing_model: a served list without the
  leader model raises CommandError naming the model.
- test_model_served_matches_exact_and_tag: the model check accepts exact
  ids and Ollama tag-suffixed ids, nothing else.
- test_run_logs_start_and_summary_on_success: run() emits the start
  record and a summary record carrying the archived run directory.
- test_run_logs_summary_on_failure: a failed run still emits a summary
  record carrying the error, then re-raises.
- test_invoke_game_logs_exit_record: the game subprocess exit record
  carries the exit code even when the run fails.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from hima_dht_cli import experiment
from hima_dht_cli.errors import CommandError
from hima_dht_cli.experiment import RunOptions
from hima_dht_cli.services import DEFAULT_ADVISOR_HOST


def make_options(advisor_host: str) -> RunOptions:
    return RunOptions(
        difficulty="Hard",
        enemy_race="Zerg",
        seed=3,
        port=8090,
        advisor_host=advisor_host,
        model="qwen3:8b",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        realtime=False,
    )


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


def test_invoke_game_defaults_to_localhost_advisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = invoke_argv(monkeypatch, make_options(DEFAULT_ADVISOR_HOST))

    assert argv[argv.index("--advisor_host") + 1] == "localhost"


def test_invoke_game_forwards_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = invoke_argv(monkeypatch, make_options(DEFAULT_ADVISOR_HOST))

    assert argv[argv.index("--LLM_api_key") + 1] == "ollama"


def test_require_services_checks_advisor_at_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polled: dict = {}

    def fake_advisor_healthy(host: str, port: int) -> bool:
        polled["endpoint"] = (host, port)
        return True

    monkeypatch.setattr(experiment.services, "advisor_healthy", fake_advisor_healthy)
    monkeypatch.setattr(
        experiment.services, "leader_models", lambda base_url, api_key: ["qwen3:8b"]
    )
    experiment._require_services(make_options("advisor"))

    assert polled["endpoint"] == ("advisor", 8090)


def test_require_services_queries_leader_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried: dict = {}

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        queried["endpoint"] = (base_url, api_key)
        return ["qwen3:8b"]

    monkeypatch.setattr(experiment.services, "advisor_healthy", lambda host, port: True)
    monkeypatch.setattr(experiment.services, "leader_models", fake_leader_models)
    experiment._require_services(make_options(DEFAULT_ADVISOR_HOST))

    assert queried["endpoint"] == ("http://localhost:11434/v1", "ollama")


def test_require_services_rejects_unreachable_leader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment.services, "advisor_healthy", lambda host, port: True)
    monkeypatch.setattr(experiment.services, "leader_models", lambda base_url, api_key: None)

    with pytest.raises(CommandError, match="http://localhost:11434/v1"):
        experiment._require_services(make_options(DEFAULT_ADVISOR_HOST))


def test_require_services_rejects_missing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment.services, "advisor_healthy", lambda host, port: True)
    monkeypatch.setattr(
        experiment.services, "leader_models", lambda base_url, api_key: ["llama3:8b"]
    )

    with pytest.raises(CommandError, match="qwen3:8b"):
        experiment._require_services(make_options(DEFAULT_ADVISOR_HOST))


@pytest.mark.parametrize(
    "served,match",
    [
        (["qwen3:8b"], True),  # exact id
        (["qwen3:8b:q4"], True),  # Ollama tag suffix on the requested id
        (["qwen3"], False),  # bare family is not the requested tag
        (["llama3:8b"], False),  # different model
        ([], False),  # empty served list
    ],
)
def test_model_served_matches_exact_and_tag(served: list[str], match: bool) -> None:
    assert experiment._model_served("qwen3:8b", served) is match


def test_run_logs_start_and_summary_on_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(experiment, "_play_and_archive", lambda options: tmp_path / "run")
    monkeypatch.setattr(experiment, "_print_metric", lambda run_dir: None)

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.experiment"):
        experiment.run(make_options(DEFAULT_ADVISOR_HOST))

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("run starting: difficulty=Hard") for message in messages)
    assert any(
        message.startswith(f"run archived: run_dir={tmp_path / 'run'}") for message in messages
    )


def test_run_logs_summary_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(options: RunOptions) -> Path:
        raise CommandError("boom")

    monkeypatch.setattr(experiment, "_play_and_archive", fail)

    with (
        caplog.at_level(logging.INFO, logger="hima_dht_cli.experiment"),
        pytest.raises(CommandError, match="boom"),
    ):
        experiment.run(make_options(DEFAULT_ADVISOR_HOST))

    failures = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.getMessage().startswith("run failed:")
    ]
    assert len(failures) == 1 and "boom" in failures[0].getMessage()


def test_invoke_game_logs_exit_record(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        experiment.subprocess, "run", lambda argv, cwd: SimpleNamespace(returncode=3)
    )

    with (
        caplog.at_level(logging.INFO, logger="hima_dht_cli.experiment"),
        pytest.raises(CommandError, match="code 3"),
    ):
        experiment._invoke_game(make_options(DEFAULT_ADVISOR_HOST))

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("game subprocess exited: exit_code=3") for message in messages)
