"""Unit tests for hima_dht_cli.services._docker (compose-delegated services).

Test cases:
- test_docker_leader_model_absent_skip_pull_raises: the docker backend
  with --skip-pull raises when the model is absent.
"""

import pytest

from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import _docker


def test_docker_leader_model_absent_skip_pull_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_docker, "leader_model_present", lambda root, model: False)

    with pytest.raises(CommandError, match="docker compose exec"):
        _docker.ensure_leader_model("qwen3:8b", skip_pull=True, ollama_port=11434)
