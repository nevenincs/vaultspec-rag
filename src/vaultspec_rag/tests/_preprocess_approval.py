"""Stand in for the operator who has reviewed and approved a root's hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..indexer._preprocess_approval import approve_policy
from ..indexer._preprocess_config import load_preprocess_rules

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["approve_preprocess_policy"]


def approve_preprocess_policy(root: Path) -> None:
    """Approve *root*'s current policy, as ``preprocess approve`` would.

    A test that expects a hook to run calls this after writing the policy
    file. It goes through the loader and the store the CLI verb uses, into
    whatever status directory the test has configured, so an edit to the
    policy afterwards leaves the root unapproved exactly as it would for an
    operator.
    """
    digest = load_preprocess_rules(root, strict=True).policy_digest
    assert digest is not None, f"{root} has no preprocess policy to approve"
    approve_policy(root, digest, approved_at="2026-01-01T00:00:00+00:00")
