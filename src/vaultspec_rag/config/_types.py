"""Configuration vocabulary and value objects."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Literal, NamedTuple

from vaultspec_core.env_values import parse_bool

PreprocessMode = Literal["default", "off"]

VALID_PREPROCESS_MODES: frozenset[str] = frozenset({"default", "off"})
VALID_INDEX_SUPPORT_PROFILES: frozenset[str] = frozenset(
    {"managed-service", "embedded-local"}
)


class EnvVar(StrEnum):
    """Recognized environment variables for vaultspec-rag.

    Each member's value is the full env var name.  This enum is the
    single source of truth - no other module should use bare string
    literals when reading or writing env vars for RAG configuration.

    One admission rule applies: a name earns a member by being read or set
    by this codebase outside its tests. A name nobody here touches
    configures nothing this project can vouch for, and declaring one
    advertises a knob that does not exist - whether the name is this
    project's own or belongs to a library it depends on. A third-party
    variable the code never touches is the library's to document.
    """

    RAG_ROOT = "VAULTSPEC_RAG_ROOT"
    DATA_DIR = "VAULTSPEC_RAG_DATA_DIR"
    QDRANT_DIR = "VAULTSPEC_RAG_QDRANT_DIR"
    STATUS_DIR = "VAULTSPEC_RAG_STATUS_DIR"
    LOG_FILE = "VAULTSPEC_RAG_LOG_FILE"
    PORT = "VAULTSPEC_RAG_PORT"
    MONITOR_BINARY = "VAULTSPEC_RAG_MONITOR_BINARY"
    MONITOR_PYTHON = "VAULTSPEC_RAG_MONITOR_PYTHON"
    LOG_LEVEL = "VAULTSPEC_RAG_LOG_LEVEL"
    SERVICE_IDLE_TTL_SECONDS = "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS"
    SERVICE_MAX_PROJECTS = "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS"
    # Client-side request bounds. Registered here so this enum stays the one
    # authoritative list of settings; the thin client parses them leniently
    # and falls back to the shipped default rather than raising.
    SERVICE_SEARCH_TIMEOUT = "VAULTSPEC_RAG_SEARCH_TIMEOUT"
    SEARCH_FRESHNESS_WAIT_MAX_SECONDS = (
        "VAULTSPEC_RAG_SEARCH_FRESHNESS_WAIT_MAX_SECONDS"
    )
    SERVICE_ADMIN_TIMEOUT = "VAULTSPEC_RAG_ADMIN_TIMEOUT"
    SERVICE_REINDEX_TIMEOUT = "VAULTSPEC_RAG_REINDEX_TIMEOUT"
    # How long a pause waits for in-flight work to drain. Operator-tunable
    # because what has to drain is the operator's workload, not a round trip:
    # a service running long jobs needs longer than one serving searches.
    SERVICE_PAUSE_DRAIN_TIMEOUT = "VAULTSPEC_RAG_PAUSE_DRAIN_TIMEOUT"
    # Managed qdrant readiness bound, operator-tunable for very large stores.
    QDRANT_READY_TIMEOUT = "VAULTSPEC_RAG_QDRANT_READY_TIMEOUT"
    QDRANT_COLLECTION_LOAD_CONCURRENCY = (
        "VAULTSPEC_RAG_QDRANT_COLLECTION_LOAD_CONCURRENCY"
    )
    # Diagnostic memory probe on/off switch. Named here so this enum stays the
    # authoritative list, but deliberately absent from the defaults map: the
    # probe module is reachable from spawn workers and must not pull this
    # module into their import chain. It reads the raw value itself, through
    # the same shared boolean table this module coerces with, so the spellings
    # cannot drift from the ones every other flag accepts.
    MEMORY_PROBE = "VAULTSPEC_RAG_MEMORY_PROBE"
    MANAGED_LOG_MAX_BYTES = "VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES"
    MANAGED_LOG_BACKUP_COUNT = "VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT"
    # Service-domain indexing job lifecycle bounds.
    JOB_MAX_NONTERMINAL = "VAULTSPEC_RAG_JOB_MAX_NONTERMINAL"
    JOB_SHUTDOWN_TIMEOUT_SECONDS = "VAULTSPEC_RAG_JOB_SHUTDOWN_TIMEOUT_SECONDS"
    # Existing operation-level storage timeout and bounded write retry.
    STORE_OPERATION_TIMEOUT_SECONDS = "VAULTSPEC_RAG_STORE_OPERATION_TIMEOUT_SECONDS"
    STORE_WRITE_RETRY_ATTEMPTS = "VAULTSPEC_RAG_STORE_WRITE_RETRY_ATTEMPTS"
    STORE_WRITE_RETRY_BASE_SECONDS = "VAULTSPEC_RAG_STORE_WRITE_RETRY_BASE_SECONDS"
    STORE_WRITE_RETRY_MAX_SECONDS = "VAULTSPEC_RAG_STORE_WRITE_RETRY_MAX_SECONDS"
    # Resource-bounded indexing and watcher-retry policy.
    INDEX_SEGMENT_MAX_CHUNKS = "VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS"
    INDEX_SEGMENT_MAX_BYTES = "VAULTSPEC_RAG_INDEX_SEGMENT_MAX_BYTES"
    INDEX_QUEUE_MAX_CHUNKS = "VAULTSPEC_RAG_INDEX_QUEUE_MAX_CHUNKS"
    INDEX_QUEUE_MAX_BYTES = "VAULTSPEC_RAG_INDEX_QUEUE_MAX_BYTES"
    INDEX_NO_PROGRESS_TIMEOUT_SECONDS = (
        "VAULTSPEC_RAG_INDEX_NO_PROGRESS_TIMEOUT_SECONDS"
    )
    WATCH_RETRY_BASE_SECONDS = "VAULTSPEC_RAG_WATCH_RETRY_BASE_SECONDS"
    WATCH_RETRY_MAX_SECONDS = "VAULTSPEC_RAG_WATCH_RETRY_MAX_SECONDS"
    WATCH_RETRY_JITTER_FRACTION = "VAULTSPEC_RAG_WATCH_RETRY_JITTER_FRACTION"
    WATCH_CIRCUIT_FAILURE_THRESHOLD = "VAULTSPEC_RAG_WATCH_CIRCUIT_FAILURE_THRESHOLD"
    INDEX_RSS_CEILING_MIB = "VAULTSPEC_RAG_INDEX_RSS_CEILING_MIB"
    INDEX_CUDA_CEILING_MIB = "VAULTSPEC_RAG_INDEX_CUDA_CEILING_MIB"
    INDEX_CUDA_HEADROOM_MIB = "VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MIB"
    INDEX_CUDA_ALLOCATOR_FRACTION = "VAULTSPEC_RAG_INDEX_CUDA_ALLOCATOR_FRACTION"
    # Free device memory required before this process may load model stacks
    # onto the GPU. Distinct from the ceilings above, which bound the work an
    # already-resident process does; this one decides whether it becomes
    # resident at all.
    GPU_ADMISSION_FLOOR_MIB = "VAULTSPEC_RAG_GPU_ADMISSION_FLOOR_MIB"
    INDEX_SUPPORT_PROFILE = "VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE"
    # Wall-clock + memory tuning knobs introduced in #68 Track B.
    # Model identity and the dense width that must accompany it. Overriding a
    # model against an index built with another one is an operator decision
    # with consequences: the stored vectors belong to the old model's space.
    # A width that disagrees with the model is rejected by the server on the
    # first upsert rather than silently stored, so the mismatch is loud.
    EMBEDDING_MODEL = "VAULTSPEC_RAG_EMBEDDING_MODEL"
    EMBEDDING_DIMENSION = "VAULTSPEC_RAG_EMBEDDING_DIMENSION"
    SPARSE_MODEL = "VAULTSPEC_RAG_SPARSE_MODEL"
    RERANKER_MODEL = "VAULTSPEC_RAG_RERANKER_MODEL"
    # Where the models above are downloaded from. Exported to the hub
    # client's own ``HF_ENDPOINT`` before that client is first imported,
    # because the client reads its endpoint once, at import.
    RAG_HF_ENDPOINT = "VAULTSPEC_RAG_HF_ENDPOINT"
    TYPESAFE_API_KEY = "VAULTSPEC_RAG_TYPESAFE_API_KEY"
    EMBEDDING_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE"
    EMBEDDING_ENCODE_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE"
    EMBEDDING_MAX_SEQ_LENGTH = "VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH"
    MAX_EMBED_CHARS = "VAULTSPEC_RAG_MAX_EMBED_CHARS"
    # Codebase-index parallelism + throughput knobs (#155).
    INDEX_CHUNK_WORKERS = "VAULTSPEC_RAG_INDEX_CHUNK_WORKERS"
    EMBEDDING_CODE_ENCODE_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE"
    EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE = (
        "VAULTSPEC_RAG_EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE"
    )
    # Token-budget bucket planning knobs for the encode paths.
    EMBEDDING_ENCODE_TOKEN_BUDGET = "VAULTSPEC_RAG_EMBEDDING_ENCODE_TOKEN_BUDGET"
    EMBEDDING_SPARSE_ENCODE_TOKEN_BUDGET = (
        "VAULTSPEC_RAG_EMBEDDING_SPARSE_ENCODE_TOKEN_BUDGET"
    )
    EMBEDDING_ENCODE_CHARS_PER_TOKEN = "VAULTSPEC_RAG_EMBEDDING_ENCODE_CHARS_PER_TOKEN"
    INDEX_CACHE_FLUSH_SLICES = "VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES"
    VAULT_CACHE_FLUSH_SLICES = "VAULTSPEC_RAG_VAULT_CACHE_FLUSH_SLICES"
    DOCUMENT_CACHE_FLUSH_SLICES = "VAULTSPEC_RAG_DOCUMENT_CACHE_FLUSH_SLICES"
    INDEX_PARALLEL_MIN_BYTES = "VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES"
    # Dense-encoder backend selection (#155).
    DENSE_BACKEND = "VAULTSPEC_RAG_DENSE_BACKEND"
    DENSE_ONNX_FILE = "VAULTSPEC_RAG_DENSE_ONNX_FILE"
    # Filesystem-watcher / auto-reindex knobs (#143/#144).
    WATCH_ENABLED = "VAULTSPEC_RAG_WATCH_ENABLED"
    WATCH_DEBOUNCE_MS = "VAULTSPEC_RAG_WATCH_DEBOUNCE_MS"
    WATCH_COOLDOWN_S = "VAULTSPEC_RAG_WATCH_COOLDOWN_S"
    WATCH_COALESCE_MIN_SECONDS = "VAULTSPEC_RAG_WATCH_COALESCE_MIN_SECONDS"
    WATCH_COALESCE_MAX_SECONDS = "VAULTSPEC_RAG_WATCH_COALESCE_MAX_SECONDS"
    WATCH_COOLING_MAX_SECONDS = "VAULTSPEC_RAG_WATCH_COOLING_MAX_SECONDS"
    WATCH_MAXIMUM_FRESHNESS_SECONDS = "VAULTSPEC_RAG_WATCH_MAXIMUM_FRESHNESS_SECONDS"
    WATCH_MEASUREMENT_REEVALUATION_SECONDS = (
        "VAULTSPEC_RAG_WATCH_MEASUREMENT_REEVALUATION_SECONDS"
    )
    WATCH_BATCH_PATH_LIMIT = "VAULTSPEC_RAG_WATCH_BATCH_PATH_LIMIT"
    WATCH_SCOPE_MAX_PATHS = "VAULTSPEC_RAG_WATCH_SCOPE_MAX_PATHS"
    WATCH_SCOPE_MAX_BYTES = "VAULTSPEC_RAG_WATCH_SCOPE_MAX_BYTES"
    # Document-preprocessing hook knobs (#185). ``PREPROCESS`` carries the
    # kill switch (``=off``); resolved into ``preprocess_mode``.
    PREPROCESS = "VAULTSPEC_RAG_PREPROCESS"
    PREPROCESS_MAX_EMITTED_BYTES = "VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES"
    # Document split budget knobs. The effective chunk bound is the dense
    # model's token window times the chars-per-token ratio, so both are plain
    # overrides resolved through the generic path.
    DOCUMENT_CHUNK_CHARS_PER_TOKEN = "VAULTSPEC_RAG_DOCUMENT_CHUNK_CHARS_PER_TOKEN"
    DOCUMENT_CHUNK_OVERLAP_CHARS = "VAULTSPEC_RAG_DOCUMENT_CHUNK_OVERLAP_CHARS"
    HTML_STRIP = "VAULTSPEC_RAG_HTML_STRIP"
    # Stdio shim lifetime watchdog kill switch. Reads the shared boolean
    # table, but fails safe rather than rejecting: only an explicit falsey
    # spelling disarms the ancestor-death backstop.
    STDIO_WATCHDOG = "VAULTSPEC_RAG_STDIO_WATCHDOG"
    # Vault document chunking knob.
    VAULT_CHUNK_CHARS = "VAULTSPEC_RAG_VAULT_CHUNK_CHARS"
    # Intent-aware vault ranking knobs.
    VAULT_INTENT_DEFAULT = "VAULTSPEC_RAG_VAULT_INTENT_DEFAULT"
    VAULT_INTENT_RANKING_ENABLED = "VAULTSPEC_RAG_VAULT_INTENT_RANKING_ENABLED"
    VAULT_INTENT_TYPE_CAP = "VAULTSPEC_RAG_VAULT_INTENT_TYPE_CAP"
    # Code-search noise profile.
    CODE_NOISE_HIDE_DOMAINS = "VAULTSPEC_RAG_CODE_NOISE_HIDE_DOMAINS"
    CODE_NOISE_DEMOTE_DOMAINS = "VAULTSPEC_RAG_CODE_NOISE_DEMOTE_DOMAINS"
    CODE_NOISE_DEMOTE_PENALTY = "VAULTSPEC_RAG_CODE_NOISE_DEMOTE_PENALTY"
    DEDUP_LOCALES_DEFAULT = "VAULTSPEC_RAG_DEDUP_LOCALES_DEFAULT"
    # Reranker input token bound.
    RERANKER_MAX_LENGTH = "VAULTSPEC_RAG_RERANKER_MAX_LENGTH"
    RERANKER_BATCH_SIZE = "VAULTSPEC_RAG_RERANKER_BATCH_SIZE"
    # Vault-graph cache lifetime.
    GRAPH_TTL_SECONDS = "VAULTSPEC_RAG_GRAPH_TTL_SECONDS"
    # Worker-thread pool partitioning.
    SEARCH_CONCURRENCY = "VAULTSPEC_RAG_SEARCH_CONCURRENCY"
    INDEX_JOB_CONCURRENCY = "VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY"
    # Encode-seam vector reuse off-switch.
    INDEX_REUSE = "VAULTSPEC_RAG_INDEX_REUSE"

    QDRANT_URL = "VAULTSPEC_RAG_QDRANT_URL"
    QDRANT_API_KEY = "VAULTSPEC_RAG_QDRANT_API_KEY"
    QDRANT_QUANTIZATION = "VAULTSPEC_RAG_QDRANT_QUANTIZATION"
    SPARSE_ENABLED = "VAULTSPEC_RAG_SPARSE_ENABLED"
    RERANKER_ENABLED = "VAULTSPEC_RAG_RERANKER_ENABLED"
    # Supervised qdrant server-mode knobs.
    QDRANT_SERVER = "VAULTSPEC_RAG_QDRANT_SERVER"
    QDRANT_PORT = "VAULTSPEC_RAG_QDRANT_PORT"
    QDRANT_BINARY = "VAULTSPEC_RAG_QDRANT_BINARY"
    # The SHA256 the operator declares for that binary. The two are one
    # setting in two halves: a path with no digest would be a binary run
    # unverified, and a digest with no path verifies nothing.
    QDRANT_BINARY_SHA256 = "VAULTSPEC_RAG_QDRANT_BINARY_SHA256"
    QDRANT_STORAGE_DIR = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
    # Where the managed qdrant binary comes from, and whether a host start
    # fetches it unasked. The digests the download is checked against are
    # code constants and have no variable here: a source may be redirected,
    # the bytes it must serve may not.
    QDRANT_AUTO_PROVISION = "VAULTSPEC_RAG_QDRANT_AUTO_PROVISION"
    QDRANT_RELEASE_BASE_URL = "VAULTSPEC_RAG_QDRANT_RELEASE_BASE_URL"
    QDRANT_DOWNLOAD_HOSTS = "VAULTSPEC_RAG_QDRANT_DOWNLOAD_HOSTS"
    # Scheduled storage maintenance (auto-prune) knobs.
    STORAGE_AUTOPRUNE = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE"
    STORAGE_AUTOPRUNE_INTERVAL_MINUTES = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_INTERVAL_MINUTES"
    )
    STORAGE_AUTOPRUNE_GRACE_HOURS = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS"
    STORAGE_AUTOPRUNE_GRACE_HOURS_DATA = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS_DATA"
    )
    STORAGE_AUTOPRUNE_GRACE_HOURS_EPHEMERAL = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS_EPHEMERAL"
    )
    STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS"
    )
    STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB"
    STORAGE_AUTOPRUNE_MAX_PER_CYCLE = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_MAX_PER_CYCLE"
    STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS"
    )
    # Automatic non-destructive repair of a demonstrably shrunken index.
    INTEGRITY_AUTO_REPAIR = "VAULTSPEC_RAG_INTEGRITY_AUTO_REPAIR"
    # Geometry reconcile knobs (non-destructive; see storage-prealloc-reclaim).
    STORAGE_RECONCILE = "VAULTSPEC_RAG_STORAGE_RECONCILE"
    STORAGE_RECONCILE_MAX_PER_CYCLE = "VAULTSPEC_RAG_STORAGE_RECONCILE_MAX_PER_CYCLE"
    STORAGE_RECONCILE_BUDGET_SECONDS = "VAULTSPEC_RAG_STORAGE_RECONCILE_BUDGET_SECONDS"
    # First-class local-backend opt-out. When set truthy it selects the
    # on-disk store regardless of the server-mode default.
    LOCAL_ONLY = "VAULTSPEC_RAG_LOCAL_ONLY"

    # Markers this project sets on its own child processes. Transport
    # channels rather than knobs, but declared for the same reason every
    # other name is: the literal lives in one place, and a rename cannot
    # leave the reader on the other side of the process boundary behind.
    # The junction pair carries a path and a target to a PowerShell child
    # through its environment, so neither enters the command string where
    # it would be subject to injection. Prefixed like the rest of this
    # project's names, because this project both sets and reads them.
    RAG_JUNCTION_PATH = "VAULTSPEC_RAG_JUNCTION_PATH"
    RAG_JUNCTION_TARGET = "VAULTSPEC_RAG_JUNCTION_TARGET"
    # The execution envelope handed to a preprocessor child. Unprefixed and
    # staying that way: the readers are user-authored extractors, which this
    # project does not get to rename out from under.
    PREPROCESS_INVOCATION = "VAULTSPEC_PREPROCESS_INVOCATION"

    # Third-party env vars this codebase reads or sets - defined here so
    # the string literal lives in exactly one place.
    HF_HOME = "HF_HOME"
    HF_ENDPOINT = "HF_ENDPOINT"
    HF_HUB_OFFLINE = "HF_HUB_OFFLINE"
    HF_HUB_DOWNLOAD_TIMEOUT = "HF_HUB_DOWNLOAD_TIMEOUT"
    TRANSFORMERS_OFFLINE = "TRANSFORMERS_OFFLINE"
    DISABLE_SAFETENSORS_CONVERSION = "DISABLE_SAFETENSORS_CONVERSION"
    HF_DEACTIVATE_ASYNC_LOAD = "HF_DEACTIVATE_ASYNC_LOAD"
    HF_HUB_DISABLE_PROGRESS_BARS = "HF_HUB_DISABLE_PROGRESS_BARS"
    TRANSFORMERS_NO_ADVISORY_WARNINGS = "TRANSFORMERS_NO_ADVISORY_WARNINGS"
    TRANSFORMERS_VERBOSITY = "TRANSFORMERS_VERBOSITY"
    PYTORCH_ENABLE_MPS_FALLBACK = "PYTORCH_ENABLE_MPS_FALLBACK"
    UV_CACHE_DIR = "UV_CACHE_DIR"
    UV_TOOL_DIR = "UV_TOOL_DIR"
    VIRTUAL_ENV = "VIRTUAL_ENV"
    # The interpreter's safe-path switch. Never read as configuration: it is
    # set on this process only while an indexing worker pool is open, because
    # the environment is the one thing that reaches a pool worker's start.
    PYTHON_SAFE_PATH = "PYTHONSAFEPATH"
    # The program search path and, on Windows, the extensions a program name
    # may carry. Read to find a helper program in an absolute location: an
    # empty or relative entry of the search path is never searched.
    PATH = "PATH"
    PATHEXT = "PATHEXT"
    # The operating system's temporary-directory conventions, read to decide
    # whether an indexed root was throwaway.
    TEMP = "TEMP"
    TMP = "TMP"
    TMPDIR = "TMPDIR"


class OperatorBinaryPairError(ValueError):
    """Exactly one of the operator binary's path and digest is set.

    Its own type so that the code resolving the binary can report this one
    refusal as a fault of the binary configuration without relabelling every
    other unusable setting as one. It is a ``ValueError`` like any other
    settings refusal, so nothing that handles those sees a difference.
    """


class OperatorBinary(NamedTuple):
    """A Qdrant binary the operator supplies, and the digest they declare for it.

    The two travel together because neither is usable alone. The digest is
    what the operator states the file to be; whoever runs the file hashes it
    and compares.

    Attributes:
        path: The configured path, as written. Whether it names an absolute
            regular file is judged where the binary is resolved.
        sha256: The declared SHA256, as 64 lower-case hexadecimal characters.
    """

    path: str
    sha256: str


#: Default for ``EnvVar.STATUS_DIR``, declared beside the env var it defaults
#: so every consumer - the persistence layer and the config wrapper alike -
#: imports the one literal instead of each keeping its own copy.
STATUS_DIR_DEFAULT = "~/.vaultspec-rag"


def hf_cache_only() -> bool:
    """Return whether supported Hugging Face offline mode is enabled.

    ``HF_HUB_OFFLINE`` is the authoritative Hub switch. Transformers also
    documents ``TRANSFORMERS_OFFLINE`` for cache-only model loading, so honour
    either value and pass ``local_files_only=True`` explicitly to model
    constructors. Normal product construction remains online-capable when both
    variables are unset.

    These two variables belong to the Hub and Transformers, not to this
    project, so a word neither table recognises is read as "not offline"
    rather than rejected: refusing a value the owning library accepts would
    break an install whose configuration this module has no authority over.
    The library reports its own opinion of a bad value.
    """
    return any(
        parse_bool(os.environ.get(var.value, "")) is True
        for var in (EnvVar.HF_HUB_OFFLINE, EnvVar.TRANSFORMERS_OFFLINE)
    )
