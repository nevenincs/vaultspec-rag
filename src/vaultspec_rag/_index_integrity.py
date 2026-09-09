"""Serve-time reconciliation of a collection's breadth against its published claim.

A collection can silently lose most of its points and keep answering queries
as though it were whole: every remaining point is valid, so searches succeed,
health stays green, and the only symptom is results that quietly stopped
covering the corpus. This module is the invariant that stands between that
state and a confident response: at serve time the collection's actual breadth
must be reconcilable with what its publication claimed, and unexplained
shrinkage degrades loudly - the search still serves, but the response says the
index is short and an operator-facing ERROR names the figures.

One implementation, service-domain: the daemon route and the command line both
acquire a proof snapshot before backend work and render its verdict, so no
entry point can classify the same collection differently. The verdict is a
tri-state, and the third state is the honest one: ``unverifiable`` says "there
is no claim to check against", never "fine" and never "shrunken", so a root
written by a build that recorded no breadth is neither escalated nor quietly
promoted to healthy.

Cheapness is a contract: the live count is the one the search path already
took for its empty-index short-circuit, so the check adds no store round trip.
The ledger proof read is constant-size, and its token is validated after the
backend operation so mixed publication generations fail closed.
"""

from __future__ import annotations

import logging
import threading
import time
import types
from dataclasses import asdict, dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    Protocol,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from . import store_schema
from ._source_types import PublicSourceType
from ._store_writes import workspace_volume_path
from .indexer._file_state import validate_rel_path
from .indexer._publication_proof import (
    ProofIncompatibleError,
    ProofReadConflictError,
    ProofUnverifiableError,
)
from .indexer._run_ledger_models import (
    RunAuthority,
    RunLedgerCompatibilityError,
    RunLedgerConcurrencyError,
    RunLedgerContentionError,
    RunLedgerCorruptionError,
    index_run_ledger_path,
)
from .indexer._run_ledger_runtime import RunLedger
from .store_runtime import configured_backend_identity

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from ._publication_state import PublicationSnapshot
    from .indexer._publication_proof import ProofCompatibilityKey
    from .indexer._run_ledger_models import PublicationProof

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_VERDICT_CONSISTENT",
    "AUDIT_VERDICT_DRIFT",
    "REASON_COUNT_UNAVAILABLE",
    "SHRUNKEN_LOG_INTERVAL_SECONDS",
    "VERDICT_CONSISTENT",
    "VERDICT_SHRUNKEN",
    "VERDICT_UNVERIFIABLE",
    "IndexAudit",
    "IndexIntegrity",
    "IndexIntegritySnapshot",
    "acquire_index_integrity_snapshot",
    "audit_index_integrity",
    "audit_index_sources",
]

IntegrityVerdict = Literal["consistent", "shrunken", "unverifiable"]

VERDICT_CONSISTENT: IntegrityVerdict = "consistent"
VERDICT_SHRUNKEN: IntegrityVerdict = "shrunken"
VERDICT_UNVERIFIABLE: IntegrityVerdict = "unverifiable"

AuditVerdict = Literal["consistent", "drift"]
AUDIT_VERDICT_CONSISTENT: AuditVerdict = "consistent"
AUDIT_VERDICT_DRIFT: AuditVerdict = "drift"
_AUDIT_PAGE_SIZE = 256


class _PayloadContractType(Protocol):
    __required_keys__: frozenset[str]


def _payload_contract(
    payload_type: object,
) -> tuple[frozenset[str], dict[str, object]]:
    contract = cast("_PayloadContractType", payload_type)
    required = contract.__required_keys__
    field_types = cast("dict[str, object]", get_type_hints(payload_type))
    return required, field_types


_AUDIT_PAYLOAD_CONTRACTS = {
    PublicSourceType.VAULT: _payload_contract(store_schema.VaultChunkPayload),
    PublicSourceType.CODE: _payload_contract(store_schema.CodeChunkPayload),
    PublicSourceType.DOCUMENT: _payload_contract(store_schema.DocumentChunkPayload),
}

#: The caller had no live count to compare - the count call failed or the
#: figure never reached the envelope site. Degraded, never fatal: a count that
#: could not be taken proves nothing about the collection either way.
REASON_COUNT_UNAVAILABLE = "count_unavailable"

#: Minimum spacing between ERROR lines for one root and domain. The response
#: envelope carries the verdict on every single search, so the log line exists
#: for an operator tailing logs, not as the transport: one line per minute per
#: domain keeps the signal without letting a busy agent loop write one line
#: per query.
SHRUNKEN_LOG_INTERVAL_SECONDS = 60.0

#: Hard ceiling on remembered roots. A daemon serves a bounded registry of
#: roots, so this is never reached in practice; it exists so a pathological
#: caller cycling through roots cannot grow the two dicts without bound.
_CACHE_MAX_ENTRIES = 512

_STATE_LOCK = threading.Lock()
_ERROR_LAST_EMIT: dict[tuple[str, str], float] = {}


class _BreadthClaim(NamedTuple):
    """Exact aggregate carried by one canonical publication proof."""

    claimed: int
    generation_id: str
    named_files: int


class IndexIntegrity(NamedTuple):
    """One serve-time breadth verdict, with the evidence that produced it.

    Constructed only by a proof-fenced snapshot, so a consumer never
    compares figures for itself - the verdict is the conclusion.
    """

    verdict: IntegrityVerdict
    source: str
    claimed_count: int | None
    live_count: int | None
    generation_id: str | None
    reason: str | None
    named_files: int | None = None
    """Indexed files the manifest names, ``None`` where the domain has none."""
    covered_files: int | None = None
    """Files the publication recorded covering, ``None`` when unrecorded."""

    def as_block(self) -> dict[str, object]:
        """Return the canonical ``index_integrity`` envelope block.

        One projection for every surface. The block is emitted whenever the
        serving path evaluated the check - ``consistent`` included - so a
        consumer can tell "checked and fine" from "surface predates the
        check", where the block is absent entirely. Unknown figures are
        ``null``, never invented; ``missing_count`` appears only over a
        demonstrated point deficit. ``named_files`` appears only where the
        proof names any, so an empty publication renders no file figure.
        """
        block: dict[str, object] = {
            "verdict": self.verdict,
            "source": self.source,
            "claimed_count": self.claimed_count,
            "live_count": self.live_count,
            "generation_id": self.generation_id,
            "reason": self.reason,
        }
        if self.named_files:
            block["named_files"] = self.named_files
            block["covered_files"] = self.covered_files
        if (
            self.verdict == VERDICT_SHRUNKEN
            and self.claimed_count is not None
            and self.live_count is not None
            and self.claimed_count > self.live_count
        ):
            block["missing_count"] = self.claimed_count - self.live_count
        return block


def acquire_index_integrity_snapshot(
    root: pathlib.Path, source: PublicSourceType
) -> IndexIntegritySnapshot:
    """Acquire the proof token that must fence the related backend work."""
    from ._publication_state import acquire_publication_snapshot

    if source is PublicSourceType.COMBINED:
        raise ValueError("combined search has no single publication proof")
    publication = acquire_publication_snapshot(root, source)
    aggregate = publication.proof.aggregate
    claim = _BreadthClaim(
        aggregate.retained_points,
        publication.proof.generation_id,
        aggregate.indexed_identities,
    )
    return IndexIntegritySnapshot(root, source, claim, publication)


class IndexIntegritySnapshot(NamedTuple):
    """Canonical proof held across a backend count or search."""

    root: pathlib.Path
    source: PublicSourceType
    claim: _BreadthClaim
    publication: PublicationSnapshot

    def finish(
        self,
        live_count: int | None,
    ) -> IndexIntegrity:
        """Validate the proof token and classify the fenced backend result."""
        self.publication.validate()
        return _evaluate_claim(
            self.root,
            self.source,
            self.claim,
            live_count,
        )


def _log_shrunken(root: pathlib.Path, integrity: IndexIntegrity) -> None:
    """Emit the operator-facing ERROR for a demonstrated shrink, rate-limited."""
    key = (str(root), integrity.source)
    now = time.monotonic()
    with _STATE_LOCK:
        last = _ERROR_LAST_EMIT.get(key)
        if last is not None and now - last < SHRUNKEN_LOG_INTERVAL_SECONDS:
            return
        if len(_ERROR_LAST_EMIT) >= _CACHE_MAX_ENTRIES:
            _ERROR_LAST_EMIT.clear()
        _ERROR_LAST_EMIT[key] = now
    logger.error(
        "%s collection for %s holds %s of the %s points its publication "
        "(generation %s) claims; searches still serve but results are drawn "
        "from an incomplete index",
        integrity.source,
        root,
        integrity.live_count,
        integrity.claimed_count,
        integrity.generation_id,
    )


def _evaluate_claim(
    root: pathlib.Path,
    source: PublicSourceType,
    claim: _BreadthClaim,
    live_count: int | None,
) -> IndexIntegrity:
    """Reconcile *source*'s live breadth for *root* against its published claim.

    ``live_count`` is the count the search path already took for its
    empty-index short-circuit - supplied, never re-counted, which is what
    keeps this affordable on every query. ``None`` means the caller had no
    count, and that is ``unverifiable``: degraded, never fatal.

    The comparison is exact and one-sided, no tolerance. Every publication
    counts the store immediately after storage reconciliation and writes the
    figure atomically with the generation it describes - for a rebuilt
    generation the proof lands before the served pointer moves, and an
    in-place incremental republishes the figure at the same protected commit
    edge that performs its deletions - so a complete served collection always
    reads back at least its claim. A count above the claim is the legitimate
    motion of an in-flight incremental whose upserts land ahead of its
    republication; a count below it is either demonstrated loss or a
    publication torn mid-replacement, and both deserve the loud verdict. Any
    tolerance wider than zero would mask exactly a loss of that size.

    Some manifests are judged without comparing counts at all, because they
    already disagree with themselves: zero points, or a recorded file
    coverage below the file count, over a manifest that names indexed files.
    Neither pair can be produced by a complete publication, which counts the
    collection after storage reconciliation and records what it found, so
    neither is the "no information" case ``unverifiable`` exists for - the
    manifest is stating a figure and contradicting it in the same breath. A
    zero point claim left to the count comparison would read ``consistent``
    against any live count at all, most perversely against an empty
    collection, and latch there: a claim of zero is satisfied forever, so
    nothing would ever escalate and nothing would ever repair. ``shrunken``
    is both the honest reading and the one the self-heal path acts on.

    An ABSENT figure is the opposite and stays ``unverifiable``: a build that
    never recorded coverage has told us nothing, and escalating on that would
    rebuild every root written before the key existed.

    A ``shrunken`` verdict never blocks the search - partial results beat no
    results - but it is attached to the response and logged at ERROR with the
    figures and the claiming generation, rate-limited per root and domain.
    """
    if live_count is None:
        integrity = IndexIntegrity(
            verdict=VERDICT_UNVERIFIABLE,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=None,
            generation_id=claim.generation_id,
            reason=REASON_COUNT_UNAVAILABLE,
            named_files=claim.named_files or None,
        )
    elif live_count >= claim.claimed:
        integrity = IndexIntegrity(
            verdict=VERDICT_CONSISTENT,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=None,
            named_files=claim.named_files or None,
        )
    else:
        integrity = IndexIntegrity(
            verdict=VERDICT_SHRUNKEN,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=None,
            named_files=claim.named_files or None,
        )
        _log_shrunken(root, integrity)
    return integrity


class _IndexAuditStore(Protocol):
    """Read-only store surface needed by exact publication verification."""

    TABLE_NAME: str
    CODE_TABLE_NAME: str
    DOCUMENT_TABLE_NAME: str
    backend_identity: str

    def index_audit_point_id_matches(
        self,
        physical_id: object,
        logical_id: str,
    ) -> bool: ...

    def scroll_index_audit_content(
        self,
        collection: str,
        *,
        limit: int,
        offset: object | None,
    ) -> tuple[list[dict[str, object]], object | None]: ...


@dataclass(frozen=True, slots=True)
class IndexAudit:
    """Exact comparison of one canonical proof with one backend scan."""

    source: str
    verdict: AuditVerdict
    generation_id: str
    proof_revision: int
    expected_identities: int
    observed_identities: int
    expected_points: int
    scanned_points: int
    matched_points: int
    missing_points: int
    missing_identities: int
    extra_points: int
    foreign_points: int
    incompatible_points: int
    partial_identities: int
    duration_ms: int

    @property
    def ok(self) -> bool:
        """Return whether the backend exactly satisfies the committed proof."""
        return self.verdict == AUDIT_VERDICT_CONSISTENT

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready audit domain result."""
        return {"ok": self.ok, "status": self.verdict, **asdict(self)}


@dataclass(frozen=True, slots=True)
class _AuditPayloadIdentity:
    point_id: str
    rel_path: str
    content_identity: str | None


def _audit_collection(source: PublicSourceType) -> str:
    collections = {
        PublicSourceType.VAULT: store_schema.VAULT_COLLECTION,
        PublicSourceType.CODE: store_schema.CODE_COLLECTION,
        PublicSourceType.DOCUMENT: store_schema.DOCUMENT_COLLECTION,
    }
    try:
        return collections[source]
    except KeyError as exc:
        raise ValueError("index audit requires one concrete source") from exc


def _store_collection(store: _IndexAuditStore, source: PublicSourceType) -> str:
    if source is PublicSourceType.VAULT:
        return store.TABLE_NAME
    if source is PublicSourceType.CODE:
        return store.CODE_TABLE_NAME
    if source is PublicSourceType.DOCUMENT:
        return store.DOCUMENT_TABLE_NAME
    raise ValueError("index audit requires one concrete source")


def _required_payload_text(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"audit payload field {field!r} must be non-empty text")
    return value


def _payload_container_matches(
    value: object,
    origin: object,
    arguments: tuple[object, ...],
) -> bool:
    if origin is list:
        if not isinstance(value, list) or len(arguments) != 1:
            return False
        return all(
            _payload_value_matches(item, arguments[0])
            for item in cast("list[object]", value)
        )
    if origin is dict:
        if not isinstance(value, dict) or len(arguments) != 2:
            return False
        key_type, value_type = arguments
        return all(
            _payload_value_matches(key, key_type)
            and _payload_value_matches(item, value_type)
            for key, item in cast("dict[object, object]", value).items()
        )
    return False


def _payload_value_matches(
    value: object,
    expected: object,
) -> bool:
    if expected is Any or expected is object:
        return True
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(expected, type):
        return isinstance(value, expected)
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin in {types.UnionType, Union}:
        return any(_payload_value_matches(value, option) for option in arguments)
    return _payload_container_matches(value, origin, arguments)


def _validate_audit_payload_schema(
    source: PublicSourceType,
    payload: dict[str, object],
) -> None:
    try:
        required, field_types = _AUDIT_PAYLOAD_CONTRACTS[source]
    except KeyError as exc:
        raise ValueError("index audit requires one concrete source") from exc
    missing = required.difference(payload)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"audit payload is missing required fields: {names}")
    for field_name, expected in field_types.items():
        if field_name in payload and not _payload_value_matches(
            payload[field_name], expected
        ):
            raise ValueError(
                f"audit payload field {field_name!r} has an incompatible type"
            )


def _audit_payload_identity(
    source: PublicSourceType,
    row: dict[str, object],
) -> _AuditPayloadIdentity:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("audit row payload must be an object")
    typed_payload = cast("dict[str, object]", payload)
    _validate_audit_payload_schema(source, typed_payload)
    if source is PublicSourceType.CODE:
        identity = _AuditPayloadIdentity(
            point_id=_required_payload_text(typed_payload, "chunk_id"),
            rel_path=_required_payload_text(typed_payload, "path"),
            content_identity=None,
        )
    elif source is PublicSourceType.DOCUMENT:
        identity = _AuditPayloadIdentity(
            point_id=_required_payload_text(typed_payload, "document_id"),
            rel_path=_required_payload_text(typed_payload, "source_path"),
            content_identity=_required_payload_text(
                typed_payload, "content_fingerprint"
            ),
        )
    elif source is PublicSourceType.VAULT:
        doc_id = _required_payload_text(typed_payload, "doc_id")
        ordinal = typed_payload.get("chunk_ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise ValueError(
                "audit payload field 'chunk_ordinal' must be a non-negative integer"
            )
        identity = _AuditPayloadIdentity(
            point_id=f"{doc_id}#c{ordinal}",
            rel_path=_required_payload_text(typed_payload, "path"),
            content_identity=None,
        )
    else:
        raise ValueError("index audit requires one concrete source")
    validate_rel_path(identity.rel_path)
    return identity


@dataclass(slots=True)
class _AuditCounters:
    scanned_points: int = 0
    matched_ids: set[str] = field(default_factory=set)
    matched_by_path: dict[str, set[str]] = field(default_factory=dict)
    observed_paths: set[str] = field(default_factory=set)
    seen_ids: set[str] = field(default_factory=set)
    evidence_sizes: dict[str, int] = field(default_factory=dict)
    extra_points: int = 0
    foreign_points: int = 0
    incompatible_points: int = 0


def _classify_audit_page(  # noqa: PLR0913 - one explicit audit snapshot contract.
    ledger: RunLedger,
    key: ProofCompatibilityKey,
    source: PublicSourceType,
    store: _IndexAuditStore,
    rows: list[dict[str, object]],
    counters: _AuditCounters,
) -> None:
    counters.scanned_points += len(rows)
    identities: list[_AuditPayloadIdentity] = []
    for row in rows:
        try:
            identity = _audit_payload_identity(source, row)
            if not store.index_audit_point_id_matches(
                row.get("id"),
                identity.point_id,
            ):
                raise ValueError("backend physical point identity is incompatible")
        except (TypeError, ValueError):
            counters.incompatible_points += 1
            continue
        counters.observed_paths.add(identity.rel_path)
        if identity.point_id in counters.seen_ids:
            counters.incompatible_points += 1
            continue
        counters.seen_ids.add(identity.point_id)
        identities.append(identity)

    candidate_ids = tuple(identity.point_id for identity in identities)
    paths = tuple(dict.fromkeys(identity.rel_path for identity in identities))
    retained = ledger.publication_point_ids_for_candidates(key, candidate_ids)
    evidence = ledger.publication_evidence_for_paths(key, paths)
    counters.evidence_sizes.update(
        {rel_path: len(item.point_ids) for rel_path, item in evidence.items()}
    )
    for identity in identities:
        item = evidence.get(identity.rel_path)
        if identity.point_id not in retained:
            counters.extra_points += 1
        elif item is None or identity.point_id not in item.point_ids:
            counters.foreign_points += 1
        elif (
            identity.content_identity is not None
            and identity.content_identity != item.content_identity
        ):
            counters.incompatible_points += 1
        else:
            counters.matched_ids.add(identity.point_id)
            counters.matched_by_path.setdefault(identity.rel_path, set()).add(
                identity.point_id
            )


def _scan_audit_store(
    ledger: RunLedger,
    key: ProofCompatibilityKey,
    source: PublicSourceType,
    backend_identity: str,
    store: _IndexAuditStore,
) -> _AuditCounters:
    if store.backend_identity != backend_identity:
        raise ProofIncompatibleError(
            "opened store backend differs from the canonical proof backend"
        )
    collection = _store_collection(store, source)
    counters = _AuditCounters()
    offset: object | None = None
    while True:
        rows, next_offset = store.scroll_index_audit_content(
            collection,
            limit=_AUDIT_PAGE_SIZE,
            offset=offset,
        )
        if len(rows) > _AUDIT_PAGE_SIZE:
            raise RuntimeError("backend returned an oversized audit page")
        _classify_audit_page(ledger, key, source, store, rows, counters)
        if next_offset is None:
            return counters
        if next_offset == offset:
            raise RuntimeError("backend audit pagination did not advance")
        offset = next_offset


def _audit_result(
    source: PublicSourceType,
    proof: PublicationProof,
    counters: _AuditCounters,
    started: float,
) -> IndexAudit:
    expected_identities = proof.aggregate.indexed_identities
    expected_points = proof.aggregate.retained_points
    matched_points = len(counters.matched_ids)
    missing_points = max(expected_points - matched_points, 0)
    missing_identities = max(
        expected_identities - len(counters.matched_by_path),
        0,
    )
    partial_identities = sum(
        1
        for rel_path, point_ids in counters.matched_by_path.items()
        if len(point_ids) < counters.evidence_sizes[rel_path]
    )
    consistent = (
        counters.scanned_points == expected_points
        and matched_points == expected_points
        and len(counters.matched_by_path) == expected_identities
        and not counters.extra_points
        and not counters.foreign_points
        and not counters.incompatible_points
        and not partial_identities
    )
    return IndexAudit(
        source=source.value,
        verdict=(AUDIT_VERDICT_CONSISTENT if consistent else AUDIT_VERDICT_DRIFT),
        generation_id=proof.generation_id,
        proof_revision=proof.revision,
        expected_identities=expected_identities,
        observed_identities=len(counters.observed_paths),
        expected_points=expected_points,
        scanned_points=counters.scanned_points,
        matched_points=matched_points,
        missing_points=missing_points,
        missing_identities=missing_identities,
        extra_points=counters.extra_points,
        foreign_points=counters.foreign_points,
        incompatible_points=counters.incompatible_points,
        partial_identities=partial_identities,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
    )


def audit_index_integrity(
    root: pathlib.Path,
    source: PublicSourceType,
    authority: RunAuthority,
    store_factory: Callable[[], AbstractContextManager[object]],
) -> IndexAudit:
    """Verify one backend projection against its existing canonical proof.

    The proof and read token are acquired before opening the store. Every
    ledger lookup and backend page is bounded, and the token is validated only
    after the final page so a concurrent receipt or proof revision makes the
    entire scan unusable. This function never creates, seeds, repairs, or
    migrates proof; absence is an explicit-rebuild refusal.
    """
    if authority is not RunAuthority.AUDIT_VERIFICATION:
        raise PermissionError("exact audit requires audit-verification authority")
    if not isinstance(source, PublicSourceType):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
        raise TypeError("source must be a PublicSourceType")
    logical_collection = _audit_collection(source)
    resolved = root.resolve()
    ledger_path = index_run_ledger_path(workspace_volume_path(resolved))
    if not ledger_path.is_file():
        from .indexer._publication_proof import ProofMissingError

        raise ProofMissingError(
            "canonical publication proof does not exist; an explicit rebuild is "
            "required"
        )

    started = time.perf_counter()
    backend_identity = configured_backend_identity(resolved)
    ledger = RunLedger(ledger_path)
    proof, token = ledger.acquire_current_publication_snapshot(
        source_type=source,
        root_identity=str(resolved),
        backend_identity=backend_identity,
    )
    key = proof.compatibility_key
    if (
        key.collection_identity != logical_collection
        or key.storage_schema != store_schema.STORAGE_SCHEMA_VERSION
        or key.payload_schema != store_schema.STORAGE_SCHEMA_VERSION
    ):
        raise ProofIncompatibleError(
            "canonical publication proof does not match the current storage projection"
        )
    with store_factory() as raw_store:
        store = cast("_IndexAuditStore", raw_store)
        counters = _scan_audit_store(
            ledger,
            key,
            source,
            backend_identity,
            store,
        )
    ledger.validate_publication_read_token(token)
    return _audit_result(source, proof, counters, started)


def _audit_rebuild_required(
    source: PublicSourceType,
    error: ProofUnverifiableError
    | RunLedgerCompatibilityError
    | RunLedgerCorruptionError,
) -> dict[str, object]:
    from ._operator_commands import IndexCommandOptions, index_command

    reason = getattr(error, "reason", None)
    return {
        "ok": False,
        "status": "rebuild_required",
        "source": source.value,
        "error_kind": (reason.value if reason is not None else type(error).__name__),
        "message": str(error),
        "remediation": [
            index_command(source, IndexCommandOptions(rebuild=True)),
        ],
    }


def audit_index_sources(
    root: pathlib.Path,
    source: PublicSourceType,
    authority: RunAuthority,
    store_factory: Callable[[], AbstractContextManager[object]],
) -> dict[str, object]:
    """Audit one or all source projections without acquiring publication rights."""
    if authority is not RunAuthority.AUDIT_VERIFICATION:
        raise PermissionError("exact audit requires audit-verification authority")
    sources = (
        (
            PublicSourceType.VAULT,
            PublicSourceType.CODE,
            PublicSourceType.DOCUMENT,
        )
        if source is PublicSourceType.COMBINED
        else (source,)
    )
    domains: dict[str, dict[str, object]] = {}
    for current in sources:
        try:
            result = audit_index_integrity(
                root,
                current,
                authority,
                store_factory,
            )
        except (
            ProofReadConflictError,
            RunLedgerConcurrencyError,
            RunLedgerContentionError,
        ) as exc:
            domains[current.value] = {
                "ok": False,
                "status": "conflict",
                "source": current.value,
                "error_kind": "proof_read_conflict",
                "message": str(exc),
                "retryable": True,
            }
        except (
            ProofUnverifiableError,
            RunLedgerCompatibilityError,
            RunLedgerCorruptionError,
        ) as exc:
            domains[current.value] = _audit_rebuild_required(current, exc)
        else:
            domain = result.as_dict()
            if not result.ok:
                from ._operator_commands import IndexCommandOptions, index_command

                domain["error_kind"] = "unexplained_drift"
                domain["remediation"] = [
                    index_command(current, IndexCommandOptions(rebuild=True))
                ]
            domains[current.value] = domain

    ok = all(bool(domain["ok"]) for domain in domains.values())
    statuses = {str(domain["status"]) for domain in domains.values()}
    if ok:
        status = AUDIT_VERDICT_CONSISTENT
    elif "conflict" in statuses:
        status = "conflict"
    elif "rebuild_required" in statuses:
        status = "rebuild_required"
    else:
        status = AUDIT_VERDICT_DRIFT
    return {
        "ok": ok,
        "partial": any(bool(domain["ok"]) for domain in domains.values()) and not ok,
        "status": status,
        "domains": domains,
    }
