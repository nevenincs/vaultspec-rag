"""Single source of truth for the vaultspec-rag Qdrant storage schema.

The Qdrant data shape - the collection names, the dense/sparse vector layout,
the per-point payload fields, the payload index set, and the point-ID scheme -
is a contract that out-of-process consumers (notably the dashboard engine's
direct-Qdrant embedding read) depend on. This module is the one place that
shape is defined: the version, the vector constants, the typed payloads, the
index tuples, the effective wire descriptor, and the consumer compatibility
helper. Every ``upsert``/``ensure`` call site in ``store_ingest.py`` builds its payload
and index set from here rather than from inline literals, so the shape cannot
drift between the writer, the reader, the wire, and the reference.

It is a **neutral torch-free leaf**: it depends only on the config (read lazily
inside :func:`describe_storage_schema`), never imports torch or the embedding
model, and is importable by both ``store_runtime.py`` and the server routes with no
``store`` <-> ``server`` cycle. Keeping it torch-free is what lets the
process-wide ``/readiness`` report advertise the descriptor without loading a
model or touching the GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

__all__ = [
    "CODE_COLLECTION",
    "CODE_FILTER_KEYS",
    "CODE_INTEGER_INDEXES",
    "CODE_KEYWORD_INDEXES",
    "DEFAULT_DENSE_DIM",
    "DENSE_DISTANCE",
    "DENSE_VECTOR_NAME",
    "DOCUMENT_COLLECTION",
    "DOCUMENT_FILTER_KEYS",
    "DOCUMENT_INTEGER_INDEXES",
    "DOCUMENT_KEYWORD_INDEXES",
    "DOCUMENT_QUERY_FILTER_KEYS",
    "SERVER_SEGMENT_NUMBER",
    "SERVER_WAL_CAPACITY_MB",
    "SPARSE_VECTOR_NAME",
    "STORAGE_SCHEMA_VERSION",
    "VAULT_COLLECTION",
    "VAULT_FILTER_KEYS",
    "VAULT_INTEGER_INDEXES",
    "VAULT_KEYWORD_INDEXES",
    "CodeChunkPayload",
    "CollectionIdentity",
    "ConformanceVerdict",
    "DocumentChunkPayload",
    "SchemaCompatibility",
    "VaultChunkPayload",
    "VaultDocPayload",
    "assert_compatible",
    "collection_names",
    "current_identity",
    "describe_storage_schema",
    "effective_dense_dim",
    "evaluate_conformance",
]

# Version of the on-disk Qdrant shape. Bump ONLY on a breaking change: a vector
# rename or dimension/distance change, a payload field removal/rename/type
# change, an index-set change that alters query semantics, or an ID-scheme
# change. Additive payload fields are non-breaking and do NOT bump - a consumer
# that does not know a new field ignores it. The version names the shape
# generation; the effective concrete values (dimension, models) are read live
# in describe_storage_schema because they are config-derivable.
STORAGE_SCHEMA_VERSION = 2

# Collection names. These are the bare local-mode names; in server mode each
# root's collections gain a stable per-root ``r{hash}_`` prefix, so a consumer
# matches on the suffix, not the whole name.
VAULT_COLLECTION = "vault_docs"
CODE_COLLECTION = "codebase_docs"
DOCUMENT_COLLECTION = "document_docs"

# Vector layout. One named dense vector (cosine) and one named sparse vector.
# A consumer scrolls the dense vector by DENSE_VECTOR_NAME; a rename here is a
# breaking change that bumps STORAGE_SCHEMA_VERSION.
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
# The qdrant ``Distance`` member name for the dense vector (string form so this
# leaf never imports qdrant_client). The collection owner maps it to
# ``models.Distance``.
DENSE_DISTANCE = "Cosine"
# Default dense dimension (Qwen3-Embedding-0.6B). This is the DEFAULT; the
# EFFECTIVE dimension is read from config in describe_storage_schema because an
# operator may override ``embedding_dimension`` or swap the model.
DEFAULT_DENSE_DIM = 1024

# Bounded per-collection geometry (server mode only; local mode preallocates
# nothing). Server defaults derive the segment count from host CPU count, and
# every segment preallocates a 32 MiB payload page, a 32 MiB sparse page, and a
# page set per indexed payload field - so on a 24-core host an EMPTY namespace
# cost 1243.8 MiB measured against the pinned 1.18.2. Seeding two segments and
# capping the WAL segment brings that to ~327 MiB while keeping ingest and
# intra-collection search headroom; the optimizer still grows segments with real
# data. Declared here rather than at the create call site because the storage
# domain reconciles pre-existing collections toward the same target, and the two
# must not drift apart.
SERVER_WAL_CAPACITY_MB = 16
SERVER_SEGMENT_NUMBER = 2

# Point-ID schemes, named for the reference and the consumer recipe (documented,
# not enforced here): a vault document keys on its stem (relative path without
# extension), a vault chunk on ``{doc_id}#c{ordinal}``, a code chunk on its
# chunk id. All three are hashed to the stable Qdrant point id by store_ingest.py.
VAULT_DOC_ID_SCHEME = "doc_id"
VAULT_CHUNK_ID_SCHEME = "doc_id#c{ordinal}"
CODE_CHUNK_ID_SCHEME = "chunk_id"
DOCUMENT_CHUNK_ID_SCHEME = (
    "blake2b(normalized_source|locator_or_unit_ordinal|content_fingerprint)@v1"
)


def collection_names(prefix: str = "") -> tuple[str, str, str]:
    """Return every collection in stable lifecycle order for one namespace."""
    return (
        prefix + VAULT_COLLECTION,
        prefix + CODE_COLLECTION,
        prefix + DOCUMENT_COLLECTION,
    )


class VaultDocPayload(TypedDict):
    """Payload of a ``vault_docs`` document-level point.

    The doc-level point carries the full body in ``content`` and the parent
    metadata used by the search filters. Field names ARE the contract: a
    rename or removal is a breaking change; an additive field is not.
    """

    doc_id: str
    path: str
    doc_type: str
    feature: str
    date: str
    tags: list[str]
    related: list[str]
    title: str
    status: str
    content: str


class VaultChunkPayload(TypedDict):
    """Payload of a ``vault_docs`` chunk-level point.

    The parent document's metadata is flattened onto every chunk so filters
    work unchanged; ``doc_id`` groups chunks back into documents. ``doc_content``
    travels only on the ordinal-0 chunk, so it is ``NotRequired``.
    """

    doc_id: str
    chunk_ordinal: int
    chunk_count: int
    path: str
    doc_type: str
    feature: str
    date: str
    tags: list[str]
    related: list[str]
    title: str
    status: str
    content: str
    doc_content: NotRequired[str]


class CodeChunkPayload(TypedDict):
    """Payload of a ``codebase_docs`` chunk-level point.

    The document-preprocessing hook fields (``source_path`` through
    ``locator_end_str``) are ``None`` for ordinary code chunks; they carry a
    deep-link into a preprocessed source's own addressing scheme when present.
    """

    chunk_id: str
    path: str
    language: str
    content: str
    line_start: int
    line_end: int
    node_type: str | None
    function_name: str | None
    class_name: str | None
    source_path: str | None
    preprocessor_id: str | None
    anchor: str | None
    locator_kind: str | None
    locator_value_int: int | None
    locator_value_str: str | None
    locator_end_int: int | None
    locator_end_str: str | None
    domain: str


class DocumentChunkPayload(TypedDict):
    """Payload of one independently owned document chunk."""

    document_id: str
    source_path: str
    unit_ordinal: int
    content_fingerprint: str
    content: str
    title: str | None
    section: str | None
    anchor: str | None
    locator_kind: str | None
    locator_value_int: int | None
    locator_value_str: str | None
    locator_end_int: int | None
    locator_end_str: str | None
    document_metadata: dict[str, object]
    unit_metadata: dict[str, object]
    extractor_id: str | None
    extractor_version: str | None


# Canonical payload index sets, per collection and qdrant schema type. The
# collection owner's ``ensure_table`` / ``ensure_code_table`` create exactly
# these indexes; the drift test asserts the live collection's indexed fields
# equal these tuples.
# A change to an index set that alters query semantics bumps the version.
VAULT_KEYWORD_INDEXES: tuple[str, ...] = (
    "doc_type",
    "feature",
    "date",
    "tags",
    "doc_id",
)
VAULT_INTEGER_INDEXES: tuple[str, ...] = ("chunk_ordinal",)
CODE_KEYWORD_INDEXES: tuple[str, ...] = (
    "path",
    "language",
    "function_name",
    "class_name",
    "node_type",
    "preprocessor_id",
    "locator_kind",
    "locator_value_str",
    "domain",
)
CODE_INTEGER_INDEXES: tuple[str, ...] = ("line_start", "locator_value_int")
DOCUMENT_KEYWORD_INDEXES: tuple[str, ...] = (
    "source_path",
    "content_fingerprint",
    "extractor_id",
    "extractor_version",
    "locator_kind",
    "locator_value_str",
)
DOCUMENT_INTEGER_INDEXES: tuple[str, ...] = (
    "unit_ordinal",
    "locator_value_int",
)

# The payload keys a caller may filter a search on, per collection. Declared
# here beside the index sets because the two are a pair: a filter key with no
# index behind it is either a full scan or silently unsupported, and the guard
# over these tuples is what makes that pairing checkable.
#
# Deliberately a SUBSET of the index sets rather than equal to them. A code
# search indexes `domain`, `locator_kind` and `locator_value_str` too, but
# those reach the query through their own dedicated handling rather than as
# raw filter keys, so admitting them here would give one concept two entry
# points that disagree.
#
# The document filter learned first why this belongs in one place: it used to
# re-list its keys, so a keyword index added to the schema was rejected as
# unknown and the filter was dropped, returning UNFILTERED results to a caller
# who had asked to narrow. Re-listing is the defect, wherever it happens.
CODE_FILTER_KEYS: tuple[str, ...] = (
    "language",
    "path",
    "node_type",
    "function_name",
    "class_name",
)
VAULT_FILTER_KEYS: tuple[str, ...] = ("doc_type", "feature", "date", "tag")
DOCUMENT_FILTER_KEYS: tuple[str, ...] = (
    "source_path",
    "extractor_id",
    "extractor_version",
    "locator_kind",
)

#: Document keys accepted as inline query tokens and forwarded to the store.
#: A superset of :data:`DOCUMENT_FILTER_KEYS`: ``locator_value_str`` is
#: indexed and filterable but has no explicit search argument, so it can only
#: arrive in the query text. The two sets answer different questions - which
#: arguments a caller passed, and which keys may reach the store - and the
#: guard pins the containment between them rather than letting one drift into
#: standing for both.
DOCUMENT_QUERY_FILTER_KEYS: tuple[str, ...] = (
    *DOCUMENT_FILTER_KEYS,
    "locator_value_str",
)

#: Filter keys whose payload field is spelled differently. ``tag`` filters one
#: value against the ``tags`` list, so the caller's singular and the payload's
#: plural are both correct and the translation is recorded rather than assumed.
FILTER_KEY_PAYLOAD_FIELD: dict[str, str] = {"tag": "tags"}

# Payload field names per collection, derived once from the TypedDicts so the
# descriptor and the drift test share one source. ``__optional_keys__`` carries
# the NotRequired members (``doc_content``), which still belong to the contract.
_VAULT_DOC_FIELDS: tuple[str, ...] = tuple(VaultDocPayload.__annotations__)
_VAULT_CHUNK_FIELDS: tuple[str, ...] = tuple(VaultChunkPayload.__annotations__)
_CODE_CHUNK_FIELDS: tuple[str, ...] = tuple(CodeChunkPayload.__annotations__)
_DOCUMENT_CHUNK_FIELDS: tuple[str, ...] = tuple(DocumentChunkPayload.__annotations__)


def _effective_models() -> dict[str, Any]:
    """Read the effective model identity from config (no model load)."""
    from .config._settings import get_config

    cfg = get_config()
    return {
        "dense": str(cfg.embedding_model),
        "sparse": str(cfg.sparse_model) if bool(cfg.sparse_enabled) else None,
    }


def effective_dense_dim() -> int:
    """Resolve the effective dense dimension from config (default the constant).

    The single source of the dense dimension: both the wire descriptor and the
    store's collection creation read it here, so the advertised dimension always
    equals the one the live collection is built with - never the constant under
    a config override.
    """
    from .config._settings import get_config

    cfg = get_config()
    try:
        dim = int(cfg.embedding_dimension)
    except (TypeError, ValueError):
        return DEFAULT_DENSE_DIM
    return dim if dim > 0 else DEFAULT_DENSE_DIM


def effective_sparse_dim(model: object) -> int:
    """Resolve the sparse width a run will write, or ``1`` when sparse is off.

    The counterpart to :func:`effective_dense_dim`, and here for the same
    reason: the width a collection is built with must come from one place. The
    code and document indexers each resolved it inline, in blocks that were
    identical down to the strict ``type(...) is not int`` test, so a rule
    change would have had to be made twice in two files that never import each
    other.

    Args:
        model: The loaded embedding model, asked for ``sparse_dimension``.

    Returns:
        The model's sparse width, or ``1`` when sparse vectors are disabled -
        the placeholder width a collection still needs a number for.

    Raises:
        RuntimeError: When sparse is enabled and the loaded model reports no
            usable width. ``type(...) is not int`` rather than ``isinstance``
            on purpose: ``bool`` is an ``int`` subclass, and a model reporting
            ``True`` would otherwise be read as a width of one and produce a
            collection that accepts exactly one sparse term.
    """
    from .config._settings import get_config

    if not bool(get_config().sparse_enabled):
        return 1
    value = getattr(model, "sparse_dimension", None)
    if type(value) is not int or value <= 0:
        raise RuntimeError("loaded sparse model has no valid output dimension")
    return value


def describe_storage_schema() -> dict[str, Any]:
    """Build the bounded wire descriptor a consumer asserts compatibility against.

    Pairs the static :data:`STORAGE_SCHEMA_VERSION` (the shape generation) with
    the EFFECTIVE concrete values read live from config (dense dimension, model
    identity), because those are config-derivable and a consumer validating a
    direct scroll needs the real dimension, not the code default. Loads no model
    and touches no GPU, so it is safe on the torch-free ``/readiness`` path.

    Returns:
        A JSON-serialisable dict: ``{version, vault:{collection, vectors,
        payload_fields, indexes, id_scheme}, code:{...}, models:{dense, sparse}}``.
    """
    dense_dim = effective_dense_dim()

    def _vectors() -> dict[str, Any]:
        # A fresh dict per collection block so a caller mutating one collection's
        # vector view never aliases the other's.
        return {
            "dense": {
                "name": DENSE_VECTOR_NAME,
                "dim": dense_dim,
                "distance": DENSE_DISTANCE,
            },
            "sparse": {"name": SPARSE_VECTOR_NAME},
        }

    return {
        "version": STORAGE_SCHEMA_VERSION,
        "vault": {
            "collection": VAULT_COLLECTION,
            "vectors": _vectors(),
            "payload_fields": {
                "document": list(_VAULT_DOC_FIELDS),
                "chunk": list(_VAULT_CHUNK_FIELDS),
            },
            "indexes": {
                "keyword": list(VAULT_KEYWORD_INDEXES),
                "integer": list(VAULT_INTEGER_INDEXES),
            },
            "id_scheme": {
                "document": VAULT_DOC_ID_SCHEME,
                "chunk": VAULT_CHUNK_ID_SCHEME,
            },
        },
        "code": {
            "collection": CODE_COLLECTION,
            "vectors": _vectors(),
            "payload_fields": {"chunk": list(_CODE_CHUNK_FIELDS)},
            "indexes": {
                "keyword": list(CODE_KEYWORD_INDEXES),
                "integer": list(CODE_INTEGER_INDEXES),
            },
            "id_scheme": {"chunk": CODE_CHUNK_ID_SCHEME},
        },
        "document": {
            "collection": DOCUMENT_COLLECTION,
            "vectors": _vectors(),
            "payload_fields": {"chunk": list(_DOCUMENT_CHUNK_FIELDS)},
            "indexes": {
                "keyword": list(DOCUMENT_KEYWORD_INDEXES),
                "integer": list(DOCUMENT_INTEGER_INDEXES),
            },
            "id_scheme": {"chunk": DOCUMENT_CHUNK_ID_SCHEME},
        },
        "models": _effective_models(),
    }


class SchemaCompatibility(TypedDict):
    """Verdict of :func:`assert_compatible`.

    ``compatible`` is the single read-or-refuse signal; ``reason`` carries the
    human-readable cause for a degrade or refuse (empty when compatible).
    """

    compatible: bool
    reason: str


def _as_str_dict(value: object) -> dict[str, Any]:
    """Narrow an untyped descriptor value to a string-keyed dict (empty if not).

    A consumer descriptor arrives as ``dict[str, Any]`` (or its JSON form), so
    each nested access is untyped; this narrows one level safely so the
    compatibility checks read typed values rather than ``Unknown``.
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


def assert_compatible(
    descriptor: dict[str, Any],
    *,
    known_version: int,
    expected_dense_dim: int,
    dense_vector_name: str = DENSE_VECTOR_NAME,
    required_domains: tuple[str, ...] = ("vault",),
) -> SchemaCompatibility:
    """Apply the consumer compatibility rules to a storage descriptor.

    The Python-side reference implementation of the contract an out-of-process
    consumer (the dashboard's Rust engine) applies before a direct Qdrant
    scroll. The rules, in order:

    - The descriptor's ``version`` must not EXCEED ``known_version``. A newer
      shape may have changed beyond what the consumer can parse, so it degrades
      rather than reading blind. An older or equal version is compatible
      (additive fields the consumer ignores).
    - The effective dense ``dim`` must EQUAL ``expected_dense_dim``. A mismatch
      is a hard refuse, not a degrade: wrong-size vectors are garbage.
    - A dense vector named ``dense_vector_name`` must EXIST in the descriptor.

    Args:
        descriptor: A :func:`describe_storage_schema` payload (or its JSON form).
        known_version: The newest ``STORAGE_SCHEMA_VERSION`` the consumer was
            built against.
        expected_dense_dim: The dense dimension the consumer will deserialize.
        dense_vector_name: The dense vector name the consumer scrolls by.

    Returns:
        A :class:`SchemaCompatibility` verdict.
    """
    version = descriptor.get("version")
    if not isinstance(version, int):
        return {"compatible": False, "reason": "descriptor carries no integer version"}
    if version > known_version:
        return {
            "compatible": False,
            "reason": (
                f"storage schema version {version} is newer than the consumer's "
                f"known version {known_version}; the shape may have changed"
            ),
        }
    known_domains = frozenset({"vault", "code", "document"})
    unknown = tuple(
        domain for domain in required_domains if domain not in known_domains
    )
    if unknown:
        return {
            "compatible": False,
            "reason": f"unknown required storage domain {unknown[0]!r}",
        }
    for domain in required_domains:
        reason = _domain_compatibility_reason(
            descriptor,
            domain=domain,
            dense_vector_name=dense_vector_name,
            expected_dense_dim=expected_dense_dim,
        )
        if reason is not None:
            return {
                "compatible": False,
                "reason": reason,
            }
    return {"compatible": True, "reason": ""}


def _domain_compatibility_reason(
    descriptor: dict[str, Any],
    *,
    domain: str,
    dense_vector_name: str,
    expected_dense_dim: int,
) -> str | None:
    """Return one domain's first incompatible storage shape, if any."""
    block = _as_str_dict(descriptor.get(domain))
    if not block:
        return f"descriptor carries no {domain!r} storage domain"
    vectors = _as_str_dict(block.get("vectors"))
    dense = _as_str_dict(vectors.get("dense"))
    if dense.get("name") != dense_vector_name:
        return (
            f"no dense vector named {dense_vector_name!r} in the "
            f"{domain!r} storage domain"
        )
    actual_dim = dense.get("dim")
    if actual_dim != expected_dense_dim:
        return (
            f"{domain!r} dense dimension {actual_dim} does not match "
            f"the consumer's expected {expected_dense_dim}"
        )
    return None


# Conformance verdicts. Three, not two: the absence of evidence is its own
# answer. A namespace written before identity was stamped cannot be scored as
# passing (that reintroduces the silent mismatch this record exists to remove)
# nor as failing (that degrades every host on first upgrade), so it is reported
# as the unknown it is and is never grounds to refuse a read or to destroy data.
CONFORMING = "conforming"
NONCONFORMING = "nonconforming"
UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class CollectionIdentity:
    """What actually produced one collection's vectors.

    The fact the descriptor cannot supply. ``describe_storage_schema`` reads the
    effective model and width from live config, so it reports what this process
    is configured with and never what the stored vectors were built with -
    comparing it against the config it came from always succeeds. This record is
    stamped once, at collection-create, and is the only durable statement of
    provenance a later reader can compare against.

    ``sparse_model`` is ``None`` when sparse was disabled at create time, which
    is a real difference from a collection built with sparse enabled and must
    not be conflated with an absent record.
    """

    dense_model: str
    sparse_model: str | None
    dense_dim: int
    distance: str
    dense_vector_name: str
    sparse_vector_name: str
    storage_schema_version: int

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable form persisted in either home."""
        return {
            "dense_model": self.dense_model,
            "sparse_model": self.sparse_model,
            "dense_dim": self.dense_dim,
            "distance": self.distance,
            "dense_vector_name": self.dense_vector_name,
            "sparse_vector_name": self.sparse_vector_name,
            "storage_schema_version": self.storage_schema_version,
        }

    @classmethod
    def from_payload(cls, payload: object) -> CollectionIdentity | None:
        """Rebuild from a persisted payload, or ``None`` if it is unusable.

        Returns ``None`` rather than raising or substituting defaults: a
        malformed record is missing evidence, and the caller's correct response
        is ``unverifiable``. Defaulting any field here would manufacture the
        provenance this type exists to prove.
        """
        if not isinstance(payload, dict):
            return None
        raw = cast("dict[str, Any]", payload)
        dense_model = raw.get("dense_model")
        dense_dim = raw.get("dense_dim")
        if not isinstance(dense_model, str) or not dense_model:
            return None
        if not isinstance(dense_dim, int) or isinstance(dense_dim, bool):
            return None
        sparse_model = raw.get("sparse_model")
        if sparse_model is not None and not isinstance(sparse_model, str):
            return None
        version = raw.get("storage_schema_version")
        if not isinstance(version, int) or isinstance(version, bool):
            return None
        return cls(
            dense_model=dense_model,
            sparse_model=sparse_model,
            dense_dim=dense_dim,
            distance=str(raw.get("distance", DENSE_DISTANCE)),
            dense_vector_name=str(raw.get("dense_vector_name", DENSE_VECTOR_NAME)),
            sparse_vector_name=str(raw.get("sparse_vector_name", SPARSE_VECTOR_NAME)),
            storage_schema_version=version,
        )


def current_identity() -> CollectionIdentity:
    """Build the identity this process would stamp on a collection it creates.

    Reads the effective model names and dense width from config the same way
    the descriptor does, so a collection's stamp always matches the process that
    actually wrote its vectors rather than the module defaults.
    """
    models = _effective_models()
    sparse = models["sparse"]
    return CollectionIdentity(
        dense_model=str(models["dense"]),
        sparse_model=str(sparse) if sparse is not None else None,
        dense_dim=effective_dense_dim(),
        distance=DENSE_DISTANCE,
        dense_vector_name=DENSE_VECTOR_NAME,
        sparse_vector_name=SPARSE_VECTOR_NAME,
        storage_schema_version=STORAGE_SCHEMA_VERSION,
    )


@dataclass(frozen=True)
class ConformanceVerdict:
    """Whether a collection may be trusted, and why.

    ``geometry_fatal`` separates the two failure modes that share the
    ``nonconforming`` verdict. A width, distance, or vector-name disagreement
    makes the stored vectors unscorable, so the caller refuses. A model
    disagreement at matching geometry leaves the collection readable and merely
    meaningless to rank by, so the caller degrades and lets a rebuild fix it -
    refusing there would remove search for the duration of the rebuild that is
    the remedy.
    """

    verdict: str
    reason: str
    geometry_fatal: bool = False

    @property
    def is_conforming(self) -> bool:
        """Whether the collection matched on every compared field."""
        return self.verdict == CONFORMING


def _identity_descriptor(identity: CollectionIdentity) -> dict[str, Any]:
    """Shape one identity as a descriptor ``assert_compatible`` can judge."""
    return {
        "version": identity.storage_schema_version,
        "vault": {
            "vectors": {
                "dense": {
                    "name": identity.dense_vector_name,
                    "dim": identity.dense_dim,
                    "distance": identity.distance,
                },
                "sparse": {"name": identity.sparse_vector_name},
            },
        },
    }


def evaluate_conformance(
    stamped: CollectionIdentity | None,
    *,
    expected: CollectionIdentity,
    live_dense_dim: int | None,
) -> ConformanceVerdict:
    """Judge one collection against the identity the running code expects.

    Routes the version, dense-width, and vector-name rules through
    :func:`assert_compatible` rather than restating them, so the two callers
    cannot drift apart. The model comparison is this function's own, because it
    is the fact the descriptor could never carry.

    Args:
        stamped: The identity recorded when the collection was created, or
            ``None`` when the collection predates stamping.
        expected: What this process would stamp today - see
            :func:`current_identity`.
        live_dense_dim: The dense width read back from the live collection, or
            ``None`` when it could not be read.

    Returns:
        A :class:`ConformanceVerdict`.
    """
    if stamped is None:
        return ConformanceVerdict(
            UNVERIFIABLE,
            "the collection carries no stamped identity, so what produced its "
            "vectors cannot be established",
        )
    if live_dense_dim is None:
        return ConformanceVerdict(
            UNVERIFIABLE,
            "the live collection geometry could not be read, so the stamped "
            "identity could not be confirmed against it",
        )

    geometry = _geometry_conformance(
        stamped,
        expected=expected,
        live_dense_dim=live_dense_dim,
    )
    if geometry is not None:
        return geometry
    return _model_conformance(stamped, expected=expected)


def _geometry_conformance(
    stamped: CollectionIdentity,
    *,
    expected: CollectionIdentity,
    live_dense_dim: int,
) -> ConformanceVerdict | None:
    """Return the first fatal vector-geometry disagreement, if any."""
    compatibility = assert_compatible(
        _identity_descriptor(stamped),
        known_version=expected.storage_schema_version,
        expected_dense_dim=expected.dense_dim,
        dense_vector_name=expected.dense_vector_name,
    )
    if not compatibility["compatible"]:
        return ConformanceVerdict(
            NONCONFORMING, compatibility["reason"], geometry_fatal=True
        )
    if live_dense_dim != expected.dense_dim:
        return ConformanceVerdict(
            NONCONFORMING,
            f"the live collection's dense width {live_dense_dim} does not match "
            f"the configured {expected.dense_dim}",
            geometry_fatal=True,
        )
    if stamped.distance != expected.distance:
        return ConformanceVerdict(
            NONCONFORMING,
            f"the collection was built with {stamped.distance} distance but "
            f"{expected.distance} is configured",
            geometry_fatal=True,
        )
    return None


def _model_conformance(
    stamped: CollectionIdentity,
    *,
    expected: CollectionIdentity,
) -> ConformanceVerdict:
    """Judge provenance after geometry has established readable vectors."""
    if stamped.dense_model != expected.dense_model:
        return ConformanceVerdict(
            NONCONFORMING,
            f"the collection's vectors were produced by {stamped.dense_model} "
            f"but {expected.dense_model} is configured; equal width makes the "
            "mismatch invisible to scoring, so ranking is meaningless until a "
            "rebuild",
        )
    if stamped.sparse_model != expected.sparse_model:
        return ConformanceVerdict(
            NONCONFORMING,
            f"the collection's sparse vectors were produced by "
            f"{stamped.sparse_model or 'no sparse model'} but "
            f"{expected.sparse_model or 'no sparse model'} is configured",
        )
    return ConformanceVerdict(CONFORMING, "")
