"""Unit tests for hima_dht_game.advisor (create_app over fake advisors).

Test cases:
- test_health_lists_model_ids: /health reports ok and sorted advisor ids.
- test_infer_aggregates_suggestions: /infer joins the trio's texts as
  Suggestion A/B/C lines.
- test_infer_single_returns_model_text: /infer/{model_id} returns that
  advisor's text.
- test_infer_unknown_model_returns_404: unknown model id maps to 404.
"""
from fastapi.testclient import TestClient

from hima_dht_game.advisor import Query, create_app


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
