"""Read-only donor candidacy for encode-seam vector reuse.

When a root is indexed, byte-identical chunk vectors may already exist in a
sibling namespace (most commonly another git worktree of the same repository).
This module answers two read-only questions for the encode seam:

* **Discovery** - which stored namespaces could donate vectors for a given
  indexing root and collection kind? Candidates come exclusively from the
  persisted storage manifest (prefix -> root/backend/last-indexed), the
  indexing root's own prefix is excluded, siblings of the same repository
  family are ranked first, and the list is hard-capped.
* **Eligibility** - may a specific candidate actually serve as a donor? Every
  gate must pass: same collection kind, identical dense dimensionality and
  named-vector layout, identical recorded embedding-model identity, and
  content-epoch sentinel equality between the donor root's sidecar and the
  indexing root's effective epoch. Any gate that cannot be evaluated (missing
  or unreadable donor sidecar, unreachable donor schema) fails closed: the
  candidate is ineligible.

Ranking is a hit-rate heuristic only - it decides which donors are consulted
first, never whether reuse is correct. Correctness rests on the eligibility
gates here plus the per-point payload-content verification at the seam.

This module is pure CPU and strictly read-only: it never imports torch, never
opens a store handle, and never writes anything anywhere. It stays importable
from the indexer package without initialising CUDA (heavier neighbours such as
the storage manifest are imported function-locally).
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, Unpack

from .. import store_schema
from .._index_breadth import index_meta_path
from .._source_types import PublicSourceType
from ._code_meta import CODE_EMBED_SCHEMA
from ._code_meta import CONTENT_EPOCH_KEY as _CODE_CONTENT_EPOCH_KEY
from ._code_meta import EMBED_SCHEMA_KEY as _CODE_EMBED_SCHEMA_KEY
from ._document_meta import (
    DOCUMENT_META_SCHEMA_VERSION,
    DocumentMetadataError,
    document_metadata_path,
    read_document_meta,
)
from ._vault_meta import VAULT_CONTENT_EPOCH_KEY, VAULT_POINT_SCHEMA_KEY

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ..storage_manifest import ManifestEntry

logger = logging.getLogger(__name__)


class _EligibilityOptions(TypedDict, total=False):
    kind: CollectionKind
    expected_content_epoch: str
    expected_schema: VectorSchema | None
    donor_schema_probe: Callable[[str], VectorSchema | None] | None
    expected_model: ModelIdentity | None


@dataclass(frozen=True)
class _EligibilityRequest:
    candidate: DonorCandidate
    kind: CollectionKind
    expected_content_epoch: str
    expected_schema: VectorSchema | None = None
    donor_schema_probe: Callable[[str], VectorSchema | None] | None = None
    expected_model: ModelIdentity | None = None


__all__ = [
    "DONOR_CANDIDATE_CAP",
    "CollectionKind",
    "DonorCandidate",
    "DonorEligibility",
    "DonorRecordedState",
    "IneligibilityReason",
    "ModelIdentity",
    "VectorSchema",
    "current_model_identity",
    "discover_donor_candidates",
    "evaluate_donor_eligibility",
    "expected_vector_schema",
    "index_meta_source",
    "read_donor_recorded_state",
]

#: Hard cap on donor candidates consulted for one indexing run. Small on
#: purpose: donors beyond the top-ranked few are unlikely to add hits, and
#: every candidate adds read traffic against the shared server during
#: indexing. A named constant so measurement can tune it in one place.
DONOR_CANDIDATE_CAP = 3


class CollectionKind(enum.Enum):
    """Closed set of collection kinds a namespace stores."""

    VAULT = "vault"
    CODE = "code"
    DOCUMENT = "document"

    @property
    def collection_suffix(self) -> str:
        """Return the backend-neutral collection name for this kind."""
        if self is CollectionKind.VAULT:
            return store_schema.VAULT_COLLECTION
        if self is CollectionKind.CODE:
            return store_schema.CODE_COLLECTION
        return store_schema.DOCUMENT_COLLECTION


def index_meta_source(
    kind: Literal[CollectionKind.CODE, CollectionKind.VAULT],
) -> Literal[PublicSourceType.CODE, PublicSourceType.VAULT]:
    """Return the public source vocabulary member naming *kind*'s corpus.

    Two vocabularies describe the same corpora: a collection kind names what a
    namespace stores, a public source type names what a caller asked for. Any
    holder of a kind that needs a reader keyed by source has to cross between
    them, and a site crossing inline reads as a place to resolve the sidecar
    inline too - which is how the same path resolution ends up written twice
    and one copy misses the next change.

    The domain is the two kinds publishing an index-metadata sidecar.
    Documents publish a differently shaped record reached through its own
    path, so admitting that kind would buy a runtime rejection where the type
    already says the call cannot be written.
    """
    return (
        PublicSourceType.CODE if kind is CollectionKind.CODE else PublicSourceType.VAULT
    )


class IneligibilityReason(enum.Enum):
    """Why one candidate may not serve as a donor.

    Each member names exactly one failed gate so a test (and a telemetry
    consumer) can bind to the specific rejection rather than a generic "no".
    """

    KIND_MISMATCH = "kind_mismatch"
    STORAGE_SCHEMA_MISMATCH = "storage_schema_mismatch"
    VECTOR_LAYOUT_MISMATCH = "vector_layout_mismatch"
    SCHEMA_UNAVAILABLE = "schema_unavailable"
    MODEL_IDENTITY_MISMATCH = "model_identity_mismatch"
    CONTENT_EPOCH_MISMATCH = "content_epoch_mismatch"
    SIDECAR_UNAVAILABLE = "sidecar_unavailable"


@dataclass(frozen=True, slots=True)
class VectorSchema:
    """Dense dimensionality and named-vector layout of one collection."""

    dense_name: str
    dense_dim: int
    sparse_name: str | None


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """The embedding-model identity the system records today.

    ``dense_model`` and ``sparse_model`` are the configured model names
    (process-global; no per-root record of them exists). ``embed_schema`` is
    the per-root embed-input format marker stamped into the kind's sidecar -
    the only model-adjacent identity persisted per root. Model *revision* is
    not recorded anywhere today, so it cannot be gated on; the dims gate
    catches a revision swap that changes dimensionality, and the per-point
    content verification at the seam bounds the residual risk.
    """

    dense_model: str
    sparse_model: str | None
    embed_schema: str


@dataclass(frozen=True, slots=True)
class DonorRecordedState:
    """What a donor root's sidecar records for one collection kind."""

    content_epoch: str
    embed_schema: str


@dataclass(frozen=True, slots=True)
class DonorCandidate:
    """One manifest-derived donor candidate for a specific collection kind.

    Attributes:
        prefix: The donor namespace's collection prefix (``r{hash}_``).
        root: The donor's recorded root path (may no longer exist).
        backend: ``"server"`` or ``"local"``.
        kind: The collection kind this candidate would donate for.
        collection: The donor's full collection name for ``kind``.
        last_indexed: The manifest's ISO-8601 stamp (empty when never set).
        storage_schema_version: The storage shape generation the donor's
            manifest entry records.
        family_rank: Ranking key - 0 for same-repository-family siblings,
            1 for path-family neighbours, 2 otherwise. Affects consultation
            order only, never eligibility.
    """

    prefix: str
    root: str
    backend: str
    kind: CollectionKind
    collection: str
    last_indexed: str
    storage_schema_version: int
    family_rank: int


@dataclass(frozen=True, slots=True)
class DonorEligibility:
    """Structured eligibility verdict for one candidate."""

    eligible: bool
    reasons: tuple[IneligibilityReason, ...]


def expected_vector_schema() -> VectorSchema:
    """Return the effective vector schema this process writes collections with.

    Reads the effective dense dimension and sparse toggle live from config so
    the expectation always matches what the indexing root's own collection is
    (or will be) built with, never a stale code default.
    """
    from ..config._settings import get_config

    return VectorSchema(
        dense_name=store_schema.DENSE_VECTOR_NAME,
        dense_dim=store_schema.effective_dense_dim(),
        sparse_name=(
            store_schema.SPARSE_VECTOR_NAME
            if bool(get_config().sparse_enabled)
            else None
        ),
    )


def _embed_schema_marker(kind: CollectionKind) -> str:
    """Return the current embed-input format marker for one kind."""
    if kind is CollectionKind.CODE:
        return CODE_EMBED_SCHEMA
    if kind is CollectionKind.VAULT:
        # Mirrors the vault indexer's point-layout version. A skew between
        # this literal and the writer's makes every vault donor ineligible
        # (fail closed) until the two are reconciled.
        return "2"
    return str(DOCUMENT_META_SCHEMA_VERSION)


def current_model_identity(kind: CollectionKind) -> ModelIdentity:
    """Return the recorded-form model identity of the current process."""
    from ..config._settings import get_config

    cfg = get_config()
    return ModelIdentity(
        dense_model=str(cfg.embedding_model),
        sparse_model=str(cfg.sparse_model) if bool(cfg.sparse_enabled) else None,
        embed_schema=_embed_schema_marker(kind),
    )


def _read_json_object(path: Path) -> dict[str, object]:
    """Read one sidecar JSON object; any failure returns an empty mapping."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {key: value for key, value in parsed.items() if isinstance(key, str)}  # pyright: ignore[reportUnknownVariableType]


def read_donor_recorded_state(
    donor_root: Path | str, kind: CollectionKind
) -> DonorRecordedState | None:
    """Read the donor root's sidecar-recorded state for one collection kind.

    Fail closed: a missing root, a missing or unreadable sidecar, a sidecar
    predating the epoch keys, or an incomplete document publication all
    return ``None`` - the caller must treat that candidate as ineligible.
    """
    root = Path(donor_root)
    if kind is CollectionKind.DOCUMENT:
        try:
            meta = read_document_meta(document_metadata_path(root))
        except (DocumentMetadataError, OSError):
            return None
        if meta is None or not meta.complete:
            return None
        return DonorRecordedState(
            content_epoch=meta.content_fingerprint,
            embed_schema=str(meta.meta_schema_version),
        )
    if kind is CollectionKind.CODE:
        epoch_key, marker_key = _CODE_CONTENT_EPOCH_KEY, _CODE_EMBED_SCHEMA_KEY
    else:
        epoch_key, marker_key = VAULT_CONTENT_EPOCH_KEY, VAULT_POINT_SCHEMA_KEY
    raw = _read_json_object(index_meta_path(root, index_meta_source(kind)))
    epoch = raw.get(epoch_key)
    marker = raw.get(marker_key)
    if not isinstance(epoch, str) or not epoch:
        return None
    if not isinstance(marker, str) or not marker:
        return None
    return DonorRecordedState(content_epoch=epoch, embed_schema=marker)


def _git_common_dir(root: Path) -> Path | None:
    """Resolve the git common dir of ``root`` by filesystem inspection only.

    A linked worktree's ``.git`` is a file pointing at the private worktree
    gitdir, whose ``commondir`` file names the shared repository dir. No git
    subprocess is spawned; any unreadable or unrecognised layout returns
    ``None``. Used for ranking only - a wrong or missing answer can never
    make reuse incorrect.
    """
    marker = root / ".git"
    try:
        if marker.is_dir():
            return marker.resolve()
        if not marker.is_file():
            return None
        for line in marker.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("gitdir:"):
                continue
            gitdir = Path(line[len("gitdir:") :].strip())
            if not gitdir.is_absolute():
                gitdir = root / gitdir
            gitdir = gitdir.resolve()
            commondir_file = gitdir / "commondir"
            if commondir_file.is_file():
                common = Path(commondir_file.read_text(encoding="utf-8").strip())
                if not common.is_absolute():
                    common = gitdir / common
                return common.resolve()
            return gitdir
    except OSError:
        return None
    return None


def _family_rank(
    donor_root: Path, target_family: Path | None, target_parent: Path | None
) -> int:
    """Rank a donor's affinity to the indexing root (0 closest, 2 farthest).

    Same git common dir ranks first; a shared parent directory is the
    fallback heuristic when git identity is unavailable on either side.
    Both signals order consultation only and carry no correctness weight.
    """
    donor_family = _git_common_dir(donor_root)
    if (
        target_family is not None
        and donor_family is not None
        and donor_family == target_family
    ):
        return 0
    if target_parent is not None:
        try:
            if donor_root.resolve().parent == target_parent:
                return 1
        except OSError:
            pass
    return 2


def _served_donor_collection(
    root: str | None,
    kind: CollectionKind,
    derived: str,
) -> str:
    """Return the collection a donor root serves for *kind*.

    Falls back to *derived* when the donor's root is unrecorded or its pointer
    cannot be read. That is the safe direction: the derived name is the one the
    donor's namespace declares, so an unreadable pointer consults either real
    data or a collection the store reports as absent - a miss the seam encodes
    normally. Neither outcome invents a collection.
    """
    if kind is not CollectionKind.CODE or not root:
        return derived
    from .._store_models import resolve_served_code_collection

    return resolve_served_code_collection(root, derived)


def discover_donor_candidates(
    root: Path | str,
    kind: CollectionKind,
    *,
    backend: str = "server",
    manifest: Mapping[str, ManifestEntry] | None = None,
    cap: int = DONOR_CANDIDATE_CAP,
) -> list[DonorCandidate]:
    """Discover ranked donor candidates for one indexing root and kind.

    Reads the storage manifest (read-only), excludes the indexing root's own
    prefix, keeps only entries on the requested backend whose recorded
    collection set includes the kind's collection, ranks repository-family
    siblings first (newest ``last_indexed`` first within a rank), and caps
    the result.

    Args:
        root: The root being indexed (the reuse target, never a donor).
        kind: The collection kind vectors would be reused for.
        backend: Donor backend to match; server mode is the primary target,
            and local-mode donors are only meaningful to a caller that
            already holds their in-process store handles.
        manifest: Optional pre-loaded manifest mapping; defaults to loading
            the persisted one.
        cap: Maximum candidates returned; non-positive returns none.

    Returns:
        At most ``cap`` candidates in consultation order.
    """
    from .._store_models import root_collection_prefix
    from ..storage_manifest import load_manifest

    entries = manifest if manifest is not None else load_manifest()
    own_prefix = root_collection_prefix(root)
    root_path = Path(root)
    target_family = _git_common_dir(root_path)
    try:
        target_parent: Path | None = root_path.resolve().parent
    except OSError:
        target_parent = None

    candidates: list[DonorCandidate] = []
    for prefix, entry in entries.items():
        if prefix == own_prefix:
            continue
        if entry.backend != backend:
            continue
        derived = (
            prefix + kind.collection_suffix
            if entry.backend == "server"
            else kind.collection_suffix
        )
        # The manifest declares which kinds a namespace holds, and it declares
        # them under the derived base names only - a published rebuild's
        # ``<derived>_g<generation>`` never appears there. So membership is
        # asked of the derived name, and only then is the donor's own pointer
        # read to learn which collection that kind is actually served from.
        # Asking membership of the served name instead rejects every donor
        # that has ever published a rebuild.
        if derived not in entry.collections:
            continue
        collection = _served_donor_collection(entry.root, kind, derived)
        candidates.append(
            DonorCandidate(
                prefix=prefix,
                root=entry.root,
                backend=entry.backend,
                kind=kind,
                collection=collection,
                last_indexed=entry.last_indexed,
                storage_schema_version=entry.storage_schema_version,
                family_rank=_family_rank(
                    Path(entry.root), target_family, target_parent
                ),
            )
        )
    # Stable multi-pass sort: prefix (determinism), then newest-first within
    # a rank, then family rank as the primary key.
    candidates.sort(key=lambda candidate: candidate.prefix)
    candidates.sort(key=lambda candidate: candidate.last_indexed, reverse=True)
    candidates.sort(key=lambda candidate: candidate.family_rank)
    if cap <= 0:
        return []
    return candidates[:cap]


def evaluate_donor_eligibility(
    candidate: DonorCandidate,
    **options: Unpack[_EligibilityOptions],
) -> DonorEligibility:
    """Apply every eligibility gate to one candidate."""
    return _evaluate_donor_eligibility(_EligibilityRequest(candidate, **options))


def _evaluate_donor_eligibility(request: _EligibilityRequest) -> DonorEligibility:
    """Apply every eligibility gate to one candidate.

    Gates, all of which must pass:

    * the candidate was discovered for the same collection kind;
    * the donor's recorded storage shape generation equals the current one;
    * the donor collection's dense dimensionality and named-vector layout
      equal the expected schema - compared against the actual donor schema
      when ``donor_schema_probe`` is supplied (an unreachable or absent
      collection fails closed), otherwise both sides resolve from the same
      live config and are identical by construction;
    * the donor's recorded embedding-model identity equals the expected one;
    * the donor sidecar's content-epoch sentinel for the kind equals
      ``expected_content_epoch`` (the indexing root's effective epoch,
      computed by the caller).

    A missing or unreadable donor sidecar fails closed as ineligible.

    Args:
        candidate: The discovered candidate under evaluation.
        kind: The collection kind reuse is requested for.
        expected_content_epoch: The indexing root's effective content epoch
            for ``kind``.
        expected_schema: Override of the expected vector schema; defaults to
            the config-effective one.
        donor_schema_probe: Optional callable resolving a collection name to
            its actual stored schema (``None`` when unreachable).
        expected_model: Override of the expected model identity; defaults to
            the current process's recorded-form identity.

    Returns:
        A :class:`DonorEligibility` naming every failed gate.
    """
    (
        candidate,
        kind,
        expected_content_epoch,
        expected_schema,
        donor_schema_probe,
        expected_model,
    ) = (
        request.candidate,
        request.kind,
        request.expected_content_epoch,
        request.expected_schema,
        request.donor_schema_probe,
        request.expected_model,
    )
    reasons: list[IneligibilityReason] = []
    if candidate.kind is not kind:
        reasons.append(IneligibilityReason.KIND_MISMATCH)
    if candidate.storage_schema_version != store_schema.STORAGE_SCHEMA_VERSION:
        reasons.append(IneligibilityReason.STORAGE_SCHEMA_MISMATCH)
    schema = (
        expected_schema if expected_schema is not None else expected_vector_schema()
    )
    if donor_schema_probe is not None:
        donor_schema = donor_schema_probe(candidate.collection)
        if donor_schema is None:
            reasons.append(IneligibilityReason.SCHEMA_UNAVAILABLE)
        elif donor_schema != schema:
            reasons.append(IneligibilityReason.VECTOR_LAYOUT_MISMATCH)
    model = (
        expected_model if expected_model is not None else current_model_identity(kind)
    )
    state = read_donor_recorded_state(candidate.root, kind)
    if state is None:
        reasons.append(IneligibilityReason.SIDECAR_UNAVAILABLE)
    else:
        # The embed-input format marker is the only model-adjacent identity
        # persisted per root, so it is what the recorded-identity comparison
        # can honestly gate on. The configured model names in ``model`` are
        # process-global (both sides resolve them from the same live config),
        # and no model revision is recorded anywhere - a same-dimensionality
        # model swap is bounded by the per-point content verification at the
        # seam, not by this gate.
        if state.embed_schema != model.embed_schema:
            reasons.append(IneligibilityReason.MODEL_IDENTITY_MISMATCH)
        if state.content_epoch != expected_content_epoch:
            reasons.append(IneligibilityReason.CONTENT_EPOCH_MISMATCH)
    return DonorEligibility(eligible=not reasons, reasons=tuple(reasons))
