"""Configuration defaults validation schema."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

from .._env_values import rejection
from ._types import VALID_INDEX_SUPPORT_PROFILES, EnvVar


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


def setting_rejection(
    key: str, shape: str, value: object, source: EnvVar | None
) -> ValueError:
    """Build this module's rejection, naming both the variable and the key.

    Args:
        key: The settings key that failed.
        shape: The human phrase describing what was expected.
        value: The offending value, rendered for the operator.
        source: The environment variable the value came from, when it did.

    Returns:
        A ``ValueError`` naming the variable, the key, the value and the shape.
    """
    where = key if source is None else f"{source.value} ({key})"
    return rejection(where, shape, value)


# Mapping from _RAG_DEFAULTS key → EnvVar member for env override lookup.
ENV_OVERRIDE_MAP: dict[str, EnvVar] = {
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
    "index_rss_ceiling_mib": EnvVar.INDEX_RSS_CEILING_MIB,
    "index_cuda_ceiling_mib": EnvVar.INDEX_CUDA_CEILING_MIB,
    "index_cuda_headroom_mib": EnvVar.INDEX_CUDA_HEADROOM_MIB,
    "index_cuda_allocator_fraction": EnvVar.INDEX_CUDA_ALLOCATOR_FRACTION,
    "gpu_admission_floor_mib": EnvVar.GPU_ADMISSION_FLOOR_MIB,
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
    "embedding_encode_token_budget": EnvVar.EMBEDDING_ENCODE_TOKEN_BUDGET,
    "embedding_encode_chars_per_token": EnvVar.EMBEDDING_ENCODE_CHARS_PER_TOKEN,
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
    # Automatic shrunken-index repair knob.
    "integrity_auto_repair": EnvVar.INTEGRITY_AUTO_REPAIR,
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
SETTING_BOUNDS: dict[str, _SettingBound] = {
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
    "index_rss_ceiling_mib": _POSITIVE_NUMBER,
    "index_cuda_ceiling_mib": _NON_NEGATIVE_NUMBER,
    "index_cuda_headroom_mib": _POSITIVE_NUMBER,
    "index_cuda_allocator_fraction": _OPEN_UNIT_INTERVAL,
    # Model-load admission floor, in MiB. Zero is admitted and means derive the
    # floor from the configured workload's declared CUDA demand, the way the
    # CUDA ceiling above treats its own zero; a positive value overrides that
    # derivation for one card. Negatives are refused, having no reading.
    "gpu_admission_floor_mib": _NON_NEGATIVE_INT,
    "index_support_profile": _ChoiceBound(
        "one of " + ", ".join(sorted(VALID_INDEX_SUPPORT_PROFILES)),
        frozenset(VALID_INDEX_SUPPORT_PROFILES),
    ),
    # Embedding and reranking throughput. A zero batch encodes nothing.
    "embedding_dimension": _POSITIVE_INT,
    "embedding_batch_size": _POSITIVE_INT,
    "embedding_encode_batch_size": _POSITIVE_INT,
    "embedding_code_encode_batch_size": _POSITIVE_INT,
    "embedding_document_encode_batch_size": _POSITIVE_INT,
    "embedding_encode_token_budget": _POSITIVE_INT,
    "embedding_encode_chars_per_token": _POSITIVE_INT,
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
