"""Immutable values and exact arithmetic for publication completeness proofs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .._source_types import PublicSourceType
from ._file_state import validate_rel_path

__all__ = [
    "AggregateDelta",
    "PathDelta",
    "PathOutcome",
    "ProofAggregate",
    "ProofCompatibilityKey",
    "ProofEvidence",
    "ProofIncompatibleError",
    "ProofMismatchError",
    "ProofMissingError",
    "ProofMutationState",
    "ProofOldEvidenceMismatchError",
    "ProofParentMismatchError",
    "ProofProvenance",
    "ProofReadConflictError",
    "ProofReadToken",
    "ProofRebuildRequiredError",
    "ProofReceiptState",
    "ProofUnverifiableError",
    "ProofUnverifiableReason",
    "require_non_empty",
]


def require_non_empty(value: str, *, name: str) -> None:
    """Reject a blank identity field, wherever the proof shapes use one."""
    if not isinstance(value, str) or not value.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        raise ValueError(f"{name} must be non-empty")


def _require_revision(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        raise ValueError(f"{name} must be a non-negative integer")


class PathOutcome(StrEnum):
    """Complete outcome vocabulary for one source identity change."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    EMPTY = "empty"
    IGNORED = "ignored"
    REJECTED = "rejected"
    NOOP = "noop"


class ProofReceiptState(StrEnum):
    """Lifecycle of one reserved parent-to-target proof transition."""

    RESERVED = "reserved"
    SEALED = "sealed"
    ROLLING_BACK = "rolling_back"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"

    @property
    def is_open(self) -> bool:
        """Return whether this receipt prevents the current proof being read."""
        return self in {
            ProofReceiptState.RESERVED,
            ProofReceiptState.SEALED,
            ProofReceiptState.ROLLING_BACK,
        }


class ProofMutationState(StrEnum):
    """Durable progress of one bounded external-storage mutation."""

    PREPARED = "prepared"
    APPLIED = "applied"
    CONFIRMED = "confirmed"


class ProofProvenance(StrEnum):
    """How a proof's exact contents were established."""

    VERIFIED = "verified"
    DELTA_DERIVED = "delta_derived"


class ProofUnverifiableReason(StrEnum):
    """Stable reasons why evidence cannot certify backend contents."""

    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    PARENT_MISMATCH = "parent_mismatch"
    OLD_EVIDENCE_MISMATCH = "old_evidence_mismatch"
    CORRUPT_RECEIPT = "corrupt_receipt"
    UNEXPLAINED_DRIFT = "unexplained_drift"


class ProofUnverifiableError(RuntimeError):
    """Base failure for evidence that cannot support an exact proof."""

    reason: ProofUnverifiableReason

    def __init__(self, message: str, *, reason: ProofUnverifiableReason) -> None:
        super().__init__(message)
        self.reason = reason


class ProofMissingError(ProofUnverifiableError):
    """Required proof ancestry or evidence is absent."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ProofUnverifiableReason.MISSING)


class ProofIncompatibleError(ProofUnverifiableError):
    """Evidence belongs to another proof compatibility identity."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ProofUnverifiableReason.INCOMPATIBLE)


class ProofMismatchError(ProofUnverifiableError):
    """Expected parent or old path evidence does not match durable state."""


class ProofParentMismatchError(ProofMismatchError):
    """A delta or receipt names a different durable parent revision."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ProofUnverifiableReason.PARENT_MISMATCH)


class ProofOldEvidenceMismatchError(ProofMismatchError):
    """A delta's old path evidence differs from authoritative state."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ProofUnverifiableReason.OLD_EVIDENCE_MISMATCH)


class ProofRebuildRequiredError(ProofUnverifiableError):
    """Exact proof can be restored only by an explicitly authorized rebuild."""

    def __init__(
        self,
        message: str,
        *,
        reason: ProofUnverifiableReason,
    ) -> None:
        if reason not in {
            ProofUnverifiableReason.CORRUPT_RECEIPT,
            ProofUnverifiableReason.UNEXPLAINED_DRIFT,
        }:
            raise ValueError("reason does not require authoritative reconstruction")
        super().__init__(message, reason=reason)


class ProofReadConflictError(RuntimeError):
    """A live read could not retain one receipt-free proof snapshot."""


@dataclass(frozen=True, slots=True)
class ProofCompatibilityKey:
    """Stable conditions under which publication proof ancestry is reusable."""

    source_type: PublicSourceType
    root_identity: str
    backend_identity: str
    collection_identity: str
    storage_schema: int
    payload_schema: int
    embedding_schema_identity: str
    chunking_schema_identity: str
    membership_identity: str
    content_identity: str
    policy_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, PublicSourceType):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("source_type must be a PublicSourceType")
        if self.source_type is PublicSourceType.COMBINED:
            raise ValueError("a proof must identify one concrete source type")
        for name in (
            "root_identity",
            "backend_identity",
            "collection_identity",
            "embedding_schema_identity",
            "chunking_schema_identity",
            "membership_identity",
            "content_identity",
            "policy_identity",
        ):
            require_non_empty(getattr(self, name), name=name)
        for name in ("storage_schema", "payload_schema"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProofReadToken:
    """Receipt-free proof snapshot used to fence one backend read."""

    compatibility_key: ProofCompatibilityKey
    revision: int
    reservation_sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.compatibility_key, ProofCompatibilityKey):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("compatibility_key must be a ProofCompatibilityKey")
        _require_revision(self.revision, name="revision")
        _require_revision(self.reservation_sequence, name="reservation_sequence")

    @classmethod
    def from_snapshot(
        cls,
        *,
        compatibility_key: ProofCompatibilityKey,
        revision: int,
        reservation_sequence: int,
        has_open_receipt: bool,
    ) -> ProofReadToken:
        """Capture one atomically read ledger snapshot when no receipt is open."""
        if not isinstance(has_open_receipt, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("has_open_receipt must be a bool")
        if has_open_receipt:
            raise ProofReadConflictError("an open receipt prevents proof certification")
        return cls(
            compatibility_key=compatibility_key,
            revision=revision,
            reservation_sequence=reservation_sequence,
        )

    def validate(
        self,
        *,
        compatibility_key: ProofCompatibilityKey,
        revision: int,
        reservation_sequence: int,
        has_open_receipt: bool,
    ) -> None:
        """Validate against one atomic ledger snapshot after the backend read."""
        if not isinstance(has_open_receipt, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("has_open_receipt must be a bool")
        _require_revision(revision, name="revision")
        _require_revision(reservation_sequence, name="reservation_sequence")
        if compatibility_key != self.compatibility_key:
            raise ProofIncompatibleError(
                "proof compatibility changed during the backend read"
            )
        if (
            has_open_receipt
            or revision != self.revision
            or reservation_sequence != self.reservation_sequence
        ):
            raise ProofReadConflictError("proof state changed during the backend read")


@dataclass(frozen=True, slots=True)
class ProofEvidence:
    """Exact normalized evidence retained for one indexed source identity."""

    rel_path: str
    content_identity: str
    point_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_rel_path(self.rel_path)
        require_non_empty(self.content_identity, name="content_identity")
        if not isinstance(self.point_ids, tuple):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("point_ids must be a tuple")
        if not self.point_ids:
            raise ValueError("indexed evidence must retain at least one point identity")
        if any(
            not isinstance(point_id, str) or not point_id.strip()  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            for point_id in self.point_ids
        ):
            raise ValueError("point_ids must contain only non-empty strings")
        if len(frozenset(self.point_ids)) != len(self.point_ids):
            raise ValueError("point_ids must be unique")
        if self.point_ids != tuple(sorted(self.point_ids)):
            raise ValueError("point_ids must use canonical lexical ordering")


@dataclass(frozen=True, slots=True)
class AggregateDelta:
    """Signed exact change in indexed identities and retained points."""

    indexed_identities: int = 0
    retained_points: int = 0

    def __post_init__(self) -> None:
        for name in ("indexed_identities", "retained_points"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")


@dataclass(frozen=True, slots=True)
class PathDelta:
    """One complete old-to-new source outcome against an expected revision."""

    outcome: PathOutcome
    expected_parent_revision: int
    rel_path: str
    target_rel_path: str | None = None
    old: ProofEvidence | None = None
    new: ProofEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, PathOutcome):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("outcome must be a PathOutcome")
        _require_revision(
            self.expected_parent_revision,
            name="expected_parent_revision",
        )
        validate_rel_path(self.rel_path)
        if self.outcome is PathOutcome.RENAME:
            if self.target_rel_path is None:
                raise ValueError("rename must name a target relative path")
            validate_rel_path(self.target_rel_path)
            if self.target_rel_path == self.rel_path:
                raise ValueError("rename must change the relative path")
        elif self.target_rel_path is not None:
            raise ValueError("target_rel_path is valid only for rename")
        valid_shapes = {
            PathOutcome.ADD: self.old is None and self.new is not None,
            PathOutcome.MODIFY: (
                self.old is not None and self.new is not None and self.old != self.new
            ),
            PathOutcome.DELETE: self.old is not None and self.new is None,
            PathOutcome.RENAME: self.old is not None and self.new is not None,
            PathOutcome.EMPTY: self.new is None,
            PathOutcome.IGNORED: self.new is None,
            PathOutcome.REJECTED: self.new is None,
            PathOutcome.NOOP: self.old is not None and self.old == self.new,
        }
        if not valid_shapes[self.outcome]:
            raise ValueError(f"invalid {self.outcome.value} old-to-new evidence")
        if self.old is not None and self.old.rel_path != self.rel_path:
            raise ValueError("old evidence must match rel_path")
        expected_new_path = (
            self.target_rel_path
            if self.outcome is PathOutcome.RENAME
            else self.rel_path
        )
        if self.new is not None and self.new.rel_path != expected_new_path:
            raise ValueError("new evidence must match the outcome target path")

    @property
    def aggregate_delta(self) -> AggregateDelta:
        """Return the exact signed aggregate adjustment for this outcome."""
        old_identities = int(self.old is not None)
        new_identities = int(self.new is not None)
        old_points = len(self.old.point_ids) if self.old is not None else 0
        new_points = len(self.new.point_ids) if self.new is not None else 0
        return AggregateDelta(
            indexed_identities=new_identities - old_identities,
            retained_points=new_points - old_points,
        )

    @property
    def changes_proof(self) -> bool:
        """Return whether this transition changes normalized proof evidence."""
        return self.old != self.new


@dataclass(frozen=True, slots=True)
class ProofAggregate:
    """Exact breadth certified by one proof revision."""

    indexed_identities: int = 0
    retained_points: int = 0

    def __post_init__(self) -> None:
        for name in ("indexed_identities", "retained_points"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.retained_points < self.indexed_identities:
            raise ValueError("retained_points must be at least indexed_identities")
        if self.indexed_identities == 0 and self.retained_points != 0:
            raise ValueError("zero indexed_identities requires zero retained_points")

    def apply(self, delta: PathDelta | AggregateDelta) -> ProofAggregate:
        """Apply one exact delta, refusing aggregate underflow."""
        adjustment = delta.aggregate_delta if isinstance(delta, PathDelta) else delta
        return ProofAggregate(
            indexed_identities=self.indexed_identities + adjustment.indexed_identities,
            retained_points=self.retained_points + adjustment.retained_points,
        )
