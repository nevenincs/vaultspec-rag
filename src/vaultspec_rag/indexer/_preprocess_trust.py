"""Per-root trust-on-first-use store for document preprocessing.

Preprocess rules run project-supplied commands, so a cloned or untrusted
repository must never execute its ``.vaultragpreprocess.toml`` merely because
it was indexed or watched (untrusted-repo RCE, audit C1). The
index-drift-hardening ADR (D5) resolves this with trust-on-first-use: a root's
resolved rule set is hashed, and its rules load in the default mode only after
an operator has trusted that exact hash. This module is the durable record of
those trust decisions.

The store mirrors :mod:`storage_manifest`: a ``preprocess-trust.json`` sidecar
under the managed status dir (``status_dir``, ``~/.vaultspec-rag`` by default,
overridable via ``VAULTSPEC_RAG_STATUS_DIR``) - the per-host, gitignored,
test-isolatable home the daemon already uses for ``service.json`` and the
storage manifest. It is NEVER written inside the repository, which is
attacker-controlled. Records are keyed by ``root_collection_prefix`` so the key
is a one-way hash of the resolved root path, matching the server-mode namespace.

The trust is on the *resolved rule set*, not the config file bytes: a benign
comment or whitespace edit re-resolves to the same hash (no re-prompt), while a
command, pattern, or invocation-field change produces a new hash and reverts the
root to untrusted (closing the trust/execution TOCTOU - the hash is recomputed
at every load).

The module is deliberately stdlib-only (``hashlib``/``json``/``pathlib``/
``threading``) so it stays importable from the CPU-only spawn chunk worker
import chain without dragging in torch (``index-workers-stay-cpu-only``). Writes
are atomic (``.tmp`` sibling plus ``os.replace``) under a process lock; a
corrupt or unreadable store degrades to "untrusted" (warn, never raise) so a
damaged sidecar can never wedge the indexer - it only re-prompts for trust.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..store import root_collection_prefix

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._preprocess_config import PreprocessRule

logger = logging.getLogger(__name__)

__all__ = [
    "TrustRecord",
    "hash_rule_set",
    "is_trusted",
    "load_trust_store",
    "read_trust",
    "record_trust",
    "remove_prefix",
    "remove_trust",
    "trust_store_path",
]

# Filename of the trust store inside the managed status dir. Mirrors the
# storage-manifest convention in ``storage_manifest.py``.
_TRUST_STORE_FILENAME = "preprocess-trust.json"

# Digest size (bytes) for the resolved-rule-set hash. 16 bytes / 32 hex chars is
# ample collision resistance for a trust integrity check while keeping the stored
# record compact.
_RULE_SET_DIGEST_SIZE = 16

# Serialises in-process read-modify-write so two callers recording trust
# concurrently cannot drop each other's entries. Cross-process writers still
# rely on atomic ``os.replace`` (last-writer-wins on the whole file).
_LOCK = threading.RLock()


@dataclass(frozen=True)
class TrustRecord:
    """One root's persisted preprocess-trust decision.

    Attributes:
        prefix: The collection prefix (``r{hash}_``) keying this root.
        root: The resolved root path, as a string, for operator legibility.
        rule_set_hash: The blake2b hex digest of the resolved rule set that was
            trusted. Trust holds only while a freshly-resolved set re-hashes to
            this value.
        trusted_at: ISO-8601 timestamp of when the trust was recorded, or the
            empty string when unstamped.
    """

    prefix: str
    root: str
    rule_set_hash: str
    trusted_at: str = ""


def _status_dir_path() -> Path:
    """Resolve the managed status directory the same way the rest of the system does.

    Resolves through ``get_config().status_dir`` (CLI ``--status-dir`` override
    -> ``VAULTSPEC_RAG_STATUS_DIR`` env -> default) so the trust store always
    lands beside ``service.json`` and the storage manifest, and so tests that
    isolate ``VAULTSPEC_RAG_STATUS_DIR`` to a tmp path never touch the real
    machine store. The import is function-local to avoid an import cycle with
    the config wrapper.
    """
    from ..config import get_config

    return Path(str(get_config().status_dir)).expanduser()


def trust_store_path() -> Path:
    """Return the path of the persisted preprocess-trust store."""
    return _status_dir_path() / _TRUST_STORE_FILENAME


def hash_rule_set(rules: Iterable[PreprocessRule]) -> str:
    """Return the blake2b hash of a resolved, ordered preprocess rule set.

    The hash is canonical over the fields that determine what commands run and
    in what order (ADR D5): per rule ``pattern``, ``command``/``entry_point``,
    ``on_error``, ``priority``, resolved ``timeout_s``, ``options``, and
    ``order``. Rules are hashed in the iteration order given (the loader already
    yields them sorted by ``(priority, order)``), and the JSON serialisation
    sorts object keys, so a benign comment or whitespace edit re-resolves to the
    same digest while any invocation change produces a new one.

    Args:
        rules: The resolved rules in precedence order (``PreprocessConfig.rules``).

    Returns:
        A hex blake2b digest of the canonical rule-set serialisation.
    """
    canonical = [
        {
            "pattern": rule.pattern,
            "command": rule.command,
            "entry_point": rule.entry_point,
            "on_error": rule.on_error,
            "priority": rule.priority,
            "timeout_s": rule.timeout_s,
            "options": rule.options,
            "order": rule.order,
        }
        for rule in rules
    ]
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.blake2b(
        payload.encode("utf-8"), digest_size=_RULE_SET_DIGEST_SIZE
    ).hexdigest()


def load_trust_store() -> dict[str, TrustRecord]:
    """Load the trust store as a mapping of collection prefix to record.

    A missing store (the common case on a fresh host) returns an empty mapping.
    A malformed or unreadable store is treated as empty rather than raised: a
    corrupt runtime hint must never crash the indexer - an empty store simply
    classifies every root as untrusted, the conservative outcome. Individual
    malformed records are skipped so one bad entry never voids the rest.

    Returns:
        Mapping of collection prefix to :class:`TrustRecord`.
    """
    path = trust_store_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("preprocess-trust store unreadable at %s: %s", path, exc)
        return {}
    try:
        parsed: object = json.loads(raw)
    except ValueError as exc:
        logger.warning("preprocess-trust store malformed at %s: %s", path, exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("preprocess-trust store at %s is not an object; ignoring", path)
        return {}
    roots_obj = cast("dict[str, object]", parsed).get("roots")
    if not isinstance(roots_obj, dict):
        return {}
    roots = cast("dict[str, object]", roots_obj)
    records: dict[str, TrustRecord] = {}
    for prefix, record_obj in roots.items():
        if not isinstance(record_obj, dict):
            continue
        record = cast("dict[str, object]", record_obj)
        rule_set_hash = record.get("rule_set_hash")
        root = record.get("root")
        if not isinstance(rule_set_hash, str) or not isinstance(root, str):
            continue
        records[prefix] = TrustRecord(
            prefix=prefix,
            root=root,
            rule_set_hash=rule_set_hash,
            trusted_at=str(record.get("trusted_at", "")),
        )
    return records


def _write_trust_store(records: dict[str, TrustRecord]) -> Path:
    """Atomically persist the trust-store mapping to disk."""
    path = trust_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "roots": {
            record.prefix: {
                "root": record.root,
                "rule_set_hash": record.rule_set_hash,
                "trusted_at": record.trusted_at,
            }
            for record in records.values()
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_trust(root: Path | str) -> TrustRecord | None:
    """Return the trust record for ``root``, or ``None`` when untrusted.

    Args:
        root: The workspace root whose trust record to read.

    Returns:
        The :class:`TrustRecord`, or ``None`` when no record exists.
    """
    return load_trust_store().get(root_collection_prefix(root))


def is_trusted(root: Path | str, rule_set_hash: str) -> bool:
    """Return whether ``root`` is trusted for the given resolved-rule-set hash.

    Trust holds only when a record exists for the root AND its stored hash
    equals ``rule_set_hash`` - so a changed rule set (a new hash) reverts the
    root to untrusted automatically.

    Args:
        root: The workspace root being checked.
        rule_set_hash: The freshly-computed hash of the root's resolved rules.

    Returns:
        ``True`` when the root's trust record matches the current hash.
    """
    record = read_trust(root)
    return record is not None and record.rule_set_hash == rule_set_hash


def record_trust(
    root: Path | str, *, rule_set_hash: str, trusted_at: str = ""
) -> TrustRecord:
    """Upsert the trust record for ``root`` and persist it.

    The prefix is derived from ``root_collection_prefix`` so it matches the
    server-mode collection namespace exactly. The call is a read-modify-write
    under the process lock so it preserves every other root's record.

    Args:
        root: The workspace root being trusted.
        rule_set_hash: The hash of the resolved rule set being trusted.
        trusted_at: ISO-8601 timestamp to stamp; the caller supplies it so this
            layer takes no clock dependency.

    Returns:
        The persisted :class:`TrustRecord`.
    """
    resolved = str(Path(root).resolve())
    prefix = root_collection_prefix(root)
    record = TrustRecord(
        prefix=prefix,
        root=resolved,
        rule_set_hash=rule_set_hash,
        trusted_at=trusted_at,
    )
    with _LOCK:
        records = load_trust_store()
        records[prefix] = record
        _write_trust_store(records)
    return record


def remove_prefix(prefix: str) -> bool:
    """Drop the trust record for ``prefix`` and persist.

    Args:
        prefix: The collection prefix to forget.

    Returns:
        ``True`` if a record was removed, ``False`` if none existed.
    """
    with _LOCK:
        records = load_trust_store()
        if prefix not in records:
            return False
        del records[prefix]
        _write_trust_store(records)
    return True


def remove_trust(root: Path | str) -> bool:
    """Drop the trust record for ``root`` and persist.

    Args:
        root: The workspace root whose trust to revoke.

    Returns:
        ``True`` if a record was removed, ``False`` if none existed.
    """
    return remove_prefix(root_collection_prefix(root))
