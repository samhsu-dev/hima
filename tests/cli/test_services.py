"""Unit tests for cli.services (managed background services).

Test cases:
- test_ensure_leader_model_queries_local_ollama_root: the leader-model
  presence check runs against the local Ollama root that `hima start`
  manages.
"""
import pytest

from cli import services


def test_ensure_leader_model_queries_local_ollama_root(monkeypatch: pytest.MonkeyPatch) -> None:
    queried: dict = {}

    def fake_leader_model_present(root: str, model: str) -> bool:
        queried["endpoint"] = (root, model)
        return True

    monkeypatch.setattr(services, "leader_model_present", fake_leader_model_present)
    services._ensure_leader_model("qwen3:8b", skip_pull=True)

    assert queried["endpoint"] == (services.OLLAMA_URL, "qwen3:8b")
