"""Frozen reference vault corpus for the ranking quality gates.

The intent-ranking and testimonial gates score pinned gold authorities against
a copy of the project vault. Scoring against the LIVE ``.vault/`` makes them
drift: every ADR, audit, and research document added after the gold was
calibrated competes for the same queries and eventually outranks the pinned
authority, failing the gate for a corpus-growth reason rather than a genuine
ranking-quality regression. The vault has grown from ~700 to ~1700 documents
since the gold was authored, which is enough for an older authoritative ADR to
fall out of the top results on an orientation query it still legitimately owns.

Materialising the vault at the gold-calibration commit freezes the corpus, so
the curated gold stays valid no matter how much the live vault keeps growing.
The gate then measures ranking quality against a fixed corpus instead of racing
an ever-expanding one.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: The commit that introduced the intent-aware ranking gold query set and the
#: testimonial authorities. The vault tree at this ref is the corpus the gold
#: was calibrated against; pinning to it decouples the gates from vault churn.
#: Re-pin ONLY together with a deliberate gold re-calibration, never to chase a
#: drifted live vault.
FROZEN_VAULT_REF = "c02c12cff9505f5283dc9c37b08696416a791fe8"

#: Wall-clock bound on each git read below. Both are local reads of a pinned
#: ref and measure ~1.5s, so this is headroom rather than a tuned figure; it
#: exists so a wedged git can never park a session fixture indefinitely.
_GIT_READ_TIMEOUT_SECONDS = 120.0


def materialize_frozen_vault(dest_root: Path, *, repo_root: Path) -> Path:
    """Extract ``.vault/`` at :data:`FROZEN_VAULT_REF` under *dest_root*.

    Uses ``git archive`` so only tracked files at the frozen ref are written -
    runtime index ``data/`` and ``*.lock`` files are untracked and therefore
    never included, so no copy-time ignore filter is needed. Returns the path to
    the materialised ``.vault`` directory.
    """
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "archive",
            FROZEN_VAULT_REF,
            "--",
            ".vault",
        ],
        check=True,
        capture_output=True,
        timeout=_GIT_READ_TIMEOUT_SECONDS,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest_root, filter="data")
    return dest_root / ".vault"


def frozen_vault_document_count(*, repo_root: Path) -> int:
    """Count the frozen corpus's Markdown documents without materialising it.

    Mirrors the extraction set (tracked ``*.md`` under ``.vault`` at the frozen
    ref, excluding the runtime ``data/`` subtree) so the harness's
    corpus-count invariant matches the materialised corpus exactly.
    """
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-tree",
            "-r",
            "--name-only",
            FROZEN_VAULT_REF,
            "--",
            ".vault",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_READ_TIMEOUT_SECONDS,
    ).stdout
    return sum(
        1
        for line in listing.splitlines()
        if line.endswith(".md") and "/data/" not in line
    )
