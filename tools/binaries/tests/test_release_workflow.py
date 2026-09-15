"""Guards for the public binary-release workflow boundary."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _workflow(repo_root: Path) -> str:
    """Read the workflow whose release edge these assertions protect."""
    return (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )


def _assert_immutable_action_pins(text: str) -> None:
    """Assert every action reference in *text* names a full commit SHA."""
    uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", text, re.M)
    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in uses), uses


@pytest.mark.parametrize("workflow", ["binaries.yml", "publish.yml"])
def test_artifact_workflows_are_release_only(repo_root: Path, workflow: str) -> None:
    """Artifact production exposes only its intentional release entrypoints."""
    path = repo_root / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))

    expected = {"workflow_dispatch"}
    if workflow == "publish.yml":
        expected.add("push")
        assert triggers["push"] == {"tags": ["vaultspec-rag-v*"]}
    assert set(triggers) == expected
    assert "tag" in triggers["workflow_dispatch"]["inputs"]


def test_binary_release_actions_are_immutably_pinned(repo_root: Path) -> None:
    """Privileged release actions resolve only reviewed immutable commits."""
    _assert_immutable_action_pins(_workflow(repo_root))


def test_binary_release_action_pin_guard_rejects_a_mutable_tag() -> None:
    """Mutation proof: a release action tag cannot satisfy the pin guard."""
    with pytest.raises(AssertionError, match="v7"):
        _assert_immutable_action_pins("    uses: astral-sh/setup-uv@v7\n")


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
    assert 'expected_names+=("${expected_name}")' in release_gate
    assert "raw=()" in release_gate
    assert "unexpected=()" in release_gate
    assert "exit 1" in release_gate

    assert 'expected_name="${TAG}-${triple}${suffix}"' in verify_gate
    assert "bundle_archives=()" in verify_gate
    assert "raw=()" in verify_gate
    assert "RELEASE_RESULT" in verify_gate
    assert 'wheel="vaultspec_rag-${version}-py3-none-any.whl"' in verify_gate
    assert 'sdist="vaultspec_rag-${version}.tar.gz"' in verify_gate
    assert "sha256sum -c SHA256SUMS" in verify_gate
    assert "https://pypi.org/pypi/vaultspec-rag/${version}/json" in verify_gate
    assert "vaultspec-rag-*|vaultspec-search-mcp-*)" in verify_gate
    assert verify < promote
    assert "if: ${{ success() }}" in text[promote:]


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


def test_release_please_holds_then_publish_dispatches_binaries(
    repo_root: Path,
) -> None:
    """Release Please holds stable/latest and starts the sequenced publisher.

    Mutation proof: removing the prerelease hold made this assertion fail on
    the named release-state guard; the hold was restored before the passing
    run.
    """
    text = (repo_root / ".github" / "workflows" / "release-please.yml").read_text(
        encoding="utf-8"
    )
    hold = text.index(
        "- name: Hold the release out of latest until artifacts are complete"
    )
    publish = text.index("- name: Trigger Publish workflow")
    hold_section = text[hold:publish]
    publish_section = text[publish:]

    assert "--prerelease" in hold_section
    assert "steps.release.outputs.tag_name" in hold_section
    assert "steps.release.outputs.release_created == 'true'" in publish_section
    assert "TAG: ${{ steps.release.outputs.tag_name }}" in publish_section
    assert "--ref main" in publish_section
    assert '--field tag="${TAG}"' in publish_section
    assert "Trigger Binaries workflow" not in text

    downstream = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    hold = downstream.index("- name: Hold the release as a prerelease")
    dispatch = downstream.index("- name: Trigger Binaries workflow")
    dispatch_section = downstream[dispatch:]
    assert "needs: hold-release" in downstream
    assert "--prerelease" in downstream[hold:dispatch]
    assert "needs: [publish-pypi, github-release]" in downstream
    assert "gh workflow run Binaries \\" in dispatch_section
    assert '--field tag="${TAG}"' in dispatch_section
