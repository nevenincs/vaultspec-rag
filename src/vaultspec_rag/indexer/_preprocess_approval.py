"""Operator approval of a root's preprocessing policy.

A root's ``.vaultragpreprocess.toml`` names commands that indexing launches
with the operator's privileges, and anyone who can change the repository can
change that file. The file therefore never authorises its own execution: its
rules run only while the operator has approved that exact policy for that
exact root.

An approval binds two things. The canonical root, so the same policy checked
out somewhere else is a separate decision. And the digest of the policy
file's bytes, so any edit - a new command, a widened pattern, a comment -
returns the root to unapproved until someone has looked again.

The records live in the managed status directory, never in the repository: a
file the repository controls cannot vouch for itself. They are written
owner-only, and a store that is absent, unreadable or malformed approves
nothing, so a damaged store can only withhold execution and never grant it.

Approval is consent, not containment. An approved hook still runs with the
operator's privileges, and the digest covers the policy file rather than the
programs its commands launch.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .._atomic_write import JsonWriteOptions, write_json_atomically
from .._root_identity import canonical_root_key, canonical_root_path

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "PolicyApproval",
    "approval_store_path",
    "approve_policy",
    "policy_is_approved",
    "read_approval",
    "revoke_approval",
]

_STORE_FILENAME = "preprocess-approvals.json"
_STORE_VERSION = 1

# Serialises this process's read-modify-write. Two processes approving at once
# still race on the whole file, and the loser's record is the one dropped: the
# failure direction is a root that has to be approved again.
_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class PolicyApproval:
    """One root's recorded approval.

    Attributes:
        root: The canonical root path as approved, for the operator to read.
        policy_digest: Digest of the policy file's bytes at approval time.
        approved_at: ISO-8601 timestamp of the approval.
    """

    root: str
    policy_digest: str
    approved_at: str


def approval_store_path() -> pathlib.Path:
    """Return the path of the persisted approval store."""
    # Function-local so the spawn worker's import chain, which reaches this
    # module through the rule loader, does not build the config singleton.
    from ..config._settings import managed_status_dir

    return managed_status_dir() / _STORE_FILENAME


def _read_root_records(*, for_update: bool) -> dict[object, object]:
    """Return the store's raw per-root records, empty when it approves nothing.

    Anything short of a well-formed current-version store yields no records.

    Reading "unreadable" as "empty" is the safe answer to "is this root
    approved". It is the wrong answer for a caller about to write the store
    back: a scanner holding the file open for a moment would then cost every
    other root its approval. ``for_update`` lets that read failure propagate.

    Raises:
        OSError: Only with ``for_update``, when the store exists but could
            not be read.
    """
    path = approval_store_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        if for_update:
            raise
        logger.warning(
            "preprocess approval store %s is unreadable (%s); no root is approved",
            path,
            exc,
        )
        return {}
    try:
        parsed: object = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        logger.warning(
            "preprocess approval store %s is malformed (%s); no root is approved",
            path,
            exc,
        )
        return {}
    document = cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}
    roots = document.get("roots")
    if document.get("version") != _STORE_VERSION or not isinstance(roots, dict):
        logger.warning(
            "preprocess approval store %s is not a version %d store; "
            "no root is approved",
            path,
            _STORE_VERSION,
        )
        return {}
    return cast("dict[object, object]", roots)


def _load_store(*, for_update: bool = False) -> dict[str, PolicyApproval]:
    """Return every readable approval, keyed by canonical root key.

    A record missing a field is dropped on its own, so one bad entry withholds
    one root rather than all of them.

    Raises:
        OSError: Only with ``for_update``, when the store exists but could
            not be read.
    """
    approvals: dict[str, PolicyApproval] = {}
    for key, raw_record in _read_root_records(for_update=for_update).items():
        if not isinstance(key, str) or not isinstance(raw_record, dict):
            continue
        record = cast("dict[str, object]", raw_record)
        root = record.get("root")
        digest = record.get("policy_digest")
        approved_at = record.get("approved_at")
        if (
            isinstance(root, str)
            and isinstance(digest, str)
            and digest
            and isinstance(approved_at, str)
        ):
            approvals[key] = PolicyApproval(root, digest, approved_at)
    return approvals


def _write_store(approvals: dict[str, PolicyApproval]) -> None:
    """Publish the whole store, owner-only and durable."""
    write_json_atomically(
        approval_store_path(),
        {
            "version": _STORE_VERSION,
            "roots": {
                key: {
                    "root": approval.root,
                    "policy_digest": approval.policy_digest,
                    "approved_at": approval.approved_at,
                }
                for key, approval in approvals.items()
            },
        },
        JsonWriteOptions(indent=2, sort_keys=True, durable=True, private=True),
    )


def read_approval(root: pathlib.Path | str) -> PolicyApproval | None:
    """Return the approval recorded for *root*, whatever policy it names."""
    return _load_store().get(canonical_root_key(root))


def policy_is_approved(root: pathlib.Path | str, policy_digest: str | None) -> bool:
    """Whether *root* is approved for exactly the policy *policy_digest* names.

    ``None`` is a root with no policy file, which has nothing to approve and
    nothing to run.
    """
    if policy_digest is None:
        return False
    approval = read_approval(root)
    return approval is not None and approval.policy_digest == policy_digest


def approve_policy(
    root: pathlib.Path | str,
    policy_digest: str,
    *,
    approved_at: str,
) -> PolicyApproval:
    """Record that the operator approves *policy_digest* for *root*.

    Replaces any earlier approval of the same root: a root has one approved
    policy at a time. The caller supplies the timestamp so this layer takes no
    clock dependency.

    Raises:
        OSError: The store exists but could not be read, or could not be
            written. Nothing is changed in the first case.
    """
    approval = PolicyApproval(
        root=str(canonical_root_path(root)),
        policy_digest=policy_digest,
        approved_at=approved_at,
    )
    with _LOCK:
        approvals = _load_store(for_update=True)
        approvals[canonical_root_key(root)] = approval
        _write_store(approvals)
    return approval


def revoke_approval(root: pathlib.Path | str) -> bool:
    """Drop the approval recorded for *root*; ``False`` when there was none.

    Raises:
        OSError: The store exists but could not be read, or could not be
            written. Nothing is changed in the first case.
    """
    key = canonical_root_key(root)
    with _LOCK:
        approvals = _load_store(for_update=True)
        if key not in approvals:
            return False
        del approvals[key]
        _write_store(approvals)
    return True
