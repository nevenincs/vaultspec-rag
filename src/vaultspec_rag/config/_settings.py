"""Runtime configuration resolution."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    VaultSpecConfig as BaseConfig,
)
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    get_config as get_base_config,
)

from .._env_values import BOOL_SHAPE, parse_bool
from ._paths import read_persisted_local_only
from ._schema import ENV_OVERRIDE_MAP, SETTING_BOUNDS, setting_rejection
from ._types import STATUS_DIR_DEFAULT, VALID_PREPROCESS_MODES, EnvVar, PreprocessMode

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class VaultSpecConfigWrapper:
    """Wraps VaultSpecConfig to provide RAG-specific attributes.

    Proxies attribute access to the underlying ``BaseConfig``,
    falling back to ``_RAG_DEFAULTS`` when the base config lacks a
    RAG-specific key.

    Resolution order for RAG keys:
    1. CLI override (stored via ``overrides`` dict at construction)
    2. Environment variable (via ``ENV_OVERRIDE_MAP``)
    3. ``_RAG_DEFAULTS`` value

    The resolved value is then coerced and range-checked under the module's
    coercion and validation policy, both on construction and on every read.

    Attributes:
        _RAG_DEFAULTS: Default values for RAG-specific configuration
            keys not present on the base ``VaultSpecConfig``.
        SETTING_BOUNDS: Module-level table of admissible ranges, keyed by
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
        # Automatic repair of a demonstrably shrunken index. When a search
        # proves a collection holds fewer points than its publication
        # claims, the service requests one non-destructive reconciliation
        # through the ordinary job machinery. Disabling leaves detection
        # and reporting intact - the status surface then says so honestly
        # rather than pretending the shrink is being handled.
        "integrity_auto_repair": True,
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
        "status_dir": STATUS_DIR_DEFAULT,
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
        from .._domain import NOISE_DOMAINS

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
    # path and declare that range in ``SETTING_BOUNDS``. The properties below
    # exist only where a value is constrained by ANOTHER setting, which a
    # per-key range cannot express.

    def _ordered_bounds[T: (int, float)](
        self,
        lower_key: str,
        upper_key: str,
        *,
        convert: Callable[[Any], T],
        lower_label: str,
        upper_label: str,
    ) -> tuple[T, T]:
        """Resolve a lower/upper setting pair, refusing an inverted one.

        Four settings pairs validated themselves with the same nine lines,
        differing only in the two keys, the numeric type, and the two words
        naming each end in the error. The message is assembled to the same
        shape those four produced, so an operator's existing failure text is
        unchanged.
        """
        lower = convert(self._resolve_rag_default(lower_key))
        upper = convert(self._resolve_rag_default(upper_key))
        if upper < lower:
            msg = (
                f"{upper_key} must be greater than or equal to {lower_key}, "
                f"got {upper_label}={upper}, {lower_label}={lower}"
            )
            raise ValueError(msg)
        return lower, upper

    def _store_write_retry_bounds(self) -> tuple[float, float]:
        return self._ordered_bounds(
            "store_write_retry_base_seconds",
            "store_write_retry_max_seconds",
            convert=float,
            lower_label="base",
            upper_label="maximum",
        )

    @property
    def effective_qdrant_url(self) -> str:
        """Return the Qdrant base URL to talk to, configured or defaulted.

        Server mode sets ``qdrant_url``; otherwise the managed child is on
        loopback at ``qdrant_port``. Four callers spelled this fallback
        themselves and a fifth spelled a variant of it, so "which Qdrant" was
        answered five times in four modules - and a caller that forgot the
        fallback would silently address an empty URL.
        """
        return str(self.qdrant_url or "") or f"http://127.0.0.1:{self.qdrant_port}"

    @property
    def hf_cache_location(self) -> str:
        """Return where Hugging Face keeps its model cache, for reporting.

        ``HF_HOME`` is the library's own switch; this only reports where the
        cache WILL be, so the operator can see it in the daemon log and in the
        embedding load. The default is Hugging Face's, restated here because
        the library does not expose it - which is exactly why two modules had
        it typed out separately.
        """
        import os

        return os.environ.get(EnvVar.HF_HOME.value, "~/.cache/huggingface")

    @property
    def store_write_retry_base_seconds(self) -> float:
        """Return the initial store-write retry delay, never above the maximum."""
        return self._store_write_retry_bounds()[0]

    @property
    def store_write_retry_max_seconds(self) -> float:
        """Return the maximum store-write retry delay, never below the base."""
        return self._store_write_retry_bounds()[1]

    def _index_chunk_bounds(self) -> tuple[int, int]:
        return self._ordered_bounds(
            "index_segment_max_chunks",
            "index_queue_max_chunks",
            convert=int,
            lower_label="segment",
            upper_label="queue",
        )

    def _index_byte_bounds(self) -> tuple[int, int]:
        return self._ordered_bounds(
            "index_segment_max_bytes",
            "index_queue_max_bytes",
            convert=int,
            lower_label="segment",
            upper_label="queue",
        )

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
        return self._ordered_bounds(
            "watch_retry_base_seconds",
            "watch_retry_max_seconds",
            convert=float,
            lower_label="base",
            upper_label="maximum",
        )

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
            flag = parse_bool(raw)
            if flag is None:
                raise setting_rejection(name, BOOL_SHAPE, raw, source)
            return flag
        bound = SETTING_BOUNDS.get(name)
        if bound is not None:
            try:
                return bound.parse(raw)
            except ValueError:
                raise setting_rejection(name, bound.shape, raw, source) from None
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
        bound = SETTING_BOUNDS.get(name)
        if bound is None:
            return value
        if not bound.admits(value):
            raise setting_rejection(name, bound.shape, value, source)
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
        env_key = ENV_OVERRIDE_MAP.get(name)
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
            *SETTING_BOUNDS,
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
        if configured not in VALID_PREPROCESS_MODES:
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
        2. Environment variable (via ``ENV_OVERRIDE_MAP``)
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
    and key not in SETTING_BOUNDS
)
if _unbounded_numeric:
    raise RuntimeError(
        "numeric settings declare no admissible range: " + ", ".join(_unbounded_numeric)
    )
_orphaned_bounds = sorted(set(SETTING_BOUNDS) - set(_all_defaults))
if _orphaned_bounds:
    raise RuntimeError(
        "bounds declared for unknown settings: " + ", ".join(_orphaned_bounds)
    )


def configured_model_repos() -> tuple[tuple[str, str], ...]:
    """Return every model repo this build needs, label first."""
    cfg = get_config()
    return (
        ("Dense (Qwen3)", str(cfg.embedding_model)),
        ("Sparse (SPLADE)", str(cfg.sparse_model)),
        ("Reranker (CrossEncoder)", str(cfg.reranker_model)),
    )


def managed_status_dir() -> Path:
    """Return the managed service directory, resolved through the config."""
    return Path(str(get_config().status_dir)).expanduser()
