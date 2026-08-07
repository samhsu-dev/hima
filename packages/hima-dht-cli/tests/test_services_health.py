"""Unit tests for hima_dht_cli.services._health (HTTP health probes).

Test cases:
- test_leader_models_lists_openai_endpoint: the endpoint check GETs
  {base_url}/models with the bearer key and returns the served ids.
- test_leader_models_none_when_unreachable: a request failure yields None,
  distinct from an empty served list.
"""

import pytest
import requests

from hima_dht_cli import services


def test_leader_models_lists_openai_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "llama3:8b"}]}

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        requested["url"] = url
        requested["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("hima_dht_cli.services._health.requests.get", fake_get)

    served = services.leader_models("http://localhost:11434/v1", "secret")

    assert served == ["qwen3:8b", "llama3:8b"]
    assert requested["url"] == "http://localhost:11434/v1/models"
    assert requested["headers"] == {"Authorization": "Bearer secret"}


def test_leader_models_none_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, headers: dict[str, str], timeout: int) -> None:
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("hima_dht_cli.services._health.requests.get", fake_get)

    assert services.leader_models("http://localhost:11434/v1", "ollama") is None
