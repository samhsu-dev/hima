"""Unit tests for hima_dht_cli.services._manifest (service start manifest).

Test cases:
- test_native_manifest_round_trips: a native manifest written to TOML
  reads back equal, entry types included.
- test_docker_manifest_round_trips: a docker manifest written to TOML
  reads back equal, entry types included.
- test_read_manifest_missing_returns_none: no manifest file distinguishes
  "never recorded" from a corrupt record.
- test_read_manifest_corrupt_raises: a file that does not parse as a
  manifest raises CommandError naming the path.
- test_read_manifest_version_mismatch_raises: a manifest recording a
  different version raises CommandError naming both versions.
- test_write_manifest_leaves_no_scratch_file: the atomic write leaves no
  .tmp sibling next to the manifest.
"""

from pathlib import Path

import pytest

from hima_dht_cli.errors import CommandError
from hima_dht_cli.services import (
    DockerService,
    ModelEndpoint,
    NativeService,
    ServiceBackend,
    ServiceManifest,
    read_manifest,
)
from hima_dht_cli.services._manifest import write_manifest


def test_native_manifest_round_trips(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        backend=ServiceBackend.NATIVE,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "ollama": NativeService(
                endpoint="http://localhost:11434",
                pid=4321,
                pid_file="tmp/services/ollama.pid",
                log_file="tmp/services/ollama.log",
            )
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert read_manifest(path) == manifest


def test_docker_manifest_round_trips(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        backend=ServiceBackend.DOCKER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "advisor": DockerService(endpoint="http://localhost:8090", container="hima-advisor-1")
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert read_manifest(path) == manifest


def test_read_manifest_missing_returns_none(tmp_path: Path) -> None:
    assert read_manifest(tmp_path / "manifest.toml") is None


def test_read_manifest_corrupt_raises(tmp_path: Path) -> None:
    path = tmp_path / "manifest.toml"
    path.write_text('version = 2\nbackend = "hybrid"\n', encoding="utf-8")

    with pytest.raises(CommandError, match="corrupt service manifest"):
        read_manifest(path)


def test_read_manifest_version_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "manifest.toml"
    path.write_text('version = 99\nbackend = "native"\n', encoding="utf-8")

    with pytest.raises(CommandError, match="records version 99.*reads.*version 2"):
        read_manifest(path)


def test_write_manifest_leaves_no_scratch_file(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        backend=ServiceBackend.DOCKER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "advisor": DockerService(endpoint="http://localhost:8090", container="hima-advisor-1")
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert list(tmp_path.iterdir()) == [path]
