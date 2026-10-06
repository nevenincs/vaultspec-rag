"""Configuration defaults validation schema."""

from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

from vaultspec_core.env_values import rejection

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
        """Return *value* as this bound's declared type.

        Only reached through ``checked_setting``, which calls
        ``admits`` first; ``admits`` is what establishes ``value`` is an
        ``int`` (or ``int | float``) here, since this method has no isinstance
        check of its own.
        """
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
        """Return the normalised choice name.

        Only reached through ``checked_setting``, which calls
        ``admits`` first; ``admits`` is what establishes ``value`` is a
        ``str`` here, since this method has no isinstance check of its own.
        """
        return cast("str", value).strip().lower()


def comma_separated(raw: str) -> tuple[str, ...]:
    """Split a list-valued setting into its entries.

    Entries are separated by commas, stripped and case-folded; an empty entry
    is dropped, so a trailing comma or doubled separator is not an entry.
    Every list-valued setting is tokenised here, so the same text means the
    same list whichever setting carries it.
    """
    return tuple(token.strip().lower() for token in raw.split(",") if token.strip())


_HOST_NAME = re.compile(
    r"(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
)


def _names_a_host(host: str) -> bool:
    """Return whether *host* is a host name or an address literal."""
    if _HOST_NAME.fullmatch(host):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _HttpsUrlBound:
    """The admissible shape for a settings key naming a download source.

    A source is fetched over TLS or not at all, so only ``https`` is admitted.
    Credentials are refused because the value is echoed in diagnostics, and a
    query or fragment because the consumer appends a path to the value.

    The host has to be one a connection could be opened to: a host name or an
    address literal, with no control character or space anywhere in the
    value, and a port that is not zero. None of those could reach a server,
    and refusing them here names the setting instead of leaving the operator
    with a connection error that names nothing.
    """

    shape: str

    def parse(self, raw: str) -> object:
        """Return environment text unchanged; narrowing normalises it."""
        return raw

    def admits(self, value: object) -> bool:
        """Return whether *value* is an HTTPS URL a path can be appended to."""
        if not isinstance(value, str):
            return False
        text = value.strip()
        if any(char.isspace() or not char.isprintable() for char in text):
            return False
        try:
            parts = urlsplit(text)
            # Reading the port is what validates it: a non-numeric or
            # out-of-range one raises here rather than at the first request.
            port = parts.port
        except ValueError:
            return False
        return (
            parts.scheme == "https"
            and _names_a_host(parts.hostname or "")
            and port != 0
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
        )

    def narrow(self, value: object) -> object:
        """Return the URL without surrounding whitespace or a trailing slash.

        Only reached through ``checked_setting``, which calls ``admits``
        first; ``admits`` is what establishes ``value`` is a ``str`` here.
        """
        return cast("str", value).strip().rstrip("/")


@dataclass(frozen=True, slots=True)
class _HostListBound:
    """The admissible shape for a settings key naming a set of hosts.

    Each entry is compared against the host of a URL, so it is a bare host
    name: an entry carrying a scheme, a port, a path or a wildcard would never
    equal one and is refused rather than silently matching nothing. An empty
    list is refused for the same reason - it reads as a pin and admits nothing.
    """

    shape: str

    def parse(self, raw: str) -> object:
        """Return environment text unchanged; narrowing normalises it."""
        return raw

    def admits(self, value: object) -> bool:
        """Return whether *value* lists at least one host, and only hosts."""
        if not isinstance(value, str):
            return False
        hosts = comma_separated(value)
        return bool(hosts) and all(_HOST_NAME.fullmatch(host) for host in hosts)

    def narrow(self, value: object) -> object:
        """Return the hosts as a set of lower-cased names.

        Only reached through ``checked_setting``, which calls ``admits``
        first; ``admits`` is what establishes ``value`` is a ``str`` here.
        """
        return frozenset(comma_separated(cast("str", value)))


@dataclass(frozen=True, slots=True)
class _HexBound:
    """The admissible shape for a settings key holding a hexadecimal id.

    A digest, or the id of a commit: a fixed number of hexadecimal digits and
    nothing else. The key is optional, so an absent value is admitted and
    stays absent. Letter case is not significant in hexadecimal and the
    common tools disagree about it, so either case is admitted and the value
    is returned lower-cased, the form a computed digest takes.
    """

    shape: str
    digits: int

    def parse(self, raw: str) -> object:
        """Return environment text unchanged; narrowing normalises it."""
        return raw

    def admits(self, value: object) -> bool:
        """Return whether *value* is absent or exactly that many hex digits."""
        if value is None:
            return True
        if not isinstance(value, str):
            return False
        text = value.strip().lower()
        return len(text) == self.digits and all(
            char in "0123456789abcdef" for char in text
        )

    def narrow(self, value: object) -> object:
        """Return the value lower-cased, or ``None`` when none is declared.

        Only reached through ``checked_setting``, which calls ``admits``
        first; ``admits`` is what establishes a present ``value`` is a ``str``.
        """
        return None if value is None else cast("str", value).strip().lower()


type _SettingBound = (
    _NumericBound | _ChoiceBound | _HttpsUrlBound | _HostListBound | _HexBound
)

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
_SEARCH_FRESHNESS_WAIT_MAX = _NumericBound(
    "a finite number between 0 and 300",
    integral=False,
    minimum=0.0,
    maximum=300.0,
)
# Grace windows are the interval an observation has to survive before
# destruction is allowed, so their floor is what makes them observations at
# all. At zero the first cycle to see a namespace stamps its clock and then
# finds the elapsed time is not less than the window, which authorises the
# drop on a single scan - the same-cycle destruction the reclamation contract
# forbids by name. The floor is one maintenance interval at the shipped
# cadence, so the earliest a namespace can be reclaimed is the cycle AFTER
# the one that first observed it.
_GRACE_WINDOW_HOURS = _NumericBound(
    "a finite number of hours no smaller than 1", integral=False, minimum=1.0
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
_HTTPS_SOURCE_URL = _HttpsUrlBound(
    "an https URL with a host and no credentials, query or fragment"
)
_DOWNLOAD_HOSTS = _HostListBound(
    "a comma-separated list of host names, each without a scheme, port or path"
)
_SHA256_DIGEST = _HexBound("a SHA256 digest of 64 hexadecimal characters", 64)
_COMMIT_ID = _HexBound("a full commit id of 40 hexadecimal characters", 40)


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


def checked_setting(name: str, value: object, source: EnvVar | None) -> object:
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
    bound = SETTING_BOUNDS.get(name)
    if bound is None:
        return value
    if not bound.admits(value):
        raise setting_rejection(name, bound.shape, value, source)
    return bound.narrow(value)


# Mapping from _RAG_DEFAULTS key → EnvVar member for env override lookup.
ENV_OVERRIDE_MAP: dict[str, EnvVar] = {
    "data_dir": EnvVar.DATA_DIR,
    "qdrant_dir": EnvVar.QDRANT_DIR,
    "status_dir": EnvVar.STATUS_DIR,
    "log_file": EnvVar.LOG_FILE,
    "mcp_port": EnvVar.PORT,
    # "log_level" is deliberately absent: it is a ``VaultSpecConfigWrapper``
    # property that delegates to ``resolve_log_level`` instead of this
    # generic chain, so it shares the one validated, chain-fallback answer
    # ``configure_logging`` itself resolves rather than a second,
    # unvalidated read of the same variable.
    "service_idle_ttl_seconds": EnvVar.SERVICE_IDLE_TTL_SECONDS,
    "service_max_projects": EnvVar.SERVICE_MAX_PROJECTS,
    "service_search_timeout_seconds": EnvVar.SERVICE_SEARCH_TIMEOUT,
    "search_freshness_wait_max_seconds": EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS,
    "service_admin_timeout_seconds": EnvVar.SERVICE_ADMIN_TIMEOUT,
    "service_reindex_timeout_seconds": EnvVar.SERVICE_REINDEX_TIMEOUT,
    "service_pause_drain_timeout_seconds": EnvVar.SERVICE_PAUSE_DRAIN_TIMEOUT,
    "qdrant_ready_timeout_seconds": EnvVar.QDRANT_READY_TIMEOUT,
    "qdrant_collection_load_concurrency": EnvVar.QDRANT_COLLECTION_LOAD_CONCURRENCY,
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
    "embedding_model_revision": EnvVar.EMBEDDING_MODEL_REVISION,
    "reranker_model_revision": EnvVar.RERANKER_MODEL_REVISION,
    "hf_endpoint": EnvVar.RAG_HF_ENDPOINT,
    "model_fetch_deadline_seconds": EnvVar.MODEL_FETCH_DEADLINE_SECONDS,
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
    "embedding_sparse_encode_token_budget": EnvVar.EMBEDDING_SPARSE_ENCODE_TOKEN_BUDGET,
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
    "watch_coalesce_min_seconds": EnvVar.WATCH_COALESCE_MIN_SECONDS,
    "watch_coalesce_max_seconds": EnvVar.WATCH_COALESCE_MAX_SECONDS,
    "watch_cooling_max_seconds": EnvVar.WATCH_COOLING_MAX_SECONDS,
    "watch_maximum_freshness_seconds": EnvVar.WATCH_MAXIMUM_FRESHNESS_SECONDS,
    "watch_measurement_reevaluation_seconds": (
        EnvVar.WATCH_MEASUREMENT_REEVALUATION_SECONDS
    ),
    "watch_batch_path_limit": EnvVar.WATCH_BATCH_PATH_LIMIT,
    "watch_scope_max_paths": EnvVar.WATCH_SCOPE_MAX_PATHS,
    "watch_scope_max_bytes": EnvVar.WATCH_SCOPE_MAX_BYTES,
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
    "qdrant_binary_sha256": EnvVar.QDRANT_BINARY_SHA256,
    "qdrant_storage_dir": EnvVar.QDRANT_STORAGE_DIR,
    # Managed qdrant binary provisioning: the consent switch and the source.
    "qdrant_auto_provision": EnvVar.QDRANT_AUTO_PROVISION,
    "qdrant_release_base_url": EnvVar.QDRANT_RELEASE_BASE_URL,
    "qdrant_download_hosts": EnvVar.QDRANT_DOWNLOAD_HOSTS,
    # Scheduled storage maintenance (auto-prune) knobs.
    "storage_autoprune": EnvVar.STORAGE_AUTOPRUNE,
    "storage_autoprune_interval_minutes": EnvVar.STORAGE_AUTOPRUNE_INTERVAL_MINUTES,
    "storage_autoprune_grace_hours": EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS,
    "storage_autoprune_grace_hours_data": EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS_DATA,
    "storage_autoprune_grace_hours_ephemeral": (
        EnvVar.STORAGE_AUTOPRUNE_GRACE_HOURS_EPHEMERAL
    ),
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
    "search_freshness_wait_max_seconds": _SEARCH_FRESHNESS_WAIT_MAX,
    "service_admin_timeout_seconds": _POSITIVE_NUMBER,
    "service_reindex_timeout_seconds": _POSITIVE_NUMBER,
    "service_pause_drain_timeout_seconds": _POSITIVE_NUMBER,
    "qdrant_ready_timeout_seconds": _POSITIVE_NUMBER,
    "qdrant_collection_load_concurrency": _POSITIVE_INT,
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
    "embedding_sparse_encode_token_budget": _POSITIVE_INT,
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
    "watch_coalesce_min_seconds": _NON_NEGATIVE_NUMBER,
    "watch_coalesce_max_seconds": _NON_NEGATIVE_NUMBER,
    "watch_cooling_max_seconds": _NON_NEGATIVE_NUMBER,
    "watch_maximum_freshness_seconds": _POSITIVE_NUMBER,
    "watch_measurement_reevaluation_seconds": _POSITIVE_NUMBER,
    "watch_batch_path_limit": _POSITIVE_INT,
    "watch_scope_max_paths": _POSITIVE_INT,
    "watch_scope_max_bytes": _POSITIVE_INT,
    # Document preprocessing and splitting.
    "preprocess_max_emitted_bytes": _POSITIVE_INT,
    "document_chunk_chars_per_token": _POSITIVE_INT,
    "document_chunk_overlap_chars": _POSITIVE_INT,
    # Scheduled storage maintenance. The per-cycle caps admit zero, which is
    # the same as the feature's own off switch. The three grace windows carry
    # a floor instead: zero would let a namespace be destroyed in the cycle
    # that first observed it.
    #
    # The idle window below is the deliberate exception, and reads opposite to
    # them at the same value: zero DISABLES that tier, where zero on a grace
    # window would make its tier maximally aggressive. The two are named alike
    # and mean opposite things at zero, which is why only one of them admits
    # it.
    "storage_autoprune_interval_minutes": _POSITIVE_NUMBER,
    "storage_autoprune_grace_hours": _GRACE_WINDOW_HOURS,
    "storage_autoprune_grace_hours_data": _GRACE_WINDOW_HOURS,
    "storage_autoprune_grace_hours_ephemeral": _GRACE_WINDOW_HOURS,
    "storage_autoprune_archive_retention_days": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_archive_max_gb": _NON_NEGATIVE_NUMBER,
    "storage_autoprune_max_per_cycle": _NON_NEGATIVE_INT,
    "storage_autoprune_ephemeral_idle_hours": _NON_NEGATIVE_NUMBER,
    "storage_reconcile_max_per_cycle": _NON_NEGATIVE_INT,
    "storage_reconcile_budget_seconds": _POSITIVE_NUMBER,
    # Managed qdrant binary source. Declared here so a source that is not
    # HTTPS, or a host pin that could match nothing, stops the process with
    # every other unusable setting instead of failing partway through a
    # download.
    "qdrant_release_base_url": _HTTPS_SOURCE_URL,
    "qdrant_download_hosts": _DOWNLOAD_HOSTS,
    # Model hub endpoint, held to the same shape as the binary's source.
    "hf_endpoint": _HTTPS_SOURCE_URL,
    "model_fetch_deadline_seconds": _POSITIVE_NUMBER,
    # The digest an operator declares for a binary they supply. A value that
    # is not a digest could never match a hashed file, so it is refused here
    # instead of surfacing as a mismatch at the first spawn.
    "qdrant_binary_sha256": _SHA256_DIGEST,
    # Model revisions. A full commit id and nothing else: a branch or a tag
    # is a name that moves, so admitting one would let configuration unpin a
    # model while appearing to pin it.
    "embedding_model_revision": _COMMIT_ID,
    "reranker_model_revision": _COMMIT_ID,
}
