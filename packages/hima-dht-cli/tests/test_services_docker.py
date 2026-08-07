"""Unit tests for hima_dht_cli.services._docker (compose-delegated services).

Test cases:
- test_docker_leader_model_absent_skip_pull_raises: the docker backend
  with --skip-pull raises when the model is absent.
- test_container_names_parses_json_array: pre-v2.21 compose emits one
  JSON array instead of NDJSON; both parse to the same mapping.
- test_published_ollama_port_parses_binding: `compose port` output like
  0.0.0.0:12345 yields the host port.
- test_published_ollama_port_unparsable_raises: empty or garbled
  `compose port` output raises CommandError quoting it.
"""

import json

import pytest

from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import _docker


def test_docker_leader_model_absent_skip_pull_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_docker, "leader_model_present", lambda root, model: False)

    with pytest.raises(CommandError, match="docker compose exec"):
        _docker.ensure_leader_model("qwen3:8b", skip_pull=True, ollama_port=11434)


def test_container_names_parses_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"Service": "ollama", "Name": "hima-ollama-1"},
        {"Service": "advisor", "Name": "hima-advisor-1"},
        {"Service": "webui", "Name": "hima-webui-1"},
    ]

    def fake_read(args: list[str]) -> str:
        return json.dumps(rows)

    monkeypatch.setattr(_docker, "_read_compose", fake_read)

    assert _docker.container_names() == {
        "ollama": "hima-ollama-1",
        "advisor": "hima-advisor-1",
        "webui": "hima-webui-1",
    }


def test_published_ollama_port_parses_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(args: list[str]) -> str:
        return "0.0.0.0:12345\n"

    monkeypatch.setattr(_docker, "_read_compose", fake_read)

    assert _docker.published_ollama_port() == 12345


def test_published_ollama_port_unparsable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(args: list[str]) -> str:
        return ""

    monkeypatch.setattr(_docker, "_read_compose", fake_read)

    with pytest.raises(CommandError, match="compose port"):
        _docker.published_ollama_port()
