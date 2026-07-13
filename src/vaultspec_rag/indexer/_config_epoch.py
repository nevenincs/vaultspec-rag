"""Per-root config-epoch hashing for index-drift detection.

The indexers stamp a small set of reserved epoch keys into their meta sidecars
so that index-shaping configuration drift - ignore-file edits, preprocess-rule
edits, chunking-knob flips - becomes a dependable, self-healing reindex signal
even when the underlying file bytes never change. Two epoch classes exist,
because the two drift classes need different escalations:

* the *membership* epoch tracks which files are indexed (resolved ignore
  patterns and preprocess rule patterns); a mismatch is reconciled by the
  unscoped incremental's set arithmetic;
* the *content* epoch tracks how bytes become chunks (preprocess invocation
  fields, ``html_strip``, and ``vault_chunk_chars`` on the vault side); a
  mismatch invalidates stored vectors for unchanged bytes and needs a clean
  rebuild.

This module is stdlib-only (``hashlib`` / ``json``) so it stays importable from
the CPU-only spawn chunk-worker chain without loading torch.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._preprocess_config import PreprocessRule


def _digest(payload: object) -> str:
    """Return the blake2b hex digest of a canonically-serialized payload.

    Canonicalization pins key order (``sort_keys``) and a compact separator set
    so that a semantically-identical payload always yields the same digest. TOML
    option values that JSON cannot represent natively (e.g. datetimes) degrade
    to their string form rather than raising.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.blake2b(canonical.encode("utf-8")).hexdigest()


def _preprocess_patterns(rules: Sequence[PreprocessRule]) -> list[str]:
    """Return the rule patterns in resolved-precedence order."""
    return [rule.pattern for rule in rules]


def code_membership_epoch(
    *,
    gitignore_patterns: Sequence[str],
    vaultragignore_patterns: Sequence[str],
    preprocess_rules: Sequence[PreprocessRule],
) -> str:
    """Hash the inputs that decide which code files are indexed.

    The gitignore patterns are sorted before hashing so a mere change in the
    filesystem traversal order of nested ``.gitignore`` files (which is not
    guaranteed stable across runs) never registers as spurious drift; a genuine
    pattern add or remove still changes the multiset and thus the digest. The
    ``.vaultragignore`` file patterns keep their file order, and CLI
    ``--exclude`` patterns are deliberately excluded upstream so the epoch does
    not thrash between an ephemeral CLI run and the resident service.
    """
    payload = {
        "gitignore": sorted(gitignore_patterns),
        "vaultragignore": list(vaultragignore_patterns),
        "preprocess_patterns": _preprocess_patterns(preprocess_rules),
    }
    return _digest(payload)


def code_content_epoch(
    *,
    preprocess_rules: Sequence[PreprocessRule],
    html_strip: bool,
    max_emitted_bytes: int,
) -> str:
    """Hash the inputs that decide how code bytes become chunks.

    Covers the preprocess invocation surface (command/entry_point, options,
    on_error, resolved timeout, and per-rule order), ``html_strip``, and the
    emitted-text cap - a cap change re-truncates any extraction that exceeds
    it, so it is content-shaping for unchanged bytes. A change here escalates
    to a clean rebuild.
    """
    payload = {
        "html_strip": bool(html_strip),
        "max_emitted_bytes": int(max_emitted_bytes),
        "preprocess": [
            {
                "command": rule.command,
                "entry_point": rule.entry_point,
                "on_error": rule.on_error,
                "timeout_s": rule.timeout_s,
                "options": dict(rule.options),
                "order": rule.order,
            }
            for rule in preprocess_rules
        ],
    }
    return _digest(payload)


def vault_content_epoch(*, vault_chunk_chars: int) -> str:
    """Hash the one content-shaping knob for the vault index.

    ``vault_chunk_chars`` sets the chunk boundary; changing it re-chunks every
    document with unchanged bytes, so a mismatch escalates to a clean rebuild.
    """
    return _digest({"vault_chunk_chars": int(vault_chunk_chars)})
