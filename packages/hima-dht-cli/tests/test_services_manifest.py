"""Unit tests for hima_dht_cli.services._manifest (service start manifest).

Test cases:
- test_host_manifest_round_trips: a host manifest written to TOML
  reads back equal, entry types included.
- test_container_manifest_round_trips: a container manifest written to TOML
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
from hima_dht_cli.placement import Placement
from hima_dht_cli.services import (
    ContainerService,
    HostService,
    ModelEndpoint,
    ServiceManifest,
    read_manifest,
)
from hima_dht_cli.services._manifest import write_manifest


def test_host_manifest_round_trips(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        placement=Placement.HOST,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "advisor": HostService(
                endpoint="http://localhost:8090",
                pid=4321,
                pid_file="tmp/services/advisor.pid",
                log_file="tmp/services/advisor.log",
            )
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert read_manifest(path) == manifest


def test_container_manifest_round_trips(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        placement=Placement.CONTAINER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "advisor": ContainerService(
                endpoint="http://localhost:8090", container="hima-advisor-1"
            )
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert read_manifest(path) == manifest


def test_read_manifest_missing_returns_none(tmp_path: Path) -> None:
    assert read_manifest(tmp_path / "manifest.toml") is None


def test_read_manifest_corrupt_raises(tmp_path: Path) -> None:
    path = tmp_path / "manifest.toml"
    path.write_text('version = 3\nplacement = "hybrid"\n', encoding="utf-8")

    with pytest.raises(CommandError, match="corrupt service manifest"):
        read_manifest(path)


def test_read_manifest_version_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "manifest.toml"
    path.write_text('version = 99\nplacement = "host"\n', encoding="utf-8")

    with pytest.raises(CommandError, match="records version 99.*reads.*version 3"):
        read_manifest(path)


def test_write_manifest_leaves_no_scratch_file(tmp_path: Path) -> None:
    manifest = ServiceManifest(
        placement=Placement.CONTAINER,
        created="2026-08-07T12:00:00+09:00",
        endpoints={"leader": ModelEndpoint(url="http://localhost:11434/v1", model="qwen3:8b")},
        services={
            "advisor": ContainerService(
                endpoint="http://localhost:8090", container="hima-advisor-1"
            )
        },
    )
    path = tmp_path / "manifest.toml"

    write_manifest(manifest, path)

    assert list(tmp_path.iterdir()) == [path]
