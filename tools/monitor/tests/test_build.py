"""Release provenance requires the committed producer, even for local builds."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

import tools.monitor.build as build

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_release_identity_refuses_dirty_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "package-lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    for args in (
        ["git", "init", "-q"],
        ["git", "add", "package-lock.json"],
        [
            "git",
            "-c",
            "user.name=Build tests",
            "-c",
            "user.email=build@example.invalid",
            "commit",
            "-qm",
            "Seed producer",
        ],
    ):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    committed = build.release_identity("vaultspec-rag-v1.2.3", revision)
    assert committed.development is False
    lock.write_text('{"changed":true}\n', encoding="utf-8")
    # Bypassing the dirty-checkout gate must fail the named admission assertion.
    with pytest.raises(ValueError, match="requires a clean producer checkout"):
        build.release_identity("vaultspec-rag-v1.2.3", revision)
    local = build.release_identity("vaultspec-rag-v1.2.3", revision, development=True)
    assert local.development is True
    assert local.lock_sha256 != committed.lock_sha256
