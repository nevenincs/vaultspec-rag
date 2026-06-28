"""Single source of truth for the vaultspec-rag Qdrant storage schema.

The Qdrant data shape - the collection names, the dense/sparse vector layout,
the per-point payload fields, the payload index set, and the point-ID scheme -
is a contract that out-of-process consumers (notably the dashboard engine's
direct-Qdrant embedding read) depend on. This module is the one place that
shape is defined: the version, the vector constants, the typed payloads, the
index tuples, the effective wire descriptor, and the consumer compatibility
helper. Every ``upsert``/``ensure`` call site in ``store.py`` builds its payload
and index set from here rather than from inline literals, so the shape cannot
drift between the writer, the reader, the wire, and the reference.

It is a **neutral torch-free leaf**: it depends only on the config (read lazily
inside :func:`describe_storage_schema`), never imports torch or the embedding
model, and is importable by both ``store.py`` and the server routes with no
``store`` <-> ``server`` cycle. Keeping it torch-free is what lets the
process-wide ``/readiness`` report advertise the descriptor without loading a
model or touching the GPU.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, cast

__all__ = [
    "CODE_COLLECTION",
    "CODE_INTEGER_INDEXES",
    "CODE_KEYWORD_INDEXES",
    "DEFAULT_DENSE_DIM",
    "DENSE_DISTANCE",
    "DENSE_VECTOR_NAME",
    "SPARSE_VECTOR_NAME",
    "STORAGE_SCHEMA_VERSION",
    "VAULT_COLLECTION",
    "VAULT_INTEGER_INDEXES",
    "VAULT_KEYWORD_INDEXES",
    "CodeChunkPayload",
    "SchemaCompatibility",
    "VaultChunkPayload",
    "VaultDocPayload",
    "assert_compatible",
    "describe_storage_schema",
    "effective_dense_dim",
]

# Version of the on-disk Qdrant shape. Bump ONLY on a breaking change: a vector
# rename or dimension/distance change, a payload field removal/rename/type
# change, an index-set change that alters query semantics, or an ID-scheme
# change. Additive payload fields are non-breaking and do NOT bump - a consumer
# that does not know a new field ignores it. The version names the shape
# generation; the effective concrete values (dimension, models) are read live
# in describe_storage_schema because they are config-derivable.
STORAGE_SCHEMA_VERSION = 1

# Collection names. These are the bare local-mode names; in server mode each
# root's collections gain a stable per-root ``r{hash}_`` prefix, so a consumer
# matches on the suffix, not the whole name.
VAULT_COLLECTION = "vault_docs"
CODE_COLLECTION = "codebase_docs"

# Vector layout. One named dense vector (cosine) and one named sparse vector.
# A consumer scrolls the dense vector by DENSE_VECTOR_NAME; a rename here is a
# breaking change that bumps STORAGE_SCHEMA_VERSION.
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
# The qdrant ``Distance`` member name for the dense vector (string form so this
# leaf never imports qdrant_client). store.py maps it to ``models.Distance``.
DENSE_DISTANCE = "Cosine"
# Default dense dimension (Qwen3-Embedding-0.6B). This is the DEFAULT; the
# EFFECTIVE dimension is read from config in describe_storage_schema because an
# operator may override ``embedding_dimension`` or swap the model.
DEFAULT_DENSE_DIM = 1024

# Point-ID schemes, named for the reference and the consumer recipe (documented,
# not enforced here): a vault document keys on its stem (relative path without
# extension), a vault chunk on ``{doc_id}#c{ordinal}``, a code chunk on its
# chunk id. All three are hashed to the stable Qdrant point id by store.py.
VAULT_DOC_ID_SCHEME = "doc_id"
VAULT_CHUNK_ID_SCHEME = "doc_id#c{ordinal}"
CODE_CHUNK_ID_SCHEME = "chunk_id"


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


# Canonical payload index sets, per collection and qdrant schema type. store.py's
# ``ensure_table`` / ``ensure_code_table`` create exactly these indexes; the
# drift test asserts the live collection's indexed fields equal these tuples.
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
)
CODE_INTEGER_INDEXES: tuple[str, ...] = ("line_start", "locator_value_int")

# Payload field names per collection, derived once from the TypedDicts so the
# descriptor and the drift test share one source. ``__optional_keys__`` carries
# the NotRequired members (``doc_content``), which still belong to the contract.
_VAULT_DOC_FIELDS: tuple[str, ...] = tuple(VaultDocPayload.__annotations__)
_VAULT_CHUNK_FIELDS: tuple[str, ...] = tuple(VaultChunkPayload.__annotations__)
_CODE_CHUNK_FIELDS: tuple[str, ...] = tuple(CodeChunkPayload.__annotations__)


def _effective_models() -> dict[str, Any]:
    """Read the effective model identity from config (no model load)."""
    from .config import get_config

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
    from .config import get_config

    cfg = get_config()
    try:
        dim = int(cfg.embedding_dimension)
    except (TypeError, ValueError):
        return DEFAULT_DENSE_DIM
    return dim if dim > 0 else DEFAULT_DENSE_DIM


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
    # The dense vector descriptor lives under either collection; they share the
    # same dense vector, so the vault block is the canonical place to read it.
    vault_block = _as_str_dict(descriptor.get("vault"))
    vectors = _as_str_dict(vault_block.get("vectors"))
    dense = _as_str_dict(vectors.get("dense"))
    if dense.get("name") != dense_vector_name:
        return {
            "compatible": False,
            "reason": f"no dense vector named {dense_vector_name!r} in the descriptor",
        }
    actual_dim = dense.get("dim")
    if actual_dim != expected_dense_dim:
        return {
            "compatible": False,
            "reason": (
                f"dense dimension {actual_dim} does not match the consumer's "
                f"expected {expected_dense_dim}"
            ),
        }
    return {"compatible": True, "reason": ""}
