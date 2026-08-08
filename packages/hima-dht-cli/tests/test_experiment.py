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
- test_run_container_without_manifest_raises: a container game with no
  recorded services aborts with the `hima up` remediation.
- test_run_container_addresses_the_advisor_by_service_placement: the
  address handed to the game job follows the recorded service placement,
  by compose service name or through the host gateway.
- test_run_container_prechecks_recorded_leader_and_runs_game: the leader
  precheck queries the manifest-recorded endpoint, the image is ensured
  with the license value, and the game job gets the forwarded flags.
- test_run_container_unreachable_recorded_leader_raises: an unreachable
  recorded leader endpoint raises CommandError naming its URL.
- test_open_surface_web_opens_the_page_before_the_run: `--ui web` opens
  the live page in the BEFORE phase.
- test_open_surface_web_without_a_webui_raises: `--ui web` with no server
  answering fails naming `hima up --webui`, never running unwatched.
- test_open_surface_pygui_plays_the_archived_replay_after_the_run:
  `--ui pygui` opens the renderer on the archived replay in the AFTER
  phase, and nothing in the BEFORE phase.
- test_open_surface_none_opens_nothing: the default surface touches
  neither the browser nor the renderer, in either phase.
- test_run_logs_start_and_summary_on_success: run_host() emits the start
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

from hima_dht_cli import experiment, services
from hima_dht_cli.errors import CommandError
from hima_dht_cli.experiment import (
    ContainerRunOptions,
    ObservationOptions,
    ObservationUI,
    RunOptions,
    RunPhase,
)
from hima_dht_cli.placement import Placement
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


def make_container_options(sc2_license: str | None) -> ContainerRunOptions:
    return ContainerRunOptions(
        game_args=["--seed", "7"],
        model="qwen3:8b",
        api_key="ollama",
        sc2_license=sc2_license,
    )


def recorded_manifest(placement: Placement = Placement.CONTAINER) -> services.ServiceManifest:
    return services.ServiceManifest(
        placement=placement,
        created="2026-08-07T12:00:00+09:00",
        endpoints={
            "leader": services.ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")
        },
        services={
            "advisor": services.ContainerService(
                endpoint="http://localhost:8090", container="hima-advisor-1"
            )
        },
    )


def stub_container_run(
    monkeypatch: pytest.MonkeyPatch, manifest: services.ServiceManifest
) -> dict[str, object]:
    """Stub every boundary a container run crosses; return the record."""
    events: dict[str, object] = {}

    def fake_leader_models(base_url: str, api_key: str) -> list[str]:
        events["queried"] = (base_url, api_key)
        return ["qwen3:8b"]

    monkeypatch.setattr(experiment.services, "read_manifest", lambda: manifest)
    monkeypatch.setattr(experiment.services, "service_healthy", lambda name, endpoint: True)
    monkeypatch.setattr(experiment.services, "leader_models", fake_leader_models)
    monkeypatch.setattr(
        experiment.services,
        "ensure_game_image",
        lambda sc2_license: events.update(license=sc2_license),
    )
    monkeypatch.setattr(
        experiment.services,
        "run_game",
        lambda game_args, advisor_host: events.update(
            game_args=game_args, advisor_host=advisor_host
        ),
    )
    return events


def test_run_container_without_manifest_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment.services, "read_manifest", lambda: None)

    with pytest.raises(CommandError, match="run `hima up` first"):
        experiment.run_container(make_container_options(None))


@pytest.mark.parametrize(
    "placement,advisor_host",
    [
        (Placement.CONTAINER, "advisor"),  # same compose network
        (Placement.HOST, "host.docker.internal"),  # host services
    ],
)
def test_run_container_addresses_the_advisor_by_service_placement(
    monkeypatch: pytest.MonkeyPatch, placement: Placement, advisor_host: str
) -> None:
    events = stub_container_run(monkeypatch, recorded_manifest(placement))

    experiment.run_container(make_container_options("iagreetotheeula"))

    assert events["advisor_host"] == advisor_host


def test_run_container_prechecks_recorded_leader_and_runs_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = stub_container_run(monkeypatch, recorded_manifest())

    experiment.run_container(make_container_options("iagreetotheeula"))

    assert events["queried"] == ("http://localhost:11434/v1", "ollama")
    assert events["license"] == "iagreetotheeula"
    assert events["game_args"] == ["--seed", "7"]


def test_run_container_unreachable_recorded_leader_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(experiment.services, "read_manifest", recorded_manifest)
    monkeypatch.setattr(experiment.services, "service_healthy", lambda name, endpoint: True)
    monkeypatch.setattr(experiment.services, "leader_models", lambda base_url, api_key: None)

    with pytest.raises(CommandError, match="http://localhost:11434/v1"):
        experiment.run_container(make_container_options(None))


def test_open_surface_web_opens_the_page_before_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(experiment.services, "service_healthy", lambda name, endpoint: True)
    monkeypatch.setattr(experiment.webbrowser, "open", lambda url: opened.append(url))

    experiment.open_surface(
        ObservationOptions(ui=ObservationUI.WEB, webui_url="http://localhost:8080"),
        RunPhase.BEFORE,
        None,
    )

    assert opened == ["http://localhost:8080"]


def test_open_surface_web_without_a_webui_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment.services, "service_healthy", lambda name, endpoint: False)

    with pytest.raises(CommandError, match="hima up --webui"):
        experiment.open_surface(
            ObservationOptions(ui=ObservationUI.WEB, webui_url="http://localhost:8080"),
            RunPhase.BEFORE,
            None,
        )


def test_open_surface_pygui_plays_the_archived_replay_after_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    played: list[Path] = []
    archived = tmp_path / "game.SC2Replay"
    archived.write_bytes(b"")
    monkeypatch.setattr(experiment.replay, "play", lambda path: played.append(path))
    options = ObservationOptions(ui=ObservationUI.PYGUI)

    experiment.open_surface(options, RunPhase.BEFORE, tmp_path)
    assert played == []  # nothing is archived yet

    experiment.open_surface(options, RunPhase.AFTER, tmp_path)
    assert played == [archived]


@pytest.mark.parametrize("phase", [RunPhase.BEFORE, RunPhase.AFTER])
def test_open_surface_none_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, phase: RunPhase
) -> None:
    monkeypatch.setattr(
        experiment.webbrowser, "open", lambda url: pytest.fail("no browser without --ui web")
    )
    monkeypatch.setattr(
        experiment.replay, "play", lambda path: pytest.fail("no renderer without --ui pygui")
    )

    experiment.open_surface(ObservationOptions(), phase, tmp_path)


def test_run_logs_start_and_summary_on_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(experiment, "_play_and_archive", lambda options: tmp_path / "run")
    monkeypatch.setattr(experiment, "_print_metric", lambda run_dir: None)

    with caplog.at_level(logging.INFO, logger="hima_dht_cli.experiment"):
        experiment.run_host(make_options(DEFAULT_ADVISOR_HOST))

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
        experiment.run_host(make_options(DEFAULT_ADVISOR_HOST))

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
