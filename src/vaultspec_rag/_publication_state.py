"""Read the sole committed publication authority without touching storage."""

from __future__ import annotations

import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NamedTuple

from . import store_schema
from ._job_errors import FULL_REINDEX_REQUIRED_PHRASE
from ._root_presence import root_is_missing, root_missing_message
from ._source_types import PublicSourceType
from ._store_writes import workspace_volume_path
from .indexer._publication_proof import (
    ProofIncompatibleError,
    ProofMissingError,
    ProofReadConflictError,
    ProofUnverifiableError,
)
from .indexer._run_ledger_models import (
    RunLedgerContentionError,
    RunLedgerError,
    SourceResetEpochError,
    index_run_ledger_path,
)
from .indexer._run_ledger_runtime import RunLedger
from .store_runtime import configured_backend_identity

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from .indexer._publication_proof import ProofEvidence, ProofReadToken
    from .indexer._rebuild_lifecycle import ResetEpochFence
    from .indexer._run_ledger_models import PublicationProof, PublicationReceipt

__all__ = [
    "UNREADABLE_PUBLICATION_ERRORS",
    "IndexTransitionError",
    "PublicationSnapshot",
    "SourceReadFence",
    "UnfinishedResetError",
    "acquire_publication_snapshot",
    "capture_source_read_fence",
    "clear_publication_state",
    "missing_ledger_error",
    "read_all_publication_evidence",
    "read_current_epoch",
]

#: Every way a root's committed proof can be unreadable right now: absent,
#: incompatible, or unverifiable proof; a run ledger an older build wrote, or
#: one that is corrupt or contended; and a receipt an index run holds open while
#: it publishes. A read that only uses the proof when there is one treats each of
#: these as absence. Naming a subset made the rest fail read-only requests: a
#: search over a root with an old ledger, or one issued while an update was
#: publishing, answered with an internal server error.
UNREADABLE_PUBLICATION_ERRORS: Final = (
    ProofUnverifiableError,
    ProofReadConflictError,
    RunLedgerError,
)

# Only the exact leased recovery writer may read its canonical parent.
publication_recovery_receipt: ContextVar[PublicationReceipt | None] = ContextVar(
    "publication_recovery_receipt", default=None
)


class PublicationSnapshot(NamedTuple):
    """One committed proof and the token fencing a related backend read."""

    proof: PublicationProof
    ledger: RunLedger
    token: ProofReadToken
    writer_receipt: PublicationReceipt | None = None

    def validate(self) -> None:
        """Reject a backend read concurrent with publication."""
        if self.writer_receipt is None:
            self.ledger.validate_publication_read_token(self.token)
            return
        key = self.token.compatibility_key
        proof, _token = self.ledger.acquire_current_publication_snapshot(
            source_type=key.source_type,
            root_identity=key.root_identity,
            backend_identity=key.backend_identity,
            writer_receipt=self.writer_receipt,
        )
        self.token.validate(
            compatibility_key=proof.compatibility_key,
            revision=proof.revision,
            reservation_sequence=proof.reservation_sequence,
            has_open_receipt=False,
        )


def _collection(source: PublicSourceType) -> str:
    if source is PublicSourceType.CODE:
        return store_schema.CODE_COLLECTION
    if source is PublicSourceType.VAULT:
        return store_schema.VAULT_COLLECTION
    if source is PublicSourceType.DOCUMENT:
        return store_schema.DOCUMENT_COLLECTION
    raise ValueError("publication snapshots require one concrete source")


def missing_ledger_error(root: pathlib.Path) -> ProofMissingError:
    """Explain a root that has no run ledger, and so no publication proof.

    The remedy is an explicit rebuild, unless the root itself is gone: a
    rebuild cannot restore a deleted root, so that refusal must not ask for one.
    """
    cause = (
        root_missing_message(root)
        if root_is_missing(root)
        else FULL_REINDEX_REQUIRED_PHRASE
    )
    return ProofMissingError(f"publication proof does not exist; {cause}")


def acquire_publication_snapshot(
    root: pathlib.Path,
    source: PublicSourceType,
) -> PublicationSnapshot:
    """Acquire and validate the current proof for one storage projection."""
    resolved = root.resolve()
    ledger_path = index_run_ledger_path(workspace_volume_path(resolved))
    if not ledger_path.is_file():
        raise missing_ledger_error(resolved)
    ledger = RunLedger(ledger_path)
    backend_identity = configured_backend_identity(resolved)
    writer_receipt = publication_recovery_receipt.get()
    if writer_receipt is not None:
        recovery_key = writer_receipt.compatibility_key
        if (
            recovery_key.root_identity != str(resolved)
            or recovery_key.source_type is not source
            or recovery_key.backend_identity != backend_identity
        ):
            writer_receipt = None
    proof, token = ledger.acquire_current_publication_snapshot(
        source_type=source,
        root_identity=str(resolved),
        backend_identity=backend_identity,
        writer_receipt=writer_receipt,
    )
    key = proof.compatibility_key
    if (
        key.collection_identity != _collection(source)
        or key.storage_schema != store_schema.STORAGE_SCHEMA_VERSION
        or key.payload_schema != store_schema.STORAGE_SCHEMA_VERSION
    ):
        raise ProofIncompatibleError(
            "canonical publication proof does not match the current storage projection"
        )
    return PublicationSnapshot(
        proof=proof, ledger=ledger, token=token, writer_receipt=writer_receipt
    )


def read_all_publication_evidence(
    snapshot: PublicationSnapshot,
) -> dict[str, ProofEvidence]:
    """Read a complete canonical proof through bounded keyset pages."""
    evidence: dict[str, ProofEvidence] = {}
    after_path: str | None = None
    while True:
        page = snapshot.ledger.publication_evidence_page(
            snapshot.proof.compatibility_key,
            after_path=after_path,
        )
        if not page:
            return evidence
        evidence.update(page)
        after_path = next(reversed(page))


def clear_publication_state(
    root: pathlib.Path,
    source: PublicSourceType,
    backend_identity: str,
) -> None:
    """Remove canonical authority for one source before storage deletion."""
    resolved = root.resolve()
    ledger_path = index_run_ledger_path(workspace_volume_path(resolved))
    if not ledger_path.is_file():
        return
    RunLedger(ledger_path).clear_publication_source(
        source,
        str(resolved),
        backend_identity,
    )


class IndexTransitionError(RuntimeError):
    """A read of one source could not be answered from a single reset epoch.

    Raised when the source's reset is between intent and completion at the
    start of the read, and when a reset begins before the read is validated.
    Either way the read may have observed storage that reset discards, so
    nothing it found is returned. A reset that crosses a read is running
    now, so that condition is retryable; a reset found unfinished at the start
    of the read raises :class:`UnfinishedResetError` instead.
    """

    def __init__(self, source: PublicSourceType, detail: str) -> None:
        super().__init__(f"the {source.value} index is being reset: {detail}")
        self.source = source


class UnfinishedResetError(IndexTransitionError):
    """The source's latest reset recorded intent and has not completed.

    Unlike a reset that crosses a read, this state persists until a job
    finishes that reset or a new rebuild replaces it. Whether a retry can
    succeed depends on whether a live job still owns the reset, which only the
    caller holding the job snapshot can tell; ``fence`` names the reset so it
    can.
    """

    def __init__(self, fence: ResetEpochFence) -> None:
        super().__init__(
            fence.source_type,
            f"rebuild generation {fence.generation_id} left reset epoch "
            f"{fence.epoch} at {fence.phase} and its empty replacement is not ready",
        )
        self.fence = fence


@dataclass(frozen=True, slots=True)
class SourceReadFence:
    """The reset epoch one read of one source began under.

    ``baseline_readable`` is false when this build could not read the root's
    run ledger at capture. A reset records every phase in that ledger, so no
    reset can be in progress while it stays unreadable; one that becomes
    readable and names a reset fences the read like any other.
    """

    fence: ResetEpochFence
    baseline_readable: bool

    def validate(self) -> None:
        """Raise unless the source is still at the epoch the read began under.

        Raises:
            IndexTransitionError: a reset began after capture, or the reset
                state became unreadable after a readable capture.
        """
        source = self.fence.source_type
        try:
            self.fence.validate()
        except SourceResetEpochError as exc:
            raise IndexTransitionError(source, exc.detail) from exc
        except (RunLedgerError, sqlite3.Error) as exc:
            if self.baseline_readable:
                raise IndexTransitionError(
                    source, f"its reset state became unreadable: {exc}"
                ) from exc


def capture_source_read_fence(
    root: pathlib.Path, source: PublicSourceType
) -> SourceReadFence:
    """Capture *source*'s reset epoch before any read of its storage.

    Raises:
        IndexTransitionError: the source's reset is in progress, or its reset
            state is held by a writer and cannot be read yet.
    """
    from .indexer._rebuild_lifecycle import ResetEpochFence, capture_reset_epoch

    resolved = root.resolve()
    backend_identity = configured_backend_identity(resolved)
    try:
        fence = capture_reset_epoch(resolved, source, backend_identity)
    except RunLedgerContentionError as exc:
        raise IndexTransitionError(
            source, f"its reset state is held by a writer: {exc}"
        ) from exc
    except RunLedgerError:
        return SourceReadFence(
            fence=ResetEpochFence(
                ledger_path=index_run_ledger_path(workspace_volume_path(resolved)),
                source_type=source,
                root_identity=str(resolved),
                backend_identity=backend_identity,
                epoch=0,
                phase=None,
            ),
            baseline_readable=False,
        )
    if not fence.serving:
        raise UnfinishedResetError(fence)
    return SourceReadFence(fence=fence, baseline_readable=True)


def read_current_epoch[T](
    root: pathlib.Path, source: PublicSourceType, read: Callable[[], T]
) -> T:
    """Run *read* against *source*'s storage and return it only if no reset crossed it.

    The fence is captured before *read* touches storage and validated after it
    returns, so a result is either entirely from the epoch the read began
    under or is refused. Partial content a rebuild has written so far is that
    epoch's content and is returned; completeness is a separate claim the
    publication proof makes.

    Raises:
        IndexTransitionError: the source was mid-reset at capture, or a reset
            began before validation.
    """
    read_fence = capture_source_read_fence(root, source)
    result = read()
    read_fence.validate()
    return result
