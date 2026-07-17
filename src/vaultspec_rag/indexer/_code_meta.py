"""Content-hash sidecar and config-epoch logic for the codebase indexer.

Pure helpers for the code index's metadata sidecar: reading it verbatim,
stripping the reserved dunder keys, computing the two-tier config epoch, and
classifying drift. Split out of ``_codebase_indexer`` so the sidecar and
epoch bookkeeping live apart from the GPU chunk/embed pipeline. The atomic
writer stays on ``CodebaseIndexer`` (``_write_meta``); everything read-only
delegates here.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from . import _config_epoch

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Sequence

    from ._preprocess_config import PreprocessRule

logger = logging.getLogger(__name__)

#: Version of the embedding-input format for code chunks. ``2`` embeds
#: a one-line locational header (path, class, function) ahead of the
#: chunk text; ``1`` (or an absent marker over a non-empty collection)
#: embedded the bare chunk text. A mismatch triggers a one-time clean
#: rebuild so the two regimes never mix in one collection.
CODE_EMBED_SCHEMA = "2"

#: Reserved key carrying the format version inside the hash-metadata
#: sidecar. Never collides with relative file paths.
EMBED_SCHEMA_KEY = "__code_embed_schema__"

#: Reserved sidecar keys carrying the two-tier config epoch. Both begin
#: with ``__`` so ``load_meta`` strips them from file-path set arithmetic.
#: The membership epoch tracks which files are indexed (ignore + preprocess
#: patterns); the content epoch tracks how their bytes become chunks
#: (preprocess invocation fields and ``html_strip``).
MEMBERSHIP_EPOCH_KEY = "__code_membership_epoch__"
CONTENT_EPOCH_KEY = "__code_content_epoch__"


def compute_code_epochs(
    *,
    gitignore_patterns: list[str],
    vaultragignore_patterns: list[str],
    preprocess_rules: Sequence[PreprocessRule],
) -> tuple[str, str]:
    """Compute the (membership, content) epoch pair from resolved inputs."""
    from ..config import get_config

    cfg = get_config()
    membership = _config_epoch.code_membership_epoch(
        gitignore_patterns=gitignore_patterns,
        vaultragignore_patterns=vaultragignore_patterns,
        preprocess_rules=preprocess_rules,
    )
    content = _config_epoch.code_content_epoch(
        preprocess_rules=preprocess_rules,
        html_strip=bool(cfg.html_strip),
        max_emitted_bytes=int(cfg.preprocess_max_emitted_bytes),
    )
    return membership, content


def classify_config_drift(
    raw: dict[str, str],
    membership: str,
    content: str,
) -> str:
    """Classify config drift against the stored epochs.

    Returns ``"clean"`` (content drift - clean rebuild), ``"unscoped"``
    (membership drift or a legacy sidecar missing the keys - force the
    unscoped incremental), or ``"ok"`` (no drift, or a fresh index with no
    sidecar to compare against). Content drift outranks membership drift
    because the clean rebuild subsumes the membership reconcile.
    """
    if not raw:
        return "ok"
    stored_membership = raw.get(MEMBERSHIP_EPOCH_KEY)
    stored_content = raw.get(CONTENT_EPOCH_KEY)
    if stored_membership is None or stored_content is None:
        return "unscoped"
    if stored_content != content:
        return "clean"
    if stored_membership != membership:
        return "unscoped"
    return "ok"


def needs_embed_rebuild(raw: dict[str, str], count_code: Callable[[], int]) -> bool:
    """Return True when stored vectors predate the embed-input format.

    Chunk vectors embed a locational header alongside the chunk
    text; older stores embedded the bare chunk text. Mixing the two
    regimes (and querying them with the current instruction prompt)
    silently degrades retrieval, so a marker mismatch triggers a
    one-time clean rebuild. A missing sidecar over a non-empty
    collection is treated the same way.
    """
    if raw:
        return raw.get(EMBED_SCHEMA_KEY) != CODE_EMBED_SCHEMA
    try:
        return count_code() > 0
    except (OSError, RuntimeError):
        logger.warning(
            "Could not probe the code collection for an embed "
            "rebuild decision; assuming no rebuild is needed",
            exc_info=True,
        )
        return False


def read_meta_raw(meta_path: pathlib.Path) -> dict[str, str]:
    """Load the sidecar JSON verbatim, reserved keys included."""
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (KeyError, ValueError, OSError) as exc:
        logger.debug(
            "codebase meta %s unreadable; treating as empty: %s",
            meta_path,
            exc,
            exc_info=True,
        )
        return {}


def load_meta(meta_path: pathlib.Path) -> dict[str, str]:
    """Load codebase index metadata from the sidecar JSON file.

    Reserved dunder keys (the embed-format marker) are stripped so
    they can never participate in file-path set arithmetic - the
    marker would otherwise be counted as a deleted file on every
    incremental run.

    Returns:
        Mapping of relative file path to blake2b hex digest, or
        an empty dict if the file does not exist or cannot be
        parsed.
    """
    return {
        key: value
        for key, value in read_meta_raw(meta_path).items()
        if not key.startswith("__")
    }
