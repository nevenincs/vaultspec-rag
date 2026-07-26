"""Local configuration wrapper for vaultspec-rag.

Provides RAG-specific defaults and bridges the gap when the base vaultspec
VaultSpecConfig is missing RAG-specific attributes.

Resolution order for a RAG settings key is CLI override, then environment
variable, then the shipped default.

Coercion and validation policy
------------------------------
One rule governs every setting this module owns: **reject loudly, never
repair and never ignore.** Concretely:

- A value is coerced to the type of its shipped default. Text that does not
  parse as that type is an error, never a reason to fall back to the default:
  a silent fallback leaves the operator's typo in place and the wrong value
  running in production, which is the failure this policy exists to prevent.
- Numeric settings declare their admissible range in ``_SETTING_BOUNDS``, and
  an out-of-range value is rejected rather than clamped. Clamping substitutes
  a value nobody asked for, which is the same silent substitution as ignoring
  the typo, only harder to notice afterwards.
- Every rejection names the environment variable the value came from (when it
  came from one), the settings key, the offending value, and the shape that
  was expected, so the message alone is enough to fix the mistake.
- Validation runs eagerly across the whole table when a config is built, and
  reports every problem it finds in one error. A daemon therefore fails at
  startup with the complete list instead of dying mid-flight the first time
  some rarely-read knob is touched. The same validator also runs on each read,
  so no access path can hand back a value that never passed it.
- Every numeric default must declare a range. An import-time check enforces
  this, so a new numeric knob cannot quietly land without one.

Empty text is the one value that is not simply refused, and what it means
depends on the setting's type. For a *string* setting it is treated as absent,
because ``VAR="$UNSET"`` exports an empty string and ``Path("")`` resolves to
the working directory - which would repoint the managed-directory blast radius
(delete, clean) at wherever the operator happened to be standing. For a *flag*
it reads as off, the way a shell spells "not on", and off is the safe
direction. For a *numeric* setting it has no defensible reading at all and is
rejected like any other malformed input.

Two settings resolve outside the generic path because their behaviour is not
a plain override; each says why where it is defined.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    VaultSpecConfig as BaseConfig,
)
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    get_config as get_base_config,
)

logger = logging.getLogger(__name__)

#: The two-state document-preprocessing mode.
#: ``default`` runs a root's rules directly; ``off`` is the kill switch.
PreprocessMode = Literal["default", "off"]

_VALID_PREPROCESS_MODES: frozenset[str] = frozenset({"default", "off"})
_VALID_INDEX_SUPPORT_PROFILES: frozenset[str] = frozenset(
    {"managed-service", "embedded-local"}
)


@dataclass(frozen=True, slots=True)
class ContentRouteConfig:
    """One caller-authored project-relative pattern and raw target token.

    Unknown targets remain representable at this boundary so policy
    compilation can reject them as structured configuration errors instead of
    silently dropping a route. Rule priority is the enclosing tuple's order.
    """

    pattern: str
    target: str

    def __post_init__(self) -> None:
        if not self.pattern.strip():
            raise ValueError("content route pattern must not be empty")
        if "\0" in self.pattern:
            raise ValueError("content route pattern must not contain NUL")
        if not self.target.strip():
            raise ValueError("content route target must not be empty")


@dataclass(frozen=True, slots=True)
class RootContentPolicyConfig:
    """Raw root policy whose route tuple preserves caller precedence."""

    source_profile: str
    routes: tuple[ContentRouteConfig, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_profile.strip():
            raise ValueError("source profile must not be empty")


class EnvVar(StrEnum):
    """Recognized environment variables for vaultspec-rag.

    Each member's value is the full env var name.  This enum is the
    single source of truth - no other module should use bare string
    literals when reading or writing env vars for RAG configuration.
    """

    RAG_ROOT = "VAULTSPEC_RAG_ROOT"
    # Set only in the detached HTTP daemon's environment (by _service_child_env)
    # so code running inside the resident service can distinguish itself from an
    # interactive in-process CLI; the signal is independent of the storage
    # backend so a --local-only daemon is still recognized.
    SERVICE_DAEMON = "VAULTSPEC_RAG_SERVICE_DAEMON"
    DATA_DIR = "VAULTSPEC_RAG_DATA_DIR"
    QDRANT_DIR = "VAULTSPEC_RAG_QDRANT_DIR"
    INDEX_META = "VAULTSPEC_RAG_INDEX_META"
    CODE_INDEX_META = "VAULTSPEC_RAG_CODE_INDEX_META"
    STATUS_DIR = "VAULTSPEC_RAG_STATUS_DIR"
    LOG_FILE = "VAULTSPEC_RAG_LOG_FILE"
    PORT = "VAULTSPEC_RAG_PORT"
    LOG_LEVEL = "VAULTSPEC_RAG_LOG_LEVEL"
    SERVICE_IDLE_TTL_SECONDS = "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS"
    SERVICE_MAX_PROJECTS = "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS"
    # Client-side request bounds. Registered here so this enum stays the one
    # authoritative list of settings; the thin client parses them leniently
    # and falls back to the shipped default rather than raising.
    SERVICE_SEARCH_TIMEOUT = "VAULTSPEC_RAG_SEARCH_TIMEOUT"
    SERVICE_ADMIN_TIMEOUT = "VAULTSPEC_RAG_ADMIN_TIMEOUT"
    # Managed qdrant readiness bound, operator-tunable for very large stores.
    QDRANT_READY_TIMEOUT = "VAULTSPEC_RAG_QDRANT_READY_TIMEOUT"
    # Diagnostic memory probe on/off switch. Named here so this enum stays the
    # authoritative list, but deliberately absent from the defaults map: the
    # probe module is reachable from spawn workers and must not pull this
    # module into their import chain, and it reads the raw value with its own
    # "any non-empty, non-zero string" rule rather than a bool coercion.
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
    INDEX_RSS_CEILING_MB = "VAULTSPEC_RAG_INDEX_RSS_CEILING_MB"
    INDEX_CUDA_CEILING_MB = "VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB"
    INDEX_CUDA_HEADROOM_MB = "VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MB"
    INDEX_CUDA_ALLOCATOR_FRACTION = "VAULTSPEC_RAG_INDEX_CUDA_ALLOCATOR_FRACTION"
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
    # Stdio shim lifetime watchdog kill switch;
    # "0"/"false"/"off"/"no" disables the ancestor-death backstop.
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
    QDRANT_STORAGE_DIR = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
    # Scheduled storage maintenance (auto-prune) knobs.
    STORAGE_AUTOPRUNE = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE"
    STORAGE_AUTOPRUNE_INTERVAL_MINUTES = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_INTERVAL_MINUTES"
    )
    STORAGE_AUTOPRUNE_GRACE_HOURS = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS"
    STORAGE_AUTOPRUNE_GRACE_HOURS_DATA = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS_DATA"
    )
    STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS"
    )
    STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB"
    STORAGE_AUTOPRUNE_MAX_PER_CYCLE = "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_MAX_PER_CYCLE"
    STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS = (
        "VAULTSPEC_RAG_STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS"
    )
    # Geometry reconcile knobs (non-destructive; see storage-prealloc-reclaim).
    STORAGE_RECONCILE = "VAULTSPEC_RAG_STORAGE_RECONCILE"
    STORAGE_RECONCILE_MAX_PER_CYCLE = "VAULTSPEC_RAG_STORAGE_RECONCILE_MAX_PER_CYCLE"
    STORAGE_RECONCILE_BUDGET_SECONDS = "VAULTSPEC_RAG_STORAGE_RECONCILE_BUDGET_SECONDS"
    # First-class local-backend opt-out. When set truthy it selects the
    # on-disk store regardless of the server-mode default.
    LOCAL_ONLY = "VAULTSPEC_RAG_LOCAL_ONLY"

    # Third-party env vars referenced in the codebase - defined here so
    # the string literal lives in exactly one place.
    HF_ENDPOINT = "HF_ENDPOINT"
    HF_HOME = "HF_HOME"
    HF_HUB_OFFLINE = "HF_HUB_OFFLINE"
    HF_HUB_DOWNLOAD_TIMEOUT = "HF_HUB_DOWNLOAD_TIMEOUT"
    TRANSFORMERS_OFFLINE = "TRANSFORMERS_OFFLINE"
    DISABLE_SAFETENSORS_CONVERSION = "DISABLE_SAFETENSORS_CONVERSION"
    VIRTUAL_ENV = "VIRTUAL_ENV"


def hf_cache_only() -> bool:
    """Return whether supported Hugging Face offline mode is enabled.

    ``HF_HUB_OFFLINE`` is the authoritative Hub switch. Transformers also
    documents ``TRANSFORMERS_OFFLINE`` for cache-only model loading, so honour
    either value and pass ``local_files_only=True`` explicitly to model
    constructors. Normal product construction remains online-capable when both
    variables are unset.
    """
    enabled_values = {"1", "true", "yes", "on"}
    return any(
        os.environ.get(var.value, "").strip().lower() in enabled_values
        for var in (EnvVar.HF_HUB_OFFLINE, EnvVar.TRANSFORMERS_OFFLINE)
    )


@dataclass(frozen=True, slots=True)
class _NumericBound:
    """The admissible numeric range for one settings key.

    ``shape`` is the human phrase that completes "<name> must be ...", so the
    rejection message and the range it describes can never drift apart.
    """

    shape: str
    integral: bool
    minimum: float
    minimum_exclusive: bool = False
    maximum: float | None = None

    def parse(self, raw: str) -> object:
        """Parse environment text into this bound's numeric type."""
        return int(raw) if self.integral else float(raw)

    def admits(self, value: object) -> bool:
        """Return whether *value* is inside this bound."""
        # bool is an int subclass; a flag is never a numeric setting.
        if isinstance(value, bool):
            return False
        if self.integral:
            if not isinstance(value, int):
                return False
        elif not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        numeric = float(value)
        if self.minimum_exclusive:
            if numeric <= self.minimum:
                return False
        elif numeric < self.minimum:
            return False
        return self.maximum is None or numeric <= self.maximum

    def narrow(self, value: object) -> object:
        """Return *value* as this bound's declared type."""
        return int(cast("int", value)) if self.integral else float(cast("float", value))


@dataclass(frozen=True, slots=True)
class _ChoiceBound:
    """The admissible names for one enumerated settings key.

    Comparison and the returned value are both case-folded and stripped, so an
    operator's stray whitespace or capitalisation resolves rather than being
    rejected, while an unrecognised name is still refused.
    """

    shape: str
    allowed: frozenset[str]

    def parse(self, raw: str) -> object:
        """Return environment text unchanged; narrowing normalises it."""
        return raw

    def admits(self, value: object) -> bool:
        """Return whether *value* names one of the allowed choices."""
        return isinstance(value, str) and value.strip().lower() in self.allowed

    def narrow(self, value: object) -> object:
        """Return the normalised choice name."""
        return cast("str", value).strip().lower()


type _SettingBound = _NumericBound | _ChoiceBound

_POSITIVE_INT = _NumericBound("a positive integer", integral=True, minimum=1)
_NON_NEGATIVE_INT = _NumericBound("a non-negative integer", integral=True, minimum=0)
_TCP_PORT = _NumericBound(
    "a TCP port between 1 and 65535", integral=True, minimum=1, maximum=65535
)
_POSITIVE_NUMBER = _NumericBound(
    "a finite positive number", integral=False, minimum=0.0, minimum_exclusive=True
)
_NON_NEGATIVE_NUMBER = _NumericBound(
    "a finite non-negative number", integral=False, minimum=0.0
)
_CLOSED_UNIT_INTERVAL = _NumericBound(
    "a finite number between 0 and 1", integral=False, minimum=0.0, maximum=1.0
)
_OPEN_UNIT_INTERVAL = _NumericBound(
    "a finite number greater than 0 and no greater than 1",
    integral=False,
    minimum=0.0,
    minimum_exclusive=True,
    maximum=1.0,
)

#: Accepted spellings for a boolean setting. Anything else is a typo and is
#: refused: treating an unrecognised word as false is exactly the silent
#: substitution this module refuses to make, and it disables features quietly.
#: The empty string is the one exception, and reads as off - ``VAR=`` is how a
#: shell spells "not on", and off is the safe direction to resolve it in.
_TRUE_TOKENS: frozenset[str] = frozenset({"1", "true", "yes", "on"})
_FALSE_TOKENS: frozenset[str] = frozenset({"0", "false", "no", "off", ""})
_BOOL_SHAPE = "one of " + ", ".join(
    sorted(token for token in _TRUE_TOKENS | _FALSE_TOKENS if token)
)


def _rejection(
    key: str, shape: str, value: object, source: EnvVar | None
) -> ValueError:
    """Build the one rejection message shape this module emits.

    Args:
        key: The settings key that failed.
        shape: The human phrase describing what was expected.
        value: The offending value, rendered for the operator.
        source: The environment variable the value came from, when it did.

    Returns:
        A ``ValueError`` naming the variable, the key, the value and the shape.
    """
    where = key if source is None else f"{source.value} ({key})"
    return ValueError(f"{where} must be {shape}, got {value!r}")


# Mapping from _RAG_DEFAULTS key → EnvVar member for env override lookup.
_ENV_OVERRIDE_MAP: dict[str, EnvVar] = {
    "data_dir": EnvVar.DATA_DIR,
    "qdrant_dir": EnvVar.QDRANT_DIR,
    "index_metadata_file": EnvVar.INDEX_META,
    "code_index_metadata_file": EnvVar.CODE_INDEX_META,
    "status_dir": EnvVar.STATUS_DIR,
    "log_file": EnvVar.LOG_FILE,
    "mcp_port": EnvVar.PORT,
    "log_level": EnvVar.LOG_LEVEL,
    "service_idle_ttl_seconds": EnvVar.SERVICE_IDLE_TTL_SECONDS,
    "service_max_projects": EnvVar.SERVICE_MAX_PROJECTS,
    "service_search_timeout_seconds": EnvVar.SERVICE_SEARCH_TIMEOUT,
    "service_admin_timeout_seconds": EnvVar.SERVICE_ADMIN_TIMEOUT,
    "qdrant_ready_timeout_seconds": EnvVar.QDRANT_READY_TIMEOUT,
    "managed_log_max_bytes": EnvVar.MANAGED_LOG_MAX_BYTES,
    "managed_log_backup_count": EnvVar.MANAGED_LOG_BACKUP_COUNT,
    "job_max_nonterminal": EnvVar.JOB_MAX_NONTERMINAL,
    "job_shutdown_timeout_seconds": EnvVar.JOB_SHUTDOWN_TIMEOUT_SECONDS,
    "store_operation_timeout_seconds": EnvVar.STORE_OPERATION_TIMEOUT_SECONDS,
    "store_write_retry_attempts": EnvVar.STORE_WRITE_RETRY_ATTEMPTS,
    "store_write_retry_base_seconds": EnvVar.STORE_WRITE_RETRY_BASE_SECONDS,
    "store_write_retry_max_seconds": EnvVar.STORE_WRITE_RETRY_MAX_SECONDS,
    "index_segment_max_chunks": EnvVar.INDEX_SEGMENT_MAX_CHUNKS,
    "index_segment_max_bytes": EnvVar.INDEX_SEGMENT_MAX_BYTES,
    "index_queue_max_chunks": EnvVar.INDEX_QUEUE_MAX_CHUNKS,
    "index_queue_max_bytes": EnvVar.INDEX_QUEUE_MAX_BYTES,
    "index_no_progress_timeout_seconds": EnvVar.INDEX_NO_PROGRESS_TIMEOUT_SECONDS,
    "watch_retry_base_seconds": EnvVar.WATCH_RETRY_BASE_SECONDS,
    "watch_retry_max_seconds": EnvVar.WATCH_RETRY_MAX_SECONDS,
    "watch_retry_jitter_fraction": EnvVar.WATCH_RETRY_JITTER_FRACTION,
    "watch_circuit_failure_threshold": EnvVar.WATCH_CIRCUIT_FAILURE_THRESHOLD,
    "index_rss_ceiling_mb": EnvVar.INDEX_RSS_CEILING_MB,
    "index_cuda_ceiling_mb": EnvVar.INDEX_CUDA_CEILING_MB,
    "index_cuda_headroom_mb": EnvVar.INDEX_CUDA_HEADROOM_MB,
    "index_cuda_allocator_fraction": EnvVar.INDEX_CUDA_ALLOCATOR_FRACTION,
    "index_support_profile": EnvVar.INDEX_SUPPORT_PROFILE,
    # Performance tuning knobs - surface them via env vars too so
    # deploy-time tuning does not require CLI flags or config file edits.
    "embedding_model": EnvVar.EMBEDDING_MODEL,
    "embedding_dimension": EnvVar.EMBEDDING_DIMENSION,
    "sparse_model": EnvVar.SPARSE_MODEL,
    "reranker_model": EnvVar.RERANKER_MODEL,
    "reranker_batch_size": EnvVar.RERANKER_BATCH_SIZE,
    "graph_ttl_seconds": EnvVar.GRAPH_TTL_SECONDS,
    "embedding_batch_size": EnvVar.EMBEDDING_BATCH_SIZE,
    "embedding_encode_batch_size": EnvVar.EMBEDDING_ENCODE_BATCH_SIZE,
    "embedding_max_seq_length": EnvVar.EMBEDDING_MAX_SEQ_LENGTH,
    "max_embed_chars": EnvVar.MAX_EMBED_CHARS,
    "index_chunk_workers": EnvVar.INDEX_CHUNK_WORKERS,
    "embedding_code_encode_batch_size": EnvVar.EMBEDDING_CODE_ENCODE_BATCH_SIZE,
    "embedding_document_encode_batch_size": (
        EnvVar.EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE
    ),
    "index_cache_flush_slices": EnvVar.INDEX_CACHE_FLUSH_SLICES,
    "vault_cache_flush_slices": EnvVar.VAULT_CACHE_FLUSH_SLICES,
    "document_cache_flush_slices": EnvVar.DOCUMENT_CACHE_FLUSH_SLICES,
    "index_parallel_min_bytes": EnvVar.INDEX_PARALLEL_MIN_BYTES,
    "dense_backend": EnvVar.DENSE_BACKEND,
    "dense_onnx_file": EnvVar.DENSE_ONNX_FILE,
    # Filesystem-watcher / auto-reindex knobs (#143/#144).
    "watch_enabled": EnvVar.WATCH_ENABLED,
    "watch_debounce_ms": EnvVar.WATCH_DEBOUNCE_MS,
    "watch_cooldown_s": EnvVar.WATCH_COOLDOWN_S,
    # Document-preprocessing hook knobs (#185). ``preprocess_mode`` is
    # deliberately absent from this single-var override map: its env var is a
    # kill switch whose value is not the setting's value, so it is resolved by
    # a transform rather than a plain override.
    "preprocess_max_emitted_bytes": EnvVar.PREPROCESS_MAX_EMITTED_BYTES,
    "document_chunk_chars_per_token": EnvVar.DOCUMENT_CHUNK_CHARS_PER_TOKEN,
    "document_chunk_overlap_chars": EnvVar.DOCUMENT_CHUNK_OVERLAP_CHARS,
    "html_strip": EnvVar.HTML_STRIP,
    # Vault chunking + reranker input knobs.
    "vault_chunk_chars": EnvVar.VAULT_CHUNK_CHARS,
    "reranker_max_length": EnvVar.RERANKER_MAX_LENGTH,
    # Intent-aware vault ranking knobs.
    "vault_intent_default": EnvVar.VAULT_INTENT_DEFAULT,
    "vault_intent_ranking_enabled": EnvVar.VAULT_INTENT_RANKING_ENABLED,
    "vault_intent_type_cap": EnvVar.VAULT_INTENT_TYPE_CAP,
    # Code-search noise profile.
    "code_noise_hide_domains": EnvVar.CODE_NOISE_HIDE_DOMAINS,
    "code_noise_demote_domains": EnvVar.CODE_NOISE_DEMOTE_DOMAINS,
    "code_noise_demote_penalty": EnvVar.CODE_NOISE_DEMOTE_PENALTY,
    "dedup_locales_default": EnvVar.DEDUP_LOCALES_DEFAULT,
    # Worker-thread pool partitioning.
    "search_concurrency": EnvVar.SEARCH_CONCURRENCY,
    "index_job_concurrency": EnvVar.INDEX_JOB_CONCURRENCY,
    # Encode-seam vector reuse off-switch.
    "index_reuse_enabled": EnvVar.INDEX_REUSE,
    "qdrant_url": EnvVar.QDRANT_URL,
    "qdrant_api_key": EnvVar.QDRANT_API_KEY,
    "qdrant_quantization": EnvVar.QDRANT_QUANTIZATION,
    "sparse_enabled": EnvVar.SPARSE_ENABLED,
    "reranker_enabled": EnvVar.RERANKER_ENABLED,
    # Supervised qdrant server-mode knobs.
    "qdrant_server": EnvVar.QDRANT_SERVER,
    "qdrant_port": EnvVar.QDRANT_PORT,
    "qdrant_binary": EnvVar.QDRANT_BINARY,
    "qdrant_storage_dir": EnvVar.QDRANT_STORAGE_DIR,
    # Scheduled storage maintenance (auto-prune) knobs.
    "storage_autoprune": EnvVar.STORAGE_AUTOPRUNE,
    "storage_autoprune_interval_minutes": EnvVar.STORAGE_AUTOPRUNE_INTERVAL_MINUTES,
    "storage_autoprune_grace_hours": EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS,
    "storage_autoprune_grace_hours_data": EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS_DATA,
    "storage_autoprune_archive_retention_days": (
        EnvVar.STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS
    ),
    "storage_autoprune_archive_max_gb": EnvVar.STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB,
    "storage_autoprune_max_per_cycle": EnvVar.STORAGE_AUTOPRUNE_MAX_PER_CYCLE,
    "storage_autoprune_ephemeral_idle_hours": (
        EnvVar.STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS
    ),
    # Geometry reconcile knobs.
    "storage_reconcile": EnvVar.STORAGE_RECONCILE,
    "storage_reconcile_max_per_cycle": EnvVar.STORAGE_RECONCILE_MAX_PER_CYCLE,
    "storage_reconcile_budget_seconds": EnvVar.STORAGE_RECONCILE_BUDGET_SECONDS,
    # First-class local-backend opt-out knob.
    "local_only": EnvVar.LOCAL_ONLY,
}


# Admissible range for every settings key that has one. A key absent from this
# table carries no range (paths, model names, free-form strings, flags); a key
# whose default is numeric MUST be present, which the import-time check below
# the class enforces so a new knob cannot land without a declared range.
#
# Zero is admitted only where it means something: an in-band "auto" or
# "disabled" sentinel documented at the default, or a bound whose lower end is
# genuinely nothing. Everywhere else it is refused along with the negatives.
_SETTING_BOUNDS: dict[str, _SettingBound] = {
    # Service lifecycle. A zero idle TTL means "evict as soon as idle", which
    # is a coherent request; a negative one is not.
    "mcp_port": _TCP_PORT,
    "qdrant_port": _TCP_PORT,
    "service_idle_ttl_seconds": _NON_NEGATIVE_INT,
    "service_max_projects": _POSITIVE_INT,
    "service_search_timeout_seconds": _POSITIVE_NUMBER,
    "service_admin_timeout_seconds": _POSITIVE_NUMBER,
    "qdrant_ready_timeout_seconds": _POSITIVE_NUMBER,
    "graph_ttl_seconds": _NON_NEGATIVE_NUMBER,
    # Managed log retention. Zero backups is a bounded no-history mode; a zero
    # rollover threshold would make every source unbounded.
    "managed_log_max_bytes": _POSITIVE_INT,
    "managed_log_backup_count": _NON_NEGATIVE_INT,
    # Indexing job lifecycle.
    "job_max_nonterminal": _POSITIVE_INT,
    "job_shutdown_timeout_seconds": _POSITIVE_NUMBER,
    # Store operation timeout and bounded write retry.
    "store_operation_timeout_seconds": _POSITIVE_NUMBER,
    "store_write_retry_attempts": _POSITIVE_INT,
    "store_write_retry_base_seconds": _POSITIVE_NUMBER,
    "store_write_retry_max_seconds": _POSITIVE_NUMBER,
    # Resource-bounded indexing and watcher-retry policy.
    "index_segment_max_chunks": _POSITIVE_INT,
    "index_segment_max_bytes": _POSITIVE_INT,
    "index_queue_max_chunks": _POSITIVE_INT,
    "index_queue_max_bytes": _POSITIVE_INT,
    "index_no_progress_timeout_seconds": _POSITIVE_NUMBER,
    "watch_retry_base_seconds": _POSITIVE_NUMBER,
    "watch_retry_max_seconds": _POSITIVE_NUMBER,
    "watch_retry_jitter_fraction": _CLOSED_UNIT_INTERVAL,
    "watch_circuit_failure_threshold": _POSITIVE_INT,
    # Memory ceilings. The CUDA ceiling's zero means "auto-derive from the
    # device", so it admits zero where the RSS ceiling does not.
    "index_rss_ceiling_mb": _POSITIVE_NUMBER,
    "index_cuda_ceiling_mb": _NON_NEGATIVE_NUMBER,
    "index_cuda_headroom_mb": _POSITIVE_NUMBER,
    "index_cuda_allocator_fraction": _OPEN_UNIT_INTERVAL,
    "index_support_profile": _ChoiceBound(
        "one of " + ", ".join(sorted(_VALID_INDEX_SUPPORT_PROFILES)),
        frozenset(_VALID_INDEX_SUPPORT_PROFILES),
    ),
    # Embedding and reranking throughput. A zero batch encodes nothing.
    "embedding_dimension": _POSITIVE_INT,
    "embedding_batch_size": _POSITIVE_INT,
    "embedding_encode_batch_size": _POSITIVE_INT,
    "embedding_code_encode_batch_size": _POSITIVE_INT,
    "embedding_document_encode_batch_size": _POSITIVE_INT,
    "embedding_max_seq_length": _POSITIVE_INT,
    "max_embed_chars": _POSITIVE_INT,
    "reranker_batch_size": _POSITIVE_INT,
    "reranker_max_length": _POSITIVE_INT,
    "vault_chunk_chars": _POSITIVE_INT,
    # Codebase-index parallelism. Zero workers selects the auto path, and a
    # zero parallel threshold parallelises every tree.
    "index_chunk_workers": _NON_NEGATIVE_INT,
    "index_parallel_min_bytes": _NON_NEGATIVE_INT,
    "index_cache_flush_slices": _POSITIVE_INT,
    "vault_cache_flush_slices": _POSITIVE_INT,
    "document_cache_flush_slices": _POSITIVE_INT,
    # Worker-thread pool partitioning. A zero limiter admits no callers.
    "search_concurrency": _POSITIVE_INT,
    "index_job_concurrency": _POSITIVE_INT,
    # Intent-aware vault ranking. A zero type cap disables the cap.
    "vault_intent_type_cap": _NON_NEGATIVE_INT,
    # Code-search noise profile. A zero penalty disables demotion.
    "code_noise_demote_penalty": _NON_NEGATIVE_NUMBER,
    # Filesystem watcher. Zero means "no delay" for both, not "disabled".
    "watch_debounce_ms": _NON_NEGATIVE_INT,
    "watch_cooldown_s": _NON_NEGATIVE_NUMBER,
    # Document preprocessing and splitting.
    "preprocess_max_emitted_bytes": _POSITIVE_INT,
    "document_chunk_chars_per_token": _POSITIVE_INT,
    "document_chunk_overlap_chars": _POSITIVE_INT,
    # Scheduled storage maintenance. The per-cycle caps admit zero, which is
    # the same as the feature's own off switch; the grace windows admit zero
    # so a harness can exercise reclamation without waiting, and the ephemeral
    # idle window documents zero as its disable value.
    "storage_autoprune_interval_minutes": _POSITIVE_NUMBER,
    "storage_autoprune_grace_hours": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_grace_hours_data": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_archive_retention_days": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_archive_max_gb": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_max_per_cycle": _NON_NEGATIVE_INT,
    "storage_autoprune_ephemeral_idle_hours": _NON_NEGATIVE_NUMBER,
    "storage_reconcile_max_per_cycle": _NON_NEGATIVE_INT,
    "storage_reconcile_budget_seconds": _POSITIVE_NUMBER,
}


# Name of the persisted local-only marker inside the managed service
# (``status_dir``) directory. ``install --local-only`` writes this so the
# resident service honours the local backend on a later ``server start``
# without the operator re-passing the flag. It lives under ``status_dir``
# (``~/.vaultspec-rag`` by default, overridable via
# ``VAULTSPEC_RAG_STATUS_DIR``) because that is the per-host, gitignored,
# test-isolatable home for runtime selections - never the project tree, so
# the pure-Python wheel and the repository stay untouched.
_LOCAL_ONLY_MARKER_FILENAME = "local-only.json"

# Default managed service directory. Kept in lock-step with the
# ``status_dir`` entry in ``_RAG_DEFAULTS`` below (asserted at import) so
# the persistence helpers resolve the same directory the config does
# without importing the class they feed.
_STATUS_DIR_DEFAULT = "~/.vaultspec-rag"


def _status_dir_path() -> Path:
    """Resolve the managed service directory, honouring the env override.

    Read straight from the resolution chain (env override -> default) so
    the persisted local-only marker lands in the same directory the
    daemon and CLI already use for ``service.json`` and the log. Reading
    the env directly (rather than via the cached config) keeps the
    persistence layer free of the config singleton it feeds.
    """
    raw = os.environ.get(EnvVar.STATUS_DIR.value) or _STATUS_DIR_DEFAULT
    return Path(raw).expanduser()


def _local_only_marker_path() -> Path:
    """Return the path of the persisted local-only marker file."""
    return _status_dir_path() / _LOCAL_ONLY_MARKER_FILENAME


def persist_local_only(value: bool) -> Path:
    """Persist the local-only backend selection to the managed service dir.

    ``install --local-only`` calls this so a later ``server start`` (in a
    fresh process, with no flag and no env) still selects the on-disk
    store. The marker is a small JSON document (``{"local_only": bool}``)
    written atomically through a ``.tmp`` sibling and ``os.replace`` so a
    concurrent reader never observes a half-written file. Writing
    ``False`` records an explicit server-mode selection, overwriting any
    prior local-only marker rather than deleting it, so the persisted
    choice is always unambiguous.

    Args:
        value: ``True`` to persist the local backend selection, ``False``
            to persist an explicit server-mode selection.

    Returns:
        The path the marker was written to.
    """
    path = _local_only_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"local_only": bool(value)}), encoding="utf-8")
    os.replace(tmp, path)
    logger.debug("persisted local_only=%s to %s", value, path)
    return path


def read_persisted_local_only() -> bool | None:
    """Read the persisted local-only selection, if any.

    Returns ``None`` when no marker has been written (the common case on a
    fresh host), so the resolver falls through to the module default. A
    malformed or unreadable marker is treated as absent and logged at
    debug rather than raised, because a corrupt runtime hint must never
    crash startup - the default backend remains the safe fallback.

    Returns:
        The persisted boolean, or ``None`` when no usable marker exists.
    """
    path = _local_only_marker_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.debug("local-only marker unreadable at %s: %s", path, exc)
        return None
    try:
        value = json.loads(raw).get("local_only")
    except (ValueError, AttributeError) as exc:
        logger.debug("local-only marker malformed at %s: %s", path, exc)
        return None
    return bool(value) if isinstance(value, bool) else None


class VaultSpecConfigWrapper:
    """Wraps VaultSpecConfig to provide RAG-specific attributes.

    Proxies attribute access to the underlying ``BaseConfig``,
    falling back to ``_RAG_DEFAULTS`` when the base config lacks a
    RAG-specific key.

    Resolution order for RAG keys:
    1. CLI override (stored via ``overrides`` dict at construction)
    2. Environment variable (via ``_ENV_OVERRIDE_MAP``)
    3. ``_RAG_DEFAULTS`` value

    The resolved value is then coerced and range-checked under the module's
    coercion and validation policy, both on construction and on every read.

    Attributes:
        _RAG_DEFAULTS: Default values for RAG-specific configuration
            keys not present on the base ``VaultSpecConfig``.
        _SETTING_BOUNDS: Module-level table of admissible ranges, keyed by
            settings key; every numeric default must appear in it.
        _base: The underlying ``VaultSpecConfig`` instance that
            provides project-level settings.
    """

    _RAG_DEFAULTS: ClassVar[dict[str, Any]] = {
        "qdrant_url": None,
        "qdrant_api_key": None,
        "qdrant_quantization": None,
        # Supervised qdrant server mode. ``qdrant_server`` opts the
        # resident service into spawning the pinned Rust qdrant binary
        # as a loopback child and routing stores at it. Server mode is
        # the assumed backend: an adversarial A/B on a 469k-chunk corpus
        # measured a ~54x end-to-end win, so the default points at the
        # mode that scales. Local mode stays a first-class explicit
        # opt-out via ``local_only``; ``qdrant_server`` itself remains
        # the redundant server-mode env knob. The server's HTTP port
        # defaults to one below the service port (8766); its gRPC
        # listener binds one below that. ``qdrant_binary`` overrides
        # binary resolution entirely (air-gapped escape hatch).
        # Server storage is shared and multi-root (per-root data is
        # namespaced collections inside it), so it lives under the
        # managed service directory, never a project data dir.
        "qdrant_server": True,
        # First-class local-backend opt-out. When true, the resident
        # service uses the per-project on-disk store regardless of the
        # server-mode default; it is the deliberate, trivially
        # selectable escape hatch for CI, offline, and small-project
        # hosts. Effective server mode is ``qdrant_server and not
        # local_only`` (see ``effective_server_mode``), so local-only
        # always wins over the server default.
        "local_only": False,
        "qdrant_port": 8765,
        "qdrant_binary": None,
        "qdrant_storage_dir": "~/.vaultspec-rag/qdrant-server/storage",
        # Scheduled storage maintenance (auto-prune). The daemon's hourly
        # maintenance tick reclaims time-confirmed dangling namespaces:
        # empty (zero-point) orphans after a continuous grace window,
        # point-bearing orphans after a longer window and only once a
        # snapshot archive succeeded. Grace clocks persist in the storage
        # manifest, unknown/unverifiable namespaces are never auto-touched,
        # and per-cycle reclaims are capped. The archive tree is bounded by
        # age and total size.
        "storage_autoprune": True,
        # Float, not int: fractional minutes are the test seam for
        # seconds-scale cadences, and env coercion is default-type-driven.
        "storage_autoprune_interval_minutes": 60.0,
        "storage_autoprune_grace_hours": 24.0,
        "storage_autoprune_grace_hours_data": 168.0,
        "storage_autoprune_archive_retention_days": 30.0,
        "storage_autoprune_archive_max_gb": 20.0,
        "storage_autoprune_max_per_cycle": 16,
        # Ephemeral idle-TTL tier: a temp-rooted namespace whose
        # persisted last_indexed stamp is older than this is treated as
        # dangling even though its root still exists - the leak signature
        # is a harness temp dir that outlives its usefulness but never
        # disappears. Runs through the same empty/data tiers, archive
        # gate, and per-cycle cap as orphan reclamation. 0 disables.
        "storage_autoprune_ephemeral_idle_hours": 72.0,
        # Geometry reconcile. Collections created before per-collection
        # preallocation was bounded keep their original segment target
        # forever, because collection creation is the only place the bound
        # was applied and it returns early for an existing collection. The
        # maintenance tick converges them in place: non-destructive, no
        # point movement, and measured to reclaim 63-84% per collection.
        # Capped per cycle so a large drifted backend converges over
        # several ticks instead of saturating disk in one.
        "storage_reconcile": True,
        "storage_reconcile_max_per_cycle": 4,
        # Per-collection convergence budget. A collection that has not
        # settled by then is reported as still converging and retried on a
        # later cycle - never as failed, and never with a reclaim figure.
        "storage_reconcile_budget_seconds": 300.0,
        "data_dir": ".vault/data/search-data",
        "qdrant_dir": "qdrant",
        "index_metadata_file": "index_meta.json",
        "code_index_metadata_file": "code_index_meta.json",
        "status_dir": "~/.vaultspec-rag",
        "log_file": "service.log",
        "graph_ttl_seconds": 300.0,
        "embedding_batch_size": 64,
        # Inner sub-batch size passed to SentenceTransformer.encode().
        # SentenceTransformer sorts each call's input by sequence
        # length, then processes ``encode_batch_size``-item sub-batches
        # of the sorted list. Vault inputs are heading-aware chunks
        # capped at ``vault_chunk_chars`` (~750 BPE tokens) and
        # length-sorted per slice, so padding waste is bounded and a
        # larger sub-batch keeps the tensor cores fed. The OOM backoff
        # in ``encode_documents`` halves this under memory pressure.
        # (The former value of 8 dated from whole-document inputs that
        # ranged from 200 to 8000 chars; #68 wall-clock work.)
        "embedding_encode_batch_size": 32,
        "max_embed_chars": 8000,
        # Hard cap on the sequence length the model is allowed to
        # process. ``max_embed_chars=8000`` truncates text to ~2000
        # tokens for typical Qwen3 BPE; capping ``max_seq_length`` at
        # 2048 prevents the model from advertising 32 k context, which
        # otherwise leaks into kernel-selection heuristics and wastes
        # attention memory on padded sequences.
        "embedding_max_seq_length": 2048,
        # Number of worker processes for parallel codebase chunking (#155).
        # tree-sitter AST chunking is CPU-bound and holds the GIL for both
        # parse and traverse, so a process pool (not threads) is required to
        # use multiple cores. ``0`` means "auto" - resolve to
        # ``os.process_cpu_count()`` at run time. ``1`` forces the serial
        # in-process path (useful for small trees, debugging, or environments
        # where spawning workers is undesirable).
        "index_chunk_workers": 0,
        # Inner encode sub-batch for the CODEBASE path, decoupled from the
        # vault path's small ``embedding_encode_batch_size`` (#155). Code
        # chunks are short (<=1500 chars) and length-sorted, so the padding
        # pathology that justifies 8 for variable-length vault docs does not
        # apply; a larger sub-batch keeps the GPU's tensor cores fed and
        # raises encode throughput. The OOM-backoff in ``encode_documents``
        # still halves this on memory pressure.
        "embedding_code_encode_batch_size": 32,
        # Inner encode sub-batch for the DOCUMENT path, decoupled from the vault
        # and code sub-batches. Document fragments are bounded at the model's
        # full sequence window (~2048 tokens), roughly 2.7x the vault chunk's
        # token volume, so a batch of 32 window-sized fragments is far more
        # activation memory than the vault batch was sized for. A smaller
        # sub-batch keeps the per-forward working set within the indexing
        # budget; the OOM-backoff in ``encode_documents`` still halves it under
        # pressure.
        "embedding_document_encode_batch_size": 12,
        # Flush the CUDA caching allocator every N codebase embed slices
        # instead of every slice (#155). Per-slice flushing (the #68 RSS fix)
        # forces a device sync each iteration; throttling to every N slices
        # removes most of those syncs while still bounding allocator growth to
        # N slices' worth of transient activations. ``1`` restores per-slice
        # flushing.
        "index_cache_flush_slices": 8,
        # Flush cadences for the vault and document embed paths, mirroring
        # the codebase throttle above. Both DEFAULT TO 1 (flush every
        # slice), which is byte-for-byte the historical behavior of these
        # paths. Raising either is measurement-gated: per-slice flushing
        # may be load-bearing against allocator fragmentation on a CUDA
        # ceiling that counts reserved memory, so flip only after peak
        # reserved-memory and OOM validation on real full rebuilds in a
        # coordinated GPU window.
        "vault_cache_flush_slices": 1,
        "document_cache_flush_slices": 1,
        # Minimum total source bytes before AUTO worker selection
        # (``index_chunk_workers=0``) engages the process pool (#155). Spawn
        # workers cost ~0.3s each to start, so on small/medium trees the pool
        # is slower than serial chunking; below this threshold the auto path
        # stays serial. An explicit ``index_chunk_workers`` >= 1 bypasses this
        # gate. 8 MiB sits comfortably above the measured serial/parallel
        # crossover while still parallelising any large codebase.
        "index_parallel_min_bytes": 8 * 1024 * 1024,
        # Dense-encoder backend (#155). "torch" is the
        # default and only validated path on this CUDA-13 build; "onnx" is
        # experimental and opt-in (requires sentence-transformers[onnx-gpu] in
        # an onnxruntime-compatible CUDA environment) and degrades to torch on
        # any failure. ``dense_onnx_file`` is the cached O4 model relative path.
        "dense_backend": "torch",
        "dense_onnx_file": "onnx/model_O4.onnx",
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedding_dimension": 1024,
        "sparse_enabled": True,
        "sparse_model": "naver/splade-v3",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_batch_size": 32,
        # Token bound for CrossEncoder inputs. The reranker scores
        # token-bounded full candidate content; its tokenizer truncates
        # each (query, content) pair to this length. 1024 covers a
        # 3000-char vault chunk or a 1500-char code chunk plus query.
        "reranker_max_length": 1024,
        # Heading-aware vault chunk budget in characters. One Qdrant
        # point per chunk; ~3000 chars is ~750 BPE tokens, well inside
        # the 2048-token encoder cap with the title header prepended.
        "vault_chunk_chars": 3000,
        # Intent-aware vault ranking. The prior multiplies each vault
        # result's calibrated rerank score by a per-(doc_type, status)
        # weight from the active intent profile (see
        # ``intent_weight_profiles``), then a per-type cap bounds how many
        # results of one doc_type may occupy the returned page. Default
        # intent is orientation (surfaces active ADRs); ``debug`` inverts
        # toward exec/audit. Set ``vault_intent_ranking_enabled`` false to
        # restore the bare-reranker ordering. ``vault_intent_type_cap=0``
        # disables the cap.
        "vault_intent_default": "orientation",
        "vault_intent_ranking_enabled": True,
        "vault_intent_type_cap": 4,
        # Worker-thread pool partitioning: interactive searches and
        # long-running index jobs draw from separate capacity limiters
        # so reindex runs can never exhaust the threads that serve
        # searches. Saturation beyond a limiter queues callers.
        "search_concurrency": 16,
        "index_job_concurrency": 4,
        # Encode-seam vector reuse. When indexing a root, the single
        # consumer thread may retrieve already-computed dense and sparse
        # vectors by deterministic point id from sibling donor namespaces
        # and adopt them for chunks whose stored payload content matches
        # byte-for-byte, GPU-encoding only the misses - a fork of an
        # already-indexed tree then skips the encode that dominates the
        # rebuild. Default on; set false to disable every donor lookup and
        # encode every chunk exactly as before - the paranoia escape hatch
        # and the A/B lever that restores baseline behaviour in one flip.
        "index_reuse_enabled": True,
        "mcp_port": 8766,
        "log_level": "WARNING",
        "service_idle_ttl_seconds": 1800,
        "service_max_projects": 16,
        # Client-side request bounds, in seconds. The search bound is generous
        # because a cold rebuild-class query can sit behind model load; the
        # admin bound covers lifecycle calls that should answer promptly.
        "service_search_timeout_seconds": 300.0,
        "service_admin_timeout_seconds": 30.0,
        # Readiness bound for the managed qdrant child. A large store was
        # measured opening in ~131 s, so this is generous by design; operators
        # with larger stores raise it rather than patching the supervisor.
        "qdrant_ready_timeout_seconds": 300.0,
        # Per-source retention policy for every operational log managed by the
        # resident service. Service and Qdrant each receive this full budget;
        # the values are not divided across sources.
        "managed_log_max_bytes": 10485760,
        "managed_log_backup_count": 5,
        # Nonterminal records are exact-addressable and therefore cannot be
        # evicted. Refuse excess admission at this bound instead of growing an
        # unbounded active registry or silently losing controllable work.
        "job_max_nonterminal": 64,
        # Maximum time for service shutdown to wait for cooperative indexing
        # unwind. This accommodates the code indexer's existing bounded
        # producer/consumer drain while ensuring the daemon never waits
        # indefinitely for acknowledgement.
        "job_shutdown_timeout_seconds": 300.0,
        # Preserve the current operation-level store behavior as explicit
        # policy. Later run-policy integration clamps each attempt and sleep
        # to the remaining durable no-progress budget.
        "store_operation_timeout_seconds": 120.0,
        "store_write_retry_attempts": 5,
        "store_write_retry_base_seconds": 0.5,
        "store_write_retry_max_seconds": 8.0,
        # Resource-bounded indexing. A durable unit is one file segment; the
        # weighted queue must admit at least one segment. Byte bounds include
        # text, vector, sparse, payload, and Python-container estimates.
        "index_segment_max_chunks": 64,
        "index_segment_max_bytes": 8 * 1024 * 1024,
        "index_queue_max_chunks": 512,
        "index_queue_max_bytes": 128 * 1024 * 1024,
        # Liveness is time since storage-confirmed durable progress, never a
        # total run deadline. Fifteen minutes contains a failed write ladder
        # while allowing healthy long-running indexes to continue indefinitely.
        "index_no_progress_timeout_seconds": 900.0,
        # Persistent watcher retry/circuit policy. Jitter is a symmetric
        # fraction applied to the bounded exponential delay.
        "watch_retry_base_seconds": 30.0,
        "watch_retry_max_seconds": 1800.0,
        "watch_retry_jitter_fraction": 0.1,
        "watch_circuit_failure_threshold": 3,
        # Absolute admitted process ceilings. The per-run budget may freeze a
        # lower ceiling relative to its starting baseline. The allocator cap
        # preserves device headroom for concurrent search before model load.
        "index_rss_ceiling_mb": 16384.0,
        # CUDA ceiling override. ``0`` means auto-derive from the real device:
        # total device memory minus ``index_cuda_headroom_mb``. A positive value
        # is an authoritative operator override that raises OR lowers the
        # effective ceiling, replacing the former one-way clamp against a fixed
        # 12 GiB profile constant that a 16 GiB card could never raise.
        "index_cuda_ceiling_mb": 0.0,
        # Memory reserved below the device total when the CUDA ceiling is
        # auto-derived: leaves room for the driver, concurrent search, and
        # allocator fragmentation. On a 16 GiB card this yields a ~14 GiB
        # indexing ceiling instead of the flat 12 GiB.
        "index_cuda_headroom_mb": 2048.0,
        "index_cuda_allocator_fraction": 0.8,
        # Named profile definitions and corpus dimensions live in
        # ``index_profiles``; this selects the service default.
        "index_support_profile": "managed-service",
        # Filesystem-watcher / auto-reindex knobs (#143/#144). The
        # resident service auto-reindexes on file change; ``watch_enabled``
        # is the sole opt-out (``False`` => pull-only service). The
        # ``debounce_ms`` and ``cooldown_s`` knobs tune responsiveness;
        # ``0`` means "no delay", not "disabled".
        "watch_enabled": True,
        "watch_debounce_ms": 2000,
        "watch_cooldown_s": 30.0,
        # Document-preprocessing two-state.
        # ``default`` runs a root's ``.vaultragpreprocess.toml`` rules directly
        # for any root: a root's preprocess config is repo-authored code and
        # executes with the operator's privileges, so no trust check gates it.
        # ``off`` is the kill switch (no rules ever load). Env resolution lives
        # in the ``preprocess_mode`` property: ``VAULTSPEC_RAG_PREPROCESS=off``
        # forces off, unset means default.
        "preprocess_mode": "default",
        # Document-preprocessing hook knobs (#185). The source-size cap
        # (``_MAX_FILE_SIZE``) is relaxed for files matched by a preprocess
        # rule; this cap instead bounds the *emitted* text a preprocessor
        # produces, so a 12 MB PDF that distils to 40 KB indexes while a
        # runaway extractor that emits tens of MB is skipped.
        "preprocess_max_emitted_bytes": 10 * 1024 * 1024,
        # Document split budget. The effective character bound for one
        # document chunk derives from the dense model's token window
        # (``embedding_max_seq_length``) multiplied by this declared
        # chars-per-token ratio, so the limit tracks a model change instead
        # of silently drifting as a hardcoded character count would. The
        # ratio is deliberately conservative (typical English BPE runs ~4
        # chars per token; token-dense content such as tables and numbers
        # runs lower), so a full chunk stays inside the window rather than
        # being truncated by the encoder. The overlap keeps a fragment
        # boundary from severing context mid-sentence.
        "document_chunk_chars_per_token": 3,
        "document_chunk_overlap_chars": 256,
        # Strip HTML tags to plain text before chunking ``.html`` sources
        # (#185 adjacent ask). Default on: raw markup wastes ~1/3 of each
        # chunk's budget and pollutes results with navigation boilerplate.
        # Falls back to raw-markup chunking on any parse error.
        "html_strip": True,
        # Code-search noise profile. Domains are
        # the labels from ``_domain.classify_domain``. ``hide`` domains are
        # dropped from code results by default (reversible per call with
        # ``--include-domain``); ``demote`` domains stay visible but take a
        # ``code_noise_demote_penalty`` score subtraction so production code
        # ranks first. Shipped defaults hide the duplicate/derivative trees
        # (agent worktree clones, generated output) and demote tests, docs,
        # locale tables, and vendored third-party code. Comma-separated strings
        # so a project config or env var can override the set.
        "code_noise_hide_domains": "worktree,generated",
        "code_noise_demote_domains": "tests,docs,locale,vendored",
        # Score subtraction applied to a demoted code result (calibrated rerank
        # scores live in [0, 1]); large enough to sink noise below production
        # near-ties, small enough to leave a demoted hit recoverable and
        # visible. ``0`` disables demotion.
        "code_noise_demote_penalty": 0.3,
        # Collapse near-duplicate locale-variant code results by default
        # (``locales/{en,es,ca,hu}.yml`` -> one representative). Conservative:
        # only recognised locale shapes within a tie window collapse.
        "dedup_locales_default": True,
    }

    # Intent-aware vault ranking weight profiles. Each profile maps
    # a doc_type and (for ADRs) a status to a multiplier applied to the
    # calibrated rerank score. A type or status absent from a profile defaults
    # to 1.0 (the prior leaves it unchanged). Orientation lifts active decisions
    # and grounding and demotes implementation artifacts and inactive ADRs;
    # debug inverts toward exec and audit and stays status-neutral. These are
    # the tunable, inspectable knobs the validation harness sweeps; only the
    # ``orientation`` and ``debug`` profiles ship.
    _INTENT_WEIGHT_PROFILES: ClassVar[dict[str, dict[str, dict[str, float]]]] = {
        "orientation": {
            "type": {
                "adr": 1.0,
                "audit": 1.0,
                "research": 0.85,
                "reference": 0.85,
                "plan": 0.6,
                "exec": 0.4,
            },
            "status": {
                "accepted": 1.0,
                "unknown": 1.0,
                "proposed": 0.6,
                "superseded": 0.3,
                "rejected": 0.3,
                "deprecated": 0.3,
            },
        },
        "debugging": {
            "type": {
                "exec": 1.0,
                "audit": 0.9,
                "plan": 0.7,
                "research": 0.6,
                "reference": 0.6,
                "adr": 0.6,
            },
            "status": {},
        },
    }

    @property
    def intent_weight_profiles(self) -> dict[str, dict[str, dict[str, float]]]:
        """Return the intent-aware ranking weight profiles (read-only view)."""
        return self._INTENT_WEIGHT_PROFILES

    @staticmethod
    def _parse_domain_set(raw: object) -> frozenset[str]:
        """Parse a comma-separated domain string into a validated set.

        Unknown labels are dropped (a typo cannot silently widen the noise
        policy); ``prod`` is never a noise domain and is dropped if listed.
        """
        from ._domain import NOISE_DOMAINS

        if not isinstance(raw, str):
            return frozenset()
        wanted = {tok.strip().lower() for tok in raw.split(",") if tok.strip()}
        return frozenset(wanted & NOISE_DOMAINS)

    @property
    def code_noise_hide_domains(self) -> frozenset[str]:
        """Domains dropped from code results by default (reversible per call)."""
        return self._parse_domain_set(
            self._resolve_rag_default("code_noise_hide_domains")
        )

    @property
    def code_noise_demote_domains(self) -> frozenset[str]:
        """Domains demoted (not hidden) in code results by default.

        A domain listed in both sets is hidden, not merely demoted - hide wins -
        so the two sets never double-act on one result.
        """
        demote = self._parse_domain_set(
            self._resolve_rag_default("code_noise_demote_domains")
        )
        return demote - self.code_noise_hide_domains

    def __init__(
        self,
        base: BaseConfig,
        rag_overrides: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the wrapper around an existing config.

        Args:
            base: The base ``VaultSpecConfig`` to wrap.
            rag_overrides: Optional CLI-supplied values for RAG settings keys.

        Returns:
            None.

        Raises:
            ValueError: If any setting is malformed or out of range. Raising
                here means a daemon refuses to start on a bad value instead of
                failing later, mid-flight, on the first read of that knob.
        """
        self._base = base
        self._rag_overrides = {
            key: value
            for key, value in (rag_overrides or {}).items()
            if key in self._RAG_DEFAULTS
        }
        self._validate_settings()

    # Settings whose only constraint is a range resolve through the generic
    # path and declare that range in ``_SETTING_BOUNDS``. The properties below
    # exist only where a value is constrained by ANOTHER setting, which a
    # per-key range cannot express.

    def _store_write_retry_bounds(self) -> tuple[float, float]:
        base = float(self._resolve_rag_default("store_write_retry_base_seconds"))
        maximum = float(self._resolve_rag_default("store_write_retry_max_seconds"))
        if maximum < base:
            msg = (
                "store_write_retry_max_seconds must be greater than or equal to "
                f"store_write_retry_base_seconds, got maximum={maximum}, base={base}"
            )
            raise ValueError(msg)
        return base, maximum

    @property
    def store_write_retry_base_seconds(self) -> float:
        """Return the initial store-write retry delay, never above the maximum."""
        return self._store_write_retry_bounds()[0]

    @property
    def store_write_retry_max_seconds(self) -> float:
        """Return the maximum store-write retry delay, never below the base."""
        return self._store_write_retry_bounds()[1]

    def _index_chunk_bounds(self) -> tuple[int, int]:
        segment = int(self._resolve_rag_default("index_segment_max_chunks"))
        queue = int(self._resolve_rag_default("index_queue_max_chunks"))
        if queue < segment:
            msg = (
                "index_queue_max_chunks must be greater than or equal to "
                f"index_segment_max_chunks, got queue={queue}, segment={segment}"
            )
            raise ValueError(msg)
        return segment, queue

    def _index_byte_bounds(self) -> tuple[int, int]:
        segment = int(self._resolve_rag_default("index_segment_max_bytes"))
        queue = int(self._resolve_rag_default("index_queue_max_bytes"))
        if queue < segment:
            msg = (
                "index_queue_max_bytes must be greater than or equal to "
                f"index_segment_max_bytes, got queue={queue}, segment={segment}"
            )
            raise ValueError(msg)
        return segment, queue

    @property
    def index_segment_max_chunks(self) -> int:
        """Return the chunk bound for one durable file segment."""
        return self._index_chunk_bounds()[0]

    @property
    def index_queue_max_chunks(self) -> int:
        """Return the queue chunk budget, never smaller than one segment."""
        return self._index_chunk_bounds()[1]

    @property
    def index_segment_max_bytes(self) -> int:
        """Return the byte bound for one durable file segment."""
        return self._index_byte_bounds()[0]

    @property
    def index_queue_max_bytes(self) -> int:
        """Return the queue byte budget, never smaller than one segment."""
        return self._index_byte_bounds()[1]

    @property
    def document_chunk_overlap_chars(self) -> int:
        """Return the overlap carried across document chunk bounds.

        Kept off the generic path because the ceiling is not a fixed number
        but the derived chunk budget, itself the product of two other
        settings: an overlap at or above it would consume a whole chunk and
        never advance the split. A per-key range cannot express that.
        """
        overlap = int(self._resolve_rag_default("document_chunk_overlap_chars"))
        budget = self.document_chunk_chars
        if overlap >= budget:
            msg = (
                "document_chunk_overlap_chars must be smaller than the derived "
                f"document chunk budget, got overlap={overlap}, "
                f"budget={budget}"
            )
            raise ValueError(msg)
        return overlap

    @property
    def document_chunk_chars(self) -> int:
        """Return the document split budget derived from the model window.

        The budget is the dense model's token window multiplied by the
        declared chars-per-token ratio, never a hardcoded character count,
        so it tracks a model change instead of silently drifting. Derived,
        not configured: it has no default and no environment variable of its
        own, only the two settings it multiplies.
        """
        return int(self.embedding_max_seq_length) * int(
            self.document_chunk_chars_per_token
        )

    def _watch_retry_bounds(self) -> tuple[float, float]:
        base = float(self._resolve_rag_default("watch_retry_base_seconds"))
        maximum = float(self._resolve_rag_default("watch_retry_max_seconds"))
        if maximum < base:
            msg = (
                "watch_retry_max_seconds must be greater than or equal to "
                f"watch_retry_base_seconds, got maximum={maximum}, base={base}"
            )
            raise ValueError(msg)
        return base, maximum

    @property
    def watch_retry_base_seconds(self) -> float:
        """Return the initial watcher retry delay, never above the maximum."""
        return self._watch_retry_bounds()[0]

    @property
    def watch_retry_max_seconds(self) -> float:
        """Return the maximum watcher retry delay, never below the base."""
        return self._watch_retry_bounds()[1]

    def _coerce_env(self, name: str, raw: str, source: EnvVar) -> object:
        """Parse an environment string into the settings key's declared type.

        Args:
            name: The settings key being resolved.
            raw: The raw environment value.
            source: The environment variable it was read from.

        Returns:
            The parsed value.

        Raises:
            ValueError: If *raw* does not parse as the key's type.
        """
        default = self._RAG_DEFAULTS[name]
        if isinstance(default, bool):
            token = raw.strip().lower()
            if token in _TRUE_TOKENS:
                return True
            if token in _FALSE_TOKENS:
                return False
            raise _rejection(name, _BOOL_SHAPE, raw, source)
        bound = _SETTING_BOUNDS.get(name)
        if bound is not None:
            try:
                return bound.parse(raw)
            except ValueError:
                raise _rejection(name, bound.shape, raw, source) from None
        return raw

    def _checked(self, name: str, value: object, source: EnvVar | None) -> object:
        """Return *value* narrowed to the key's declared range.

        Args:
            name: The settings key being resolved.
            value: The resolved value, from any source.
            source: The environment variable it came from, when it came from one.

        Returns:
            The value narrowed to the declared type, or unchanged when the key
            declares no range.

        Raises:
            ValueError: If the key declares a range and *value* is outside it.
        """
        bound = _SETTING_BOUNDS.get(name)
        if bound is None:
            return value
        if not bound.admits(value):
            raise _rejection(name, bound.shape, value, source)
        return bound.narrow(value)

    def _raw_rag_setting(self, name: str) -> tuple[object, EnvVar | None]:
        """Resolve *name* through the precedence chain without validating it."""
        if name in self._rag_overrides:
            return self._rag_overrides[name], None
        # 1. CLI override via base config
        try:
            return getattr(self._base, name), None
        except AttributeError as exc:
            # Base config doesn't carry RAG-specific knob; fall
            # through to env var, then to module default. Debug
            # so the swallow stays observable.
            logger.debug(
                "config attr %s not on base; fall through: %s",
                name,
                exc,
            )

        # 2. Env var override
        env_key = _ENV_OVERRIDE_MAP.get(name)
        if env_key is not None:
            env_val = os.environ.get(env_key.value)
            if env_val is not None:
                default = self._RAG_DEFAULTS[name]
                if isinstance(default, str) and not env_val.strip():
                    # An empty/whitespace string override for a path-like knob is
                    # a footgun - e.g. ``VAR="$UNSET"`` exports ``""`` - and
                    # ``Path("").expanduser()`` is the cwd, which would repoint
                    # the managed-dir blast radius (delete/clean) into the working
                    # dir. Treat it as absent (fall through to the module
                    # default), matching the persistence helpers' ``or DEFAULT``.
                    # The sole silent-fallback carve-out; every other malformed
                    # value is rejected.
                    pass
                else:
                    return self._coerce_env(name, env_val, env_key), env_key

        # 2.5. Persisted runtime selection (local_only only). When
        # ``install --local-only`` wrote the marker, a later
        # ``server start`` with no flag and no env honours it. Precedence
        # is explicit env/flag (above) > persisted config (here) >
        # module default (below), so an operator who re-passes the flag or
        # sets the env always overrides the persisted choice.
        if name == "local_only":
            persisted = read_persisted_local_only()
            if persisted is not None:
                return persisted, None

        # 3. Default
        return self._RAG_DEFAULTS[name], None

    def _resolve_rag_default(self, name: str) -> Any:
        value, source = self._raw_rag_setting(name)
        return self._checked(name, value, source)

    def _validate_settings(self) -> None:
        """Reject every unusable setting at construction, all of them at once.

        Reporting the whole list beats failing on the first: an operator
        editing a deployment environment fixes one round of mistakes, not one
        mistake per restart. Only keys that declare a constraint are swept -
        a free-form path or model name has nothing to check - plus the
        cross-setting relations no per-key range can express.

        Raises:
            ValueError: If any setting is malformed or out of range.
        """
        problems: list[str] = []

        def record(exc: ValueError) -> None:
            # The relation checks re-resolve keys the sweep already visited, so
            # one bad value can surface twice. Report it once.
            message = str(exc)
            if message not in problems:
                problems.append(message)

        keys = [
            *_SETTING_BOUNDS,
            *(
                key
                for key, default in self._RAG_DEFAULTS.items()
                if isinstance(default, bool)
            ),
        ]
        for key in keys:
            try:
                self._resolve_rag_default(key)
            except ValueError as exc:
                record(exc)
        relations = (
            self._store_write_retry_bounds,
            self._index_chunk_bounds,
            self._index_byte_bounds,
            self._watch_retry_bounds,
            lambda: self.document_chunk_overlap_chars,
        )
        for relation in relations:
            try:
                relation()
            except ValueError as exc:
                record(exc)

        if not problems:
            return
        if len(problems) == 1:
            raise ValueError(problems[0])
        listed = "\n".join(f"  - {problem}" for problem in problems)
        raise ValueError(f"{len(problems)} unusable settings:\n{listed}")

    def effective_server_mode(self) -> bool:
        """Return whether the supervised server backend is in effect.

        The supervised Qdrant server is the assumed backend
        (``qdrant_server`` defaults true), and ``local_only`` is the
        first-class opt-out that always wins: effective server mode is
        ``qdrant_server and not local_only``. Callers selecting the
        store backend MUST consult this rather than reading
        ``qdrant_server`` directly, so the local-only escape hatch is
        honoured at every selection point.

        Returns:
            ``True`` when the resident service should supervise the
            Qdrant child and route stores at it; ``False`` when the
            per-project on-disk store should be used.
        """
        return bool(self.qdrant_server) and not bool(self.local_only)

    @property
    def preprocess_mode(self) -> PreprocessMode:
        """Resolve the two-state document-preprocessing mode.

        Kept off the generic override map because this is a transform, not an
        override. ``VAULTSPEC_RAG_PREPROCESS`` is a kill switch: its value is
        not the setting's value, only ``off`` means anything, and it has to
        beat a CLI override that the generic path deliberately ranks ABOVE the
        environment - an operator must always be able to silence a root's
        rules. Reading it live also lets a flag forwarded into the daemon
        environment take effect without rebuilding the config. Resolution is:

        - ``VAULTSPEC_RAG_PREPROCESS=off`` forces ``off``, beating everything.
        - otherwise the base-config/CLI override, then the module default
          (``default``, on).

        An unrecognised configured mode degrades to ``default`` with a warning
        instead of being rejected, the one place this module bends its own
        rule. Rejecting here would refuse to start the daemon over a knob whose
        safe reading is the shipped one, and the degrade is announced rather
        than silent. The value cannot arrive from the environment anyway - the
        kill switch is the only env input - so an operator typo cannot reach
        this branch.

        Returns:
            One of ``"default"`` or ``"off"``.
        """
        off_raw = os.environ.get(EnvVar.PREPROCESS.value)
        if off_raw is not None and off_raw.strip().lower() == "off":
            return "off"
        configured = str(self._resolve_rag_default("preprocess_mode"))
        if configured not in _VALID_PREPROCESS_MODES:
            logger.warning(
                "unrecognised preprocess_mode %r; falling back to 'default'",
                configured,
            )
            return "default"
        return cast("PreprocessMode", configured)

    def __getattr__(self, name: str) -> Any:
        """Return a config attribute, checking env overrides then defaults.

        Resolution order for known RAG keys:
        1. Base config (may contain CLI overrides)
        2. Environment variable (via ``_ENV_OVERRIDE_MAP``)
        3. ``_RAG_DEFAULTS`` fallback

        Whichever source wins, the value is coerced and range-checked before it
        is returned, so no access path can hand back an unvalidated setting.

        Args:
            name: The attribute name to look up.

        Returns:
            The resolved attribute value.

        Raises:
            AttributeError: If *name* is not a RAG default and is
                also missing from the base config.
            ValueError: If the resolved value is malformed or out of range.
        """
        if name in self._RAG_DEFAULTS:
            return self._resolve_rag_default(name)

        return getattr(self._base, name)

    @classmethod
    def from_environment(
        cls,
        overrides: dict[str, Any] | None = None,
    ) -> VaultSpecConfigWrapper:
        """Create a wrapped config from the current environment.

        Args:
            overrides: Optional key/value pairs that override
                environment-derived settings.

        Returns:
            A new ``VaultSpecConfigWrapper`` instance.
        """
        base = get_base_config(overrides)
        return cls(base, overrides)


_cached_config: VaultSpecConfigWrapper | None = None


def rag_default(key: str) -> Any:
    """Return the shipped default for *key*, ignoring env and CLI overrides.

    The settings defaults are the one home for these values. Call sites that
    need the fallback for a leniently-parsed setting read it from here rather
    than restating the number, so a default can never drift between the
    settings object and the module that consumes it.

    Args:
        key: A ``_RAG_DEFAULTS`` settings key.

    Returns:
        The shipped default value for that key.

    Raises:
        KeyError: When *key* is not a known settings key.
    """
    return VaultSpecConfigWrapper._RAG_DEFAULTS[key]  # pyright: ignore[reportPrivateUsage]


def get_config(
    overrides: dict[str, Any] | None = None,
) -> VaultSpecConfigWrapper:
    """Return a cached ``VaultSpecConfigWrapper`` singleton.

    When called without *overrides*, returns the existing cached
    instance (creating one if necessary).  When called with
    *overrides*, replaces the cached instance with a freshly
    built config that incorporates the given overrides.

    Args:
        overrides: Optional key/value pairs forwarded to
            ``get_base_config()`` to override environment defaults.

    Returns:
        The cached ``VaultSpecConfigWrapper`` instance.
    """
    global _cached_config
    if overrides is not None:
        base = get_base_config(overrides)
        _cached_config = VaultSpecConfigWrapper(base, overrides)
        return _cached_config
    if _cached_config is None:
        base = get_base_config()
        _cached_config = VaultSpecConfigWrapper(base)
    return _cached_config


def reset_config() -> None:
    """Clear the cached config singleton (for testing).

    Args:
        None.

    Returns:
        None.
    """
    global _cached_config
    _cached_config = None


# Keep the persistence-layer default in lock-step with the class default so the
# local-only marker lands in the same managed directory the config resolves. An
# explicit raise (not assert) so the invariant holds under python -O, where a
# silent drift would write the marker to a directory the resolver never reads.
# Same-module invariant check: the class-private defaults table is read here to
# fail fast at import if the persistence-layer default drifts from the config default.
_rag_status_dir_default: object = VaultSpecConfigWrapper._RAG_DEFAULTS[  # pyright: ignore[reportPrivateUsage]
    "status_dir"
]
if _rag_status_dir_default != _STATUS_DIR_DEFAULT:
    raise RuntimeError(
        "status_dir default drifted between persistence layer and config defaults"
    )


# Every numeric setting must declare its admissible range, and every declared
# range must belong to a real setting. Checked at import so a new knob cannot
# land without a range - the omission that let a negative TTL and a zero batch
# size through - and so a renamed key cannot leave an orphaned entry behind.
_all_defaults: dict[str, object] = VaultSpecConfigWrapper._RAG_DEFAULTS  # pyright: ignore[reportPrivateUsage]
_unbounded_numeric = sorted(
    key
    for key, value in _all_defaults.items()
    if isinstance(value, (int, float))
    and not isinstance(value, bool)
    and key not in _SETTING_BOUNDS
)
if _unbounded_numeric:
    raise RuntimeError(
        "numeric settings declare no admissible range: " + ", ".join(_unbounded_numeric)
    )
_orphaned_bounds = sorted(set(_SETTING_BOUNDS) - set(_all_defaults))
if _orphaned_bounds:
    raise RuntimeError(
        "bounds declared for unknown settings: " + ", ".join(_orphaned_bounds)
    )
