"""Local configuration wrapper for vaultspec-rag.

Provides RAG-specific defaults and bridges the gap when the base vaultspec
VaultSpecConfig is missing RAG-specific attributes.
"""

from __future__ import annotations

import json
import logging
import os
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    VaultSpecConfig as BaseConfig,
)
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    get_config as get_base_config,
)

logger = logging.getLogger(__name__)


class EnvVar(StrEnum):
    """Recognized environment variables for vaultspec-rag.

    Each member's value is the full env var name.  This enum is the
    single source of truth - no other module should use bare string
    literals when reading or writing env vars for RAG configuration.
    """

    RAG_ROOT = "VAULTSPEC_RAG_ROOT"
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
    SERVICE_LOG_MAX_BYTES = "VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES"
    SERVICE_LOG_BACKUP_COUNT = "VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT"
    # Wall-clock + memory tuning knobs introduced in #68 Track B.
    EMBEDDING_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE"
    EMBEDDING_ENCODE_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE"
    EMBEDDING_MAX_SEQ_LENGTH = "VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH"
    MAX_EMBED_CHARS = "VAULTSPEC_RAG_MAX_EMBED_CHARS"
    # Codebase-index parallelism + throughput knobs (#155).
    INDEX_CHUNK_WORKERS = "VAULTSPEC_RAG_INDEX_CHUNK_WORKERS"
    EMBEDDING_CODE_ENCODE_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE"
    INDEX_CACHE_FLUSH_SLICES = "VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES"
    INDEX_PARALLEL_MIN_BYTES = "VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES"
    # Dense-encoder backend selection (#155 onnx-encoder-backend ADR).
    DENSE_BACKEND = "VAULTSPEC_RAG_DENSE_BACKEND"
    DENSE_ONNX_FILE = "VAULTSPEC_RAG_DENSE_ONNX_FILE"
    # Filesystem-watcher / auto-reindex knobs (#143/#144).
    WATCH_ENABLED = "VAULTSPEC_RAG_WATCH_ENABLED"
    WATCH_DEBOUNCE_MS = "VAULTSPEC_RAG_WATCH_DEBOUNCE_MS"
    WATCH_COOLDOWN_S = "VAULTSPEC_RAG_WATCH_COOLDOWN_S"
    # Document-preprocessing hook knobs (#185).
    PREPROCESS_ENABLED = "VAULTSPEC_RAG_PREPROCESS_ENABLED"
    PREPROCESS_MAX_EMITTED_BYTES = "VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES"
    HTML_STRIP = "VAULTSPEC_RAG_HTML_STRIP"
    # Vault document chunking knob.
    VAULT_CHUNK_CHARS = "VAULTSPEC_RAG_VAULT_CHUNK_CHARS"
    # Intent-aware vault ranking knobs.
    VAULT_INTENT_DEFAULT = "VAULTSPEC_RAG_VAULT_INTENT_DEFAULT"
    VAULT_INTENT_RANKING_ENABLED = "VAULTSPEC_RAG_VAULT_INTENT_RANKING_ENABLED"
    VAULT_INTENT_TYPE_CAP = "VAULTSPEC_RAG_VAULT_INTENT_TYPE_CAP"
    # Reranker input token bound.
    RERANKER_MAX_LENGTH = "VAULTSPEC_RAG_RERANKER_MAX_LENGTH"
    # Worker-thread pool partitioning.
    SEARCH_CONCURRENCY = "VAULTSPEC_RAG_SEARCH_CONCURRENCY"
    INDEX_JOB_CONCURRENCY = "VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY"

    QDRANT_URL = "VAULTSPEC_RAG_QDRANT_URL"
    QDRANT_API_KEY = "VAULTSPEC_RAG_QDRANT_API_KEY"
    QDRANT_QUANTIZATION = "VAULTSPEC_RAG_QDRANT_QUANTIZATION"
    SPARSE_ENABLED = "VAULTSPEC_RAG_SPARSE_ENABLED"
    # Supervised qdrant server-mode knobs.
    QDRANT_SERVER = "VAULTSPEC_RAG_QDRANT_SERVER"
    QDRANT_PORT = "VAULTSPEC_RAG_QDRANT_PORT"
    QDRANT_BINARY = "VAULTSPEC_RAG_QDRANT_BINARY"
    QDRANT_STORAGE_DIR = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
    # First-class local-backend opt-out. When set truthy it selects the
    # on-disk store regardless of the server-mode default.
    LOCAL_ONLY = "VAULTSPEC_RAG_LOCAL_ONLY"

    # Third-party env vars referenced in the codebase - defined here so
    # the string literal lives in exactly one place.
    HF_HOME = "HF_HOME"
    HF_HUB_DOWNLOAD_TIMEOUT = "HF_HUB_DOWNLOAD_TIMEOUT"
    DISABLE_SAFETENSORS_CONVERSION = "DISABLE_SAFETENSORS_CONVERSION"


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
    "service_log_max_bytes": EnvVar.SERVICE_LOG_MAX_BYTES,
    "service_log_backup_count": EnvVar.SERVICE_LOG_BACKUP_COUNT,
    # Performance tuning knobs (#68 audit F9.1) - surface them via
    # env vars too so deploy-time tuning does not require CLI flags
    # or config file edits.
    "embedding_batch_size": EnvVar.EMBEDDING_BATCH_SIZE,
    "embedding_encode_batch_size": EnvVar.EMBEDDING_ENCODE_BATCH_SIZE,
    "embedding_max_seq_length": EnvVar.EMBEDDING_MAX_SEQ_LENGTH,
    "max_embed_chars": EnvVar.MAX_EMBED_CHARS,
    "index_chunk_workers": EnvVar.INDEX_CHUNK_WORKERS,
    "embedding_code_encode_batch_size": EnvVar.EMBEDDING_CODE_ENCODE_BATCH_SIZE,
    "index_cache_flush_slices": EnvVar.INDEX_CACHE_FLUSH_SLICES,
    "index_parallel_min_bytes": EnvVar.INDEX_PARALLEL_MIN_BYTES,
    "dense_backend": EnvVar.DENSE_BACKEND,
    "dense_onnx_file": EnvVar.DENSE_ONNX_FILE,
    # Filesystem-watcher / auto-reindex knobs (#143/#144).
    "watch_enabled": EnvVar.WATCH_ENABLED,
    "watch_debounce_ms": EnvVar.WATCH_DEBOUNCE_MS,
    "watch_cooldown_s": EnvVar.WATCH_COOLDOWN_S,
    # Document-preprocessing hook knobs (#185).
    "preprocess_enabled": EnvVar.PREPROCESS_ENABLED,
    "preprocess_max_emitted_bytes": EnvVar.PREPROCESS_MAX_EMITTED_BYTES,
    "html_strip": EnvVar.HTML_STRIP,
    # Vault chunking + reranker input knobs.
    "vault_chunk_chars": EnvVar.VAULT_CHUNK_CHARS,
    "reranker_max_length": EnvVar.RERANKER_MAX_LENGTH,
    # Intent-aware vault ranking knobs.
    "vault_intent_default": EnvVar.VAULT_INTENT_DEFAULT,
    "vault_intent_ranking_enabled": EnvVar.VAULT_INTENT_RANKING_ENABLED,
    "vault_intent_type_cap": EnvVar.VAULT_INTENT_TYPE_CAP,
    # Worker-thread pool partitioning.
    "search_concurrency": EnvVar.SEARCH_CONCURRENCY,
    "index_job_concurrency": EnvVar.INDEX_JOB_CONCURRENCY,
    "qdrant_url": EnvVar.QDRANT_URL,
    "qdrant_api_key": EnvVar.QDRANT_API_KEY,
    "qdrant_quantization": EnvVar.QDRANT_QUANTIZATION,
    "sparse_enabled": EnvVar.SPARSE_ENABLED,
    # Supervised qdrant server-mode knobs.
    "qdrant_server": EnvVar.QDRANT_SERVER,
    "qdrant_port": EnvVar.QDRANT_PORT,
    "qdrant_binary": EnvVar.QDRANT_BINARY,
    "qdrant_storage_dir": EnvVar.QDRANT_STORAGE_DIR,
    # First-class local-backend opt-out knob.
    "local_only": EnvVar.LOCAL_ONLY,
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

    Attributes:
        _RAG_DEFAULTS: Default values for RAG-specific configuration
            keys not present on the base ``VaultSpecConfig``.
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
        # Flush the CUDA caching allocator every N codebase embed slices
        # instead of every slice (#155). Per-slice flushing (the #68 RSS fix)
        # forces a device sync each iteration; throttling to every N slices
        # removes most of those syncs while still bounding allocator growth to
        # N slices' worth of transient activations. ``1`` restores per-slice
        # flushing.
        "index_cache_flush_slices": 8,
        # Minimum total source bytes before AUTO worker selection
        # (``index_chunk_workers=0``) engages the process pool (#155). Spawn
        # workers cost ~0.3s each to start, so on small/medium trees the pool
        # is slower than serial chunking; below this threshold the auto path
        # stays serial. An explicit ``index_chunk_workers`` >= 1 bypasses this
        # gate. 8 MiB sits comfortably above the measured serial/parallel
        # crossover while still parallelising any large codebase.
        "index_parallel_min_bytes": 8 * 1024 * 1024,
        # Dense-encoder backend (#155 onnx-encoder-backend ADR). "torch" is the
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
        "mcp_port": 8766,
        "log_level": "WARNING",
        "service_idle_ttl_seconds": 1800,
        "service_max_projects": 16,
        "service_log_max_bytes": 10485760,
        "service_log_backup_count": 5,
        # Filesystem-watcher / auto-reindex knobs (#143/#144). The
        # resident service auto-reindexes on file change; ``watch_enabled``
        # is the sole opt-out (``False`` => pull-only service). The
        # ``debounce_ms`` and ``cooldown_s`` knobs tune responsiveness;
        # ``0`` means "no delay", not "disabled".
        "watch_enabled": True,
        "watch_debounce_ms": 2000,
        "watch_cooldown_s": 30.0,
        # Document-preprocessing executes project-defined commands, so it is
        # OFF by default: a cloned/untrusted repo's ``.vaultragpreprocess.toml``
        # must never run code merely because the project was indexed or watched.
        # Operators opt in per host via ``VAULTSPEC_RAG_PREPROCESS_ENABLED=1``
        # once they trust the project's preprocess commands (security: untrusted
        # -repo arbitrary code execution).
        "preprocess_enabled": False,
        # Document-preprocessing hook knobs (#185). The source-size cap
        # (``_MAX_FILE_SIZE``) is relaxed for files matched by a preprocess
        # rule; this cap instead bounds the *emitted* text a preprocessor
        # produces, so a 12 MB PDF that distils to 40 KB indexes while a
        # runaway extractor that emits tens of MB is skipped (D10).
        "preprocess_max_emitted_bytes": 10 * 1024 * 1024,
        # Strip HTML tags to plain text before chunking ``.html`` sources
        # (#185 adjacent ask). Default on: raw markup wastes ~1/3 of each
        # chunk's budget and pollutes results with navigation boilerplate.
        # Falls back to raw-markup chunking on any parse error.
        "html_strip": True,
    }

    # Intent-aware vault ranking weight profiles (ADR D2/D3). Each profile maps
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

    def __init__(self, base: BaseConfig) -> None:
        """Initialise the wrapper around an existing config.

        Args:
            base: The base ``VaultSpecConfig`` to wrap.

        Returns:
            None.
        """
        self._base = base

    def _resolve_rag_default(self, name: str) -> Any:
        # 1. CLI override via base config
        try:
            return getattr(self._base, name)
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
                    pass
                elif isinstance(default, bool):
                    return env_val.lower() in ("1", "true", "yes")
                elif isinstance(default, int):
                    return int(env_val)
                elif isinstance(default, float):
                    return float(env_val)
                else:
                    return env_val

        # 2.5. Persisted runtime selection (local_only only). When
        # ``install --local-only`` wrote the marker, a later
        # ``server start`` with no flag and no env honours it. Precedence
        # is explicit env/flag (above) > persisted config (here) >
        # module default (below), so an operator who re-passes the flag or
        # sets the env always overrides the persisted choice.
        if name == "local_only":
            persisted = read_persisted_local_only()
            if persisted is not None:
                return persisted

        # 3. Default
        return self._RAG_DEFAULTS[name]

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

    def __getattr__(self, name: str) -> Any:
        """Return a config attribute, checking env overrides then defaults.

        Resolution order for known RAG keys:
        1. Base config (may contain CLI overrides)
        2. Environment variable (via ``_ENV_OVERRIDE_MAP``)
        3. ``_RAG_DEFAULTS`` fallback

        Args:
            name: The attribute name to look up.

        Returns:
            The resolved attribute value.

        Raises:
            AttributeError: If *name* is not a RAG default and is
                also missing from the base config.
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
        return cls(base)


_cached_config: VaultSpecConfigWrapper | None = None


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
        _cached_config = VaultSpecConfigWrapper(base)
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
