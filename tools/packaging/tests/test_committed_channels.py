"""Guards on how the release job produces channel pointers.

The channel root is the account distribution repository, not this checkout.
These assertions therefore protect the release wiring and the local recipe
that writes the files users install, rather than looking for stale copies in
the product repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.repo, pytest.mark.unit]


def _workflow(repo_root: Path) -> str:
    """Read the workflow whose release edge these assertions protect."""
    return (repo_root / ".github" / "workflows" / "channels.yml").read_text(
        encoding="utf-8"
    )


def test_release_workflow_generates_archive_based_channels(repo_root: Path) -> None:
    """The release edge consumes bundle checksums through the shared recipe.

    Mutation proof: changing the recipe's checksum input back to
    ``dist-bin/SHA256SUMS`` made the exact archive-input assertion fail; the
    published path was restored before the passing run.
    """
    workflow = _workflow(repo_root)
    start = workflow.index("- name: Generate and validate the release channel pointers")
    commit = workflow.index("- name: Commit the Scoop manifest and Homebrew formula")
    generation = workflow[start:commit]
    justfile = (repo_root / "justfile").read_text(encoding="utf-8")

    assert 'run: just release-channels "$TAG" channels published/SHA256SUMS' in (
        generation
    )
    assert "dist-bin/SHA256SUMS" not in generation
    assert "dist-bundles/SHA256SUMS" not in generation
    refuse = workflow.index("- name: Refuse to point at an unpublished release")
    download = workflow.index("- name: Download the published checksums")
    assert refuse < download < start < commit
    assert "--json isDraft --jq '.isDraft'" in workflow[refuse:download]
    assert "exit 1" in workflow[refuse:download]
    assert "--pattern SHA256SUMS --dir published" in workflow[download:start]
    assert "[ ! -s published/SHA256SUMS ]" in workflow[download:start]
    generate = justfile.index("python -m tools.packaging.generate")
    validate = justfile.index("python -m tools.packaging.validate")
    assert generate < validate
    assert "release-channels tag root checksums='dist-bundles/SHA256SUMS':" in justfile


def test_release_workflow_commits_the_generated_channel_root(repo_root: Path) -> None:
    """The release job stages only the generated RAG channel pointers.

    Mutation proof: removing the formula path from the explicit ``git add``
    made the exact staging assertion fail; the path was restored before the
    passing run.
    """
    workflow = _workflow(repo_root)
    start = workflow.index("- name: Commit the Scoop manifest and Homebrew formula")
    body = workflow[start:]

    assert "cd channels" in body
    assert "git add -- bucket/vaultspec-rag.json Formula/vaultspec-rag.rb" in body
    assert "git diff --cached --quiet -- bucket Formula" in body
    assert "git push origin main" in body


def test_channels_require_a_published_release_and_isolate_the_deploy_key(
    repo_root: Path,
) -> None:
    """The channel key advertises only public assets without an OIDC grant.

    Mutation proof: changing the draft refusal to false failed the release-state
    assertion; adding ``id-token: write`` to the job failed the permission
    assertion. Each passed immediately after restoration.
    """
    workflow = _workflow(repo_root)
    document = yaml.safe_load(workflow)
    assert set(document.get("on", document.get(True))) == {"workflow_dispatch"}
    assert "id-token" not in document["permissions"]
    job = document["jobs"]["channels"]
    assert "id-token" not in job["permissions"]
    steps = job["steps"]
    refusal = next(
        i for i, step in enumerate(steps) if "--json isDraft" in step.get("run", "")
    )
    download = next(
        i
        for i, step in enumerate(steps)
        if "--pattern SHA256SUMS --dir published" in step.get("run", "")
    )
    generate = next(
        i
        for i, step in enumerate(steps)
        if "just release-channels" in step.get("run", "")
    )
    assert refusal < download < generate
    assert '= "true" ]; then' in steps[refusal]["run"]
    assert "exit 1" in steps[refusal]["run"]
    assert "[ ! -s published/SHA256SUMS ]" in steps[download]["run"]
    assert "exit 1" in steps[download]["run"]
    assert any(
        step.get("with", {}).get("ssh-key")
        == ("${{ secrets.CHANNEL_ROOT_DEPLOY_KEY }}")
        and step["with"]["repository"]
        == ("${{ github.repository_owner }}/homebrew-tap")
        for step in steps
    )


def test_this_repository_carries_no_second_channel_root(repo_root: Path) -> None:
    """Channel pointers have one account-owned home, not stale local copies.

    Mutation proof: creating a temporary ``bucket`` directory made the exact
    root assertion fail; that directory was removed before the passing run.
    """
    for stale in ("bucket", "Formula"):
        assert not (repo_root / stale).exists(), (
            f"{stale}/ is back; channel pointers belong in the account tap"
        )
