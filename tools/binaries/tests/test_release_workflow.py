"""Guards for the public binary-release workflow boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _workflow(repo_root: Path) -> str:
    """Read the workflow whose release edge these assertions protect."""
    return (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )


def test_release_workflow_publishes_only_a_complete_archive_set(
    repo_root: Path,
) -> None:
    """Publication and promotion are downstream of the exact target archive gate.

    Mutation proof: removing the ``expected_name`` assertion from the release
    gate made this test fail at the named contract assertion; the guard was
    restored before the passing run.
    """
    text = _workflow(repo_root)
    ready = text.index("- name: Assert every declared target archive ready")
    upload = text.index('run: gh release upload "${TAG}" dist-bundles/* --clobber')
    verify = text.index("- name: Require artifacts on the published release")
    promote = text.index("- name: Promote a repaired release back to latest")

    release_gate = text[ready:upload]
    verify_gate = text[verify:promote]

    assert ready < upload
    assert 'expected_name="${TAG}-${triple}${suffix}"' in release_gate
    assert "expected_names+=(\"${expected_name}\")" in release_gate
    assert "raw=()" in release_gate
    assert "unexpected=()" in release_gate
    assert "exit 1" in release_gate

    assert "expected_name=\"${TAG}-${triple}${suffix}\"" in verify_gate
    assert "bundle_archives=()" in verify_gate
    assert "raw=()" in verify_gate
    assert "RELEASE_RESULT" in verify_gate
    assert "vaultspec-rag-*|vaultspec-search-mcp-*)" in verify_gate
    assert verify < promote
    assert 'if: ${{ success() }}' in text[promote:]


def test_python_and_binary_release_workflows_share_the_checksum_lock(
    repo_root: Path,
) -> None:
    """The two asset publishers serialize their shared checksum update.

    Mutation proof: changing the publish workflow back to its private
    ``publish-*`` concurrency group made the shared-lock assertion fail; the
    common per-tag group was restored before the passing run.
    """
    binaries = _workflow(repo_root)
    publish = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    lock = "group: release-artifacts-${{ inputs.tag || github.ref_name }}"

    assert lock in binaries
    assert lock in publish
    assert "cancel-in-progress: false" in binaries
    assert "cancel-in-progress: false" in publish

    assert "sha256sum ./* > SHA256SUMS" in publish
    assert 'gh release download "${TAG}" --repo "$GITHUB_REPOSITORY"' in publish
    assert "--pattern SHA256SUMS --output inherited.txt" in publish
    assert "cat inherited.txt >> SHA256SUMS" in publish
    assert "LC_ALL=C sort -k2 -o SHA256SUMS SHA256SUMS" in publish
    assert 'gh release upload "${TAG}" dist/*' in publish
    assert '--repo "$GITHUB_REPOSITORY"' in publish
