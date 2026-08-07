"""Unit tests for hima_dht_game.app (create_app over fake advisors).

Test cases:
- test_health_lists_model_ids: /health reports ok and sorted advisor ids.
- test_infer_aggregates_suggestions: /infer joins the trio's texts as
  Suggestion A/B/C lines.
- test_infer_single_returns_model_text: /infer/{model_id} returns that
  advisor's text.
- test_infer_unknown_model_returns_404: unknown model id maps to 404.
- test_model_trio_defaults_to_published_checkpoints: no env -> SNUMPR trio.
- test_model_trio_reads_environment: HIMA_ADVISOR_MODELS overrides the trio.
- test_model_trio_ignores_blank_environment: blank env value -> default trio.
"""
import pytest
from fastapi.testclient import TestClient

from hima_dht_game.app import ENV_ADVISOR_MODELS, MODEL_TRIO, Query, create_app, model_trio


class FakeAdvisor:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, query: Query) -> str:
        return self.text


def make_client() -> TestClient:
    advisors = {"0": FakeAdvisor("alpha"), "1": FakeAdvisor("beta"), "2": FakeAdvisor("gamma")}
    return TestClient(create_app(advisors))


def test_health_lists_model_ids() -> None:
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "models": ["0", "1", "2"]}


def test_infer_aggregates_suggestions() -> None:
    response = make_client().post("/infer", json={"prompt": "hi"})

    assert response.json() == {
        "text": "Suggestion A: 'alpha',\nSuggestion B: 'beta',\nSuggestion C: 'gamma',\n"
    }


def test_infer_single_returns_model_text() -> None:
    response = make_client().post("/infer/1", json={"prompt": "hi"})

    assert response.json() == {"model": "1", "text": "beta"}


def test_infer_unknown_model_returns_404() -> None:
    response = make_client().post("/infer/9", json={"prompt": "hi"})

    assert response.status_code == 404


def test_model_trio_defaults_to_published_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_ADVISOR_MODELS, raising=False)

    assert model_trio() == MODEL_TRIO


def test_model_trio_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ADVISOR_MODELS, "org/tank-a, org/tank-b ,org/tank-c")

    assert model_trio() == ("org/tank-a", "org/tank-b", "org/tank-c")


def test_model_trio_ignores_blank_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ADVISOR_MODELS, " , ")

    assert model_trio() == MODEL_TRIO
