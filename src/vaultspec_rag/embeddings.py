"""GPU-native embedding model wrapper for vault semantic search.

Uses sentence-transformers with Qwen3-Embedding-0.6B (1024d) for dense
embeddings and SPLADE v3 via SparseEncoder for sparse embeddings.
Requires CUDA GPU -- no CPU fallback.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from .config._types import EnvVar
from .job_control import timed_gpu_lock

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    from sentence_transformers import SentenceTransformer, SparseEncoder
    from torch import Tensor

logger = logging.getLogger(__name__)

# transformers materialises model weights through a background thread pool by
# default (``spawn_materialize`` in ``core_model_loading``). On Windows that
# parallel load intermittently faults with a native access violation mid-
# materialisation - a torch storage race that crashes the whole process during
# any model load (dense, sparse, or the reranker), as seen under concurrent
# multi-root indexing and search. Deactivate the async path on Windows so
# weights materialise single-threaded and deterministically; an explicit
# operator-set value still wins. Linux (CI) keeps the faster parallel path.
if sys.platform == "win32":
    os.environ.setdefault("HF_DEACTIVATE_ASYNC_LOAD", "1")

__all__ = ["EmbeddingModel", "QueryEmbeddingCache", "SparseResult"]


@dataclass
class SparseResult:
    """Sparse embedding result compatible with Qdrant SparseVector interface.

    Wraps SPLADE COO tensor output into .indices / .values arrays
    that match the interface expected by VaultStore.hybrid_search.
    """

    indices: list[int]
    values: list[float]


class QueryEmbeddingCache:
    """Thread-safe LRU cache for query embeddings.

    Agents re-issue identical queries frequently; a hit skips both
    encoder forward passes and therefore the GPU lock acquisition.
    Keys pair the search surface with the cleaned query text; values
    hold the dense vector together with the sparse vector (or ``None``
    when sparse encoding was disabled at compute time). Entries are
    never invalidated - query embeddings depend only on the model.
    """

    def __init__(self, maxsize: int = 128) -> None:
        self._data: OrderedDict[
            tuple[str, str],
            tuple[np.ndarray, SparseResult | None],
        ] = OrderedDict()
        self._lock = threading.Lock()
        self._maxsize = max(1, maxsize)

    def get(
        self,
        key: tuple[str, str],
    ) -> tuple[np.ndarray, SparseResult | None] | None:
        """Return the cached entry for *key*, refreshing its recency.

        The sparse component is returned as a defensive copy so no
        caller can mutate the cached lists in place; the dense array is
        shared and treated as read-only by every consumer (callers
        serialize it via ``tolist()``).
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            self._data.move_to_end(key)
            dense, sparse = entry
            if sparse is None:
                return (dense, None)
            return (
                dense,
                SparseResult(
                    indices=list(sparse.indices),
                    values=list(sparse.values),
                ),
            )

    def put(
        self,
        key: tuple[str, str],
        value: tuple[np.ndarray, SparseResult | None],
    ) -> None:
        """Insert *value* under *key*, evicting the least recent entry."""
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)


@dataclass(frozen=True, slots=True)
class EncodeBucket:
    """One contiguous sub-batch of an encode call's input texts.

    ``start``/``end`` are half-open indices into the text list the bucket
    was planned over. ``estimated_tokens`` is the bucket's planned
    activation footprint: item count times the padded (bucket-longest)
    per-item token estimate, the quantity a token budget bounds.
    """

    start: int
    end: int
    estimated_tokens: int


def plan_encode_buckets(
    texts: Sequence[str],
    *,
    token_budget: int,
    chars_per_token: int,
    max_items: int,
) -> list[EncodeBucket]:
    """Partition texts into contiguous buckets bounded by a token budget.

    Activation memory for one encoder forward scales with items times the
    padded sequence length, so a fixed item count has an unbounded memory
    footprint: a batch of near-truncation-cap texts demands an order of
    magnitude more than the same count of short ones. Planning by
    estimated tokens bounds that footprint by construction.

    Each text's token count is estimated as ``ceil(len(text) /
    chars_per_token)`` (minimum 1); a bucket's footprint is its item count
    times its longest item's estimate, i.e. the padded cost the encoder
    actually pays. The scan is greedy and order-preserving: buckets are
    contiguous, their concatenation is exactly the input, and callers that
    feed a length-sorted list get length-homogeneous buckets, so the
    encode library's internal length sort becomes a no-op. A single text
    whose own estimate exceeds the budget forms its own bucket - the
    planner never drops input; the caller's OOM handling owns that risk.

    Args:
        texts: Input texts, already truncated to the embed character cap.
            Length-sorted input yields length-homogeneous buckets; the
            partition is correct (bounded, order-preserving, exhaustive)
            for any order.
        token_budget: Maximum estimated tokens per multi-item bucket.
        chars_per_token: Calibration divisor mapping characters to
            estimated tokens.
        max_items: Item-count cap per bucket, always enforced on top of
            the token budget.

    Returns:
        Ordered, contiguous, exhaustive buckets over ``texts``; empty for
        empty input.

    Raises:
        ValueError: If any bound is not a positive integer.
    """
    if token_budget <= 0:
        raise ValueError(f"token_budget must be a positive integer, got {token_budget}")
    if chars_per_token <= 0:
        raise ValueError(
            f"chars_per_token must be a positive integer, got {chars_per_token}"
        )
    if max_items <= 0:
        raise ValueError(f"max_items must be a positive integer, got {max_items}")

    buckets: list[EncodeBucket] = []
    start = 0
    count = 0
    padded = 0
    for index, text in enumerate(texts):
        estimate = max(1, -(-len(text) // chars_per_token))
        if count > 0:
            widened = max(padded, estimate)
            if count < max_items and widened * (count + 1) <= token_budget:
                padded = widened
                count += 1
                continue
            buckets.append(EncodeBucket(start, index, padded * count))
            start = index
        padded = estimate
        count = 1
    if count > 0:
        buckets.append(EncodeBucket(start, len(texts), padded * count))
    return buckets


class EncodeBatchCeiling:
    """Learned CUDA encode ceiling in token units, persistent across calls.

    The ceiling is denominated in estimated token footprint - item count
    times padded per-item tokens, the quantity activation memory actually
    scales with - not in items. A per-count ceiling learned on one length
    regime is wrong for every other: a count that fits short texts OOMs on
    long ones, and an OOM on long texts clamps short batches that would
    fit. One token number is regime-aware by construction.

    Recovering the footprint inside a single call converges that call, but
    a ceiling that resets on return makes every subsequent call rediscover
    it: each rediscovery costs a discarded forward pass plus an allocator
    cache flush, and under sustained memory pressure that tax is paid on
    every slice of every job. The ceiling therefore lives on the model
    instance and clamps each call's planning budget to a footprint below
    the one that last failed.

    The ceiling must also recover: pinning it at its low-water mark forever
    would turn one transient memory squeeze into a permanent throughput
    loss. After ``RECOVERY_SUCCESSES`` consecutive successful calls at the
    ceiling, the next call probes double the ceiling (bounded by the
    requested budget); a successful probe raises the ceiling, a failed one
    re-clamps and restarts the count. While pressure persists, at most one
    call in ``RECOVERY_SUCCESSES + 1`` pays the discarded-forward cost;
    when pressure lifts, the ceiling climbs back within tens of calls.

    Thread-safe: encoding runs on the dedicated GPU consumer thread, but
    successive jobs may run on different threads, so the state is guarded
    by a lock for visibility rather than left to happenstance ordering.
    """

    #: Consecutive at-ceiling successes required before probing upward.
    #: Bounds the amortized probe cost under sustained pressure to one
    #: discarded forward per this many calls while keeping recovery
    #: within tens of slices once memory frees up.
    RECOVERY_SUCCESSES = 16

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ceiling: int | None = None
        self._successes_at_ceiling = 0

    def clamp(self, requested: int) -> int:
        """Return the token budget a call should plan its buckets under."""
        with self._lock:
            if self._ceiling is None or requested <= self._ceiling:
                return requested
            if self._successes_at_ceiling >= self.RECOVERY_SUCCESSES:
                self._successes_at_ceiling = 0
                return min(requested, self._ceiling * 2)
            return self._ceiling

    def record_success(self, token_budget: int) -> None:
        """Bank one call that completed under *token_budget* without an OOM."""
        with self._lock:
            if self._ceiling is None:
                return
            if token_budget > self._ceiling:
                self._ceiling = token_budget
            if token_budget >= self._ceiling:
                self._successes_at_ceiling += 1

    def record_oom(self, failing_tokens: int) -> int:
        """Learn from one OOM at the *failing_tokens* estimated footprint.

        The ceiling drops to half the footprint that failed - the failing
        estimate itself proved too large, so replanning at it would
        reproduce the same failing shape - and the recovery count restarts.

        Returns:
            The new ceiling, which is also the budget the caller should
            replan its remaining work under.
        """
        with self._lock:
            self._ceiling = max(1, failing_tokens // 2)
            self._successes_at_ceiling = 0
            return self._ceiling


def _raise_for_hf_access(model_id: str, exc: Exception) -> None:
    """Re-raise a HuggingFace gated/missing repo error as an actionable RuntimeError.

    Maps ``huggingface_hub.errors.GatedRepoError`` and
    ``RepositoryNotFoundError`` to a ``RuntimeError`` that names the model,
    explains the remediation, and includes the model URL. All other exceptions
    are left untouched (not caught by callers of this helper).

    Args:
        model_id: The HuggingFace model identifier that caused the error.
        exc: The original ``GatedRepoError`` or ``RepositoryNotFoundError``.

    Raises:
        RuntimeError: Always, with actionable remediation message.
    """
    from huggingface_hub.errors import GatedRepoError

    kind = "gated" if isinstance(exc, GatedRepoError) else "inaccessible or not found"
    raise RuntimeError(
        f"Model '{model_id}' is {kind} on HuggingFace Hub. "
        f"Set the HF_TOKEN environment variable or run `huggingface-cli login` "
        f"to authenticate. Model URL: https://huggingface.co/{model_id}",
    ) from exc


def _check_rag_deps() -> None:
    """Verify GPU RAG dependencies are installed.

    Raises:
        ImportError: If torch or sentence-transformers is not
            installed.
        RuntimeError: If no CUDA GPU device is available.
    """
    from ._gpu import load_torch

    # The single centralized gate: import torch and assert a CUDA device,
    # failing hard on a CPU-only build rather than degrading to CPU compute.
    load_torch()

    import importlib.util

    if importlib.util.find_spec("sentence_transformers") is None:
        raise ImportError(
            "sentence-transformers not installed. Run: uv sync",
        ) from None


def _sparse_tensor_to_results(sparse_tensor: object) -> list[SparseResult]:
    """Convert a batch of SPLADE sparse tensors to SparseResult list.

    SparseEncoder.encode() returns a sparse COO-like tensor. Each row
    is a sparse vector over the vocabulary. We extract non-zero indices
    and values for each document.

    Handles scipy sparse matrices, torch Tensors (dense, sparse COO,
    or sparse CSR), and numpy arrays.

    Args:
        sparse_tensor: Batch sparse embedding output from
            SparseEncoder. May be a scipy sparse matrix,
            torch.Tensor, or numpy ndarray.

    Returns:
        List of SparseResult, one per input row, with non-zero
        indices and their corresponding values.
    """
    import torch

    tocsr = getattr(sparse_tensor, "tocsr", None)
    if tocsr is not None:
        # scipy sparse matrix
        csr = tocsr()
        results: list[SparseResult] = []
        for i in range(csr.shape[0]):
            row = csr.getrow(i)
            indices = cast("list[int]", row.indices.tolist())
            values = cast("list[float]", row.data.tolist())
            results.append(SparseResult(indices=indices, values=values))
        return results

    if isinstance(sparse_tensor, torch.Tensor):
        # One coalesced pass and a single device-to-host transfer for
        # the whole batch. Densifying a [batch x vocab] tensor and
        # looping per row costs a GPU sync per row and runs inside the
        # GPU lock on the indexing path.
        n_rows = int(sparse_tensor.shape[0])
        if sparse_tensor.is_sparse or sparse_tensor.is_sparse_csr:
            coo = (
                sparse_tensor.to_sparse_coo()
                if sparse_tensor.is_sparse_csr
                else sparse_tensor
            ).coalesce()
            joint = coo.indices().cpu()
            rows = cast("list[int]", joint[0].tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
            cols = cast("list[int]", joint[1].tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
            vals = cast("list[float]", coo.values().cpu().tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
        else:
            nz = sparse_tensor.nonzero(as_tuple=False)
            picked = sparse_tensor[nz[:, 0], nz[:, 1]]
            nz_cpu = nz.cpu()
            rows = cast("list[int]", nz_cpu[:, 0].tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
            cols = cast("list[int]", nz_cpu[:, 1].tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
            vals = cast("list[float]", picked.cpu().tolist())  # pyright: ignore[reportUnknownMemberType]  # torch Tensor.tolist() stub is incomplete
        results = [SparseResult(indices=[], values=[]) for _ in range(n_rows)]
        for row, col, val in zip(rows, cols, vals, strict=True):
            entry = results[row]
            entry.indices.append(col)
            entry.values.append(val)
        return results

    # numpy array fallback
    import numpy as _np

    arr = _np.asarray(sparse_tensor)
    results = []
    for i in range(arr.shape[0]):
        row = arr[i]
        nz = row.nonzero()[0]
        indices = cast("list[int]", nz.tolist())
        values = cast("list[float]", row[nz].tolist())
        results.append(SparseResult(indices=indices, values=values))
    return results


class EmbeddingModel:
    """GPU-native embedding model using sentence-transformers.

    Dense: Qwen3-Embedding-0.6B (1024 dimensions, fp16, flash_attention_2)
    Sparse: SPLADE v3 via SparseEncoder (GPU-native learned sparse)

    Attributes:
        MODEL_NAME: Default dense embedding model ID.
        SPARSE_MODEL_NAME: Default sparse embedding model ID.
        DEFAULT_DIMENSION: Embedding dimension for Qwen3-Embedding-0.6B.
        DEFAULT_BATCH_SIZE: Default encoding batch size.
        MAX_EMBED_CHARS: Maximum characters per document to embed.
        dimension: Actual embedding dimension.
        sparse_dimension: Actual sparse-model output dimension.
    """

    MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
    SPARSE_MODEL_NAME = "naver/splade-v3"
    DEFAULT_DIMENSION = 1024
    DEFAULT_BATCH_SIZE = 64
    MAX_EMBED_CHARS = 8000

    @staticmethod
    def _default_encode_batch_size() -> int:
        """Return the configured inner sub-batch size for ``encode``.

        SentenceTransformer sorts each ``encode`` call's input by
        sequence length, then iterates ``encode_batch_size``-item
        sub-batches of the sorted list. A small value (default 8)
        keeps each sub-batch length-uniform and minimises padding
        waste on variable-length corpora.
        """
        from .config._settings import get_config

        return get_config().embedding_encode_batch_size

    @staticmethod
    def _default_max_embed_chars() -> int:
        """Return the configured max characters per document.

        Returns:
            Character limit from VaultSpecConfigWrapper.
        """
        from .config._settings import get_config

        return get_config().max_embed_chars

    @staticmethod
    def _load_dense_model(
        dense_name: str,
        model_kwargs: dict[str, object],
        cfg: object,
        *,
        local_files_only: bool,
    ) -> SentenceTransformer:
        """Construct the dense SentenceTransformer for the configured backend.

        The default backend is ``torch``. When ``dense_backend == "onnx"`` the
        model is loaded with the ONNX backend on ``CUDAExecutionProvider`` using
        the cached O4 file (``dense_onnx_file``). Any failure - missing
        ``optimum`` / ``onnxruntime-gpu``, export error, or a GPU provider that
        cannot load (e.g. the onnxruntime CUDA-12 vs torch CUDA-13 mismatch) -
        logs a warning and falls back to the torch construction, so a
        misconfigured backend never breaks indexing or search. The ONNX path is
        experimental and opt-in: selecting it requires
        ``sentence-transformers[onnx-gpu]`` in an onnxruntime-compatible CUDA
        environment.
        """
        from sentence_transformers import SentenceTransformer

        backend = str(getattr(cfg, "dense_backend", "torch") or "torch").lower()
        if backend == "onnx":
            onnx_file = str(getattr(cfg, "dense_onnx_file", "onnx/model_O4.onnx"))
            try:
                try:
                    import importlib

                    # Pull CUDA libs from any nvidia-*-cu* site-packages so the
                    # CUDA provider can load even when torch ships a different
                    # CUDA minor (best-effort; safe no-op on older onnxruntime).
                    # Dynamic import: onnxruntime is an optional, operator-
                    # provided dependency, not a project requirement.
                    importlib.import_module("onnxruntime").preload_dlls()
                except Exception as exc:  # onnxruntime optional / preload varies
                    logger.debug("onnxruntime preload skipped: %s", exc)
                model = SentenceTransformer(
                    dense_name,
                    backend="onnx",
                    local_files_only=local_files_only,
                    model_kwargs={
                        "provider": "CUDAExecutionProvider",
                        "file_name": onnx_file,
                    },
                    processor_kwargs={"padding_side": "left"},
                )
            except Exception:
                logger.warning(
                    "ONNX dense backend unavailable (file=%s); falling back to "
                    "the torch backend. Install sentence-transformers[onnx-gpu] "
                    "in an onnxruntime-compatible CUDA environment to enable it.",
                    onnx_file,
                    exc_info=True,
                )
            else:
                logger.info("Dense model loaded via ONNX backend (%s)", onnx_file)
                return model

        try:
            return SentenceTransformer(
                dense_name,
                local_files_only=local_files_only,
                model_kwargs=model_kwargs,
                processor_kwargs={"padding_side": "left"},
            )
        except Exception as exc:
            from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

            if isinstance(exc, (GatedRepoError, RepositoryNotFoundError)):
                _raise_for_hf_access(dense_name, exc)
            raise

    def __init__(
        self,
        model_name: str | None = None,
        *,
        local_files_only: bool = False,
    ) -> None:
        """Load dense and sparse models onto GPU.

        Args:
            model_name: Override the dense embedding model name.
                Defaults to the config value or MODEL_NAME.
            local_files_only: Load both models from the local Hugging Face
                cache without issuing remote metadata requests. The default
                remains online-capable for normal product construction.

        Raises:
            ImportError: If sentence-transformers or torch not installed.
            RuntimeError: If no CUDA GPU is available.
        """
        _check_rag_deps()

        import torch

        from .config._settings import get_config

        cfg = get_config()
        dense_name = model_name or cfg.embedding_model
        sparse_name = (
            cfg.sparse_model
            if hasattr(cfg, "sparse_model") and cfg.sparse_model
            else self.SPARSE_MODEL_NAME
        )
        os.environ.setdefault(EnvVar.DISABLE_SAFETENSORS_CONVERSION, "1")

        logger.info(
            "HF cache: %s",
            cfg.hf_cache_location,
        )

        model_kwargs: dict[str, object] = {
            "torch_dtype": torch.float16,
        }
        # Probe for flash_attention_2 before loading to avoid double model load
        try:
            import importlib.util

            if importlib.util.find_spec("flash_attn") is not None:
                model_kwargs["attn_implementation"] = "flash_attention_2"
            else:
                logger.info(
                    "flash_attention_2 not available, using default attention",
                )
        except ImportError:
            logger.info("flash_attention_2 not available, using default attention")

        t0 = time.perf_counter()
        self._dense_model = self._load_dense_model(
            dense_name,
            model_kwargs,
            cfg,
            local_files_only=local_files_only,
        )
        # Cap the model's advertised max sequence length so the
        # processor truncates aggressively and the model never
        # allocates attention buffers for the 32 k context window.
        # ``max_embed_chars=8000`` truncates raw text to ~2000 BPE
        # tokens for Qwen3, so 2048 is the right ceiling. #68
        # wall-clock work.
        max_seq_len = (
            cfg.embedding_max_seq_length
            if hasattr(cfg, "embedding_max_seq_length")
            else 2048
        )
        try:
            self._dense_model.max_seq_length = int(max_seq_len)
        except Exception:  # defensive setattr - old st versions vary
            logger.warning("Could not set dense model max_seq_length=%d", max_seq_len)
        logger.info(
            "Dense model loaded in %.2fs (max_seq_length=%d)",
            time.perf_counter() - t0,
            int(max_seq_len),
        )

        # Every consumer of the sparse model already asks whether sparse is
        # enabled before reaching for it: the streaming indexer guards its
        # encode on ``sparse_enabled``, the searcher passes ``None`` instead of
        # a sparse query vector, and ``effective_sparse_dim`` returns the
        # placeholder width 1 without touching the model at all. Loading it
        # regardless was the one place that did not ask, so a deployment with
        # sparse off still put SPLADE on the device and held its VRAM for the
        # process lifetime - and resident VRAM is exactly what the indexing CUDA
        # ceiling is derived net of, so the unused model narrowed every budget
        # computed after it.
        if not bool(cfg.sparse_enabled):
            self._sparse_model = None
            self.sparse_dimension = None
            logger.info("Sparse model not loaded: sparse vectors are disabled")
        else:
            self._load_sparse_model(sparse_name, local_files_only=local_files_only)

        self.dimension: int = (
            cfg.embedding_dimension
            if hasattr(cfg, "embedding_dimension")
            else self.DEFAULT_DIMENSION
        )
        self._device = "cuda"
        self.query_cache = QueryEmbeddingCache()
        self._dense_batch_ceiling = EncodeBatchCeiling()
        self._sparse_batch_ceiling = EncodeBatchCeiling()

        gpu_name = torch.cuda.get_device_name(0)
        logger.info(
            "Embedding models loaded on %s (dense=%s, sparse=%s, dense_dim=%d, "
            "sparse_dim=%s)",
            gpu_name,
            dense_name,
            sparse_name if self._sparse_model is not None else "disabled",
            self.dimension,
            self.sparse_dimension,
        )

    def _require_sparse_model(self) -> SparseEncoder:
        """Return the loaded SPLADE model, or say plainly why there is none.

        Reaching a sparse encode with sparse disabled means a caller skipped the
        ``sparse_enabled`` check every other call path makes. That is a wiring
        bug, and it should name itself rather than surface as an attribute error
        on ``None`` several frames deeper.
        """
        if self._sparse_model is None:
            raise RuntimeError(
                "sparse encoding was requested while sparse vectors are "
                "disabled; the sparse model was never loaded"
            )
        return self._sparse_model

    def _load_sparse_model(
        self,
        sparse_name: str,
        *,
        local_files_only: bool,
    ) -> None:
        """Load SPLADE onto the GPU and record the width a run will write."""
        import torch
        from sentence_transformers import SparseEncoder

        t0 = time.perf_counter()
        try:
            self._sparse_model = SparseEncoder(
                sparse_name,
                device="cuda",
                local_files_only=local_files_only,
                model_kwargs={"torch_dtype": torch.float16},
            )
        except Exception as exc:
            from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

            if isinstance(exc, (GatedRepoError, RepositoryNotFoundError)):
                _raise_for_hf_access(sparse_name, exc)
            raise
        # Do NOT override the sparse model's max_seq_length: SPLADE
        # is BERT-based and has max_position_embeddings=512. Setting
        # it to 2048 causes a position-embedding shape mismatch at
        # forward time. The sparse path already truncates internally.
        sparse_max = int(getattr(self._sparse_model, "max_seq_length", 512))
        sparse_dimension = self._sparse_model.get_embedding_dimension()
        if sparse_dimension is None:
            sparse_config = self._sparse_model.config
            sparse_dimension = getattr(sparse_config, "vocab_size", None)
        if (
            not isinstance(sparse_dimension, int)
            or isinstance(sparse_dimension, bool)
            or sparse_dimension <= 0
        ):
            raise RuntimeError(
                "Sparse model did not expose a positive output dimension required "
                "for bounded indexing"
            )
        self.sparse_dimension = sparse_dimension
        logger.info(
            "Sparse model loaded in %.2fs (max_seq_length=%d, dimension=%d)",
            time.perf_counter() - t0,
            sparse_max,
            self.sparse_dimension,
        )

    @property
    def device(self) -> str:
        """Return the current device string ('cuda').

        Returns:
            Device string, always ``"cuda"``.
        """
        return self._device

    def encode_documents(
        self,
        texts: list[str],
        *,
        batch_size: int | None = None,
    ) -> np.ndarray:
        """Encode document texts as dense embeddings on GPU.

        Args:
            texts: List of document texts (title + body).
            batch_size: Inner sub-batch size passed to
                ``SentenceTransformer.encode``. SentenceTransformer
                length-sorts the input then iterates
                ``batch_size``-item sub-batches; small values
                produce length-uniform sub-batches and minimise
                padding waste on variable-length corpora. Defaults
                to :meth:`_default_encode_batch_size` (config
                ``embedding_encode_batch_size``).

        Returns:
            numpy array of shape ``(n, dimension)`` with normalized
            embeddings.

        Raises:
            torch.cuda.OutOfMemoryError: If encoding fails even at
                batch_size=1.
        """
        import numpy as np

        embeddings = self._encode_documents_output(
            texts,
            batch_size=batch_size,
            retain_on_device=False,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def encode_documents_on_device(
        self,
        texts: list[str],
        *,
        batch_size: int | None = None,
    ) -> Tensor:
        """Encode documents while retaining the bounded result on CUDA.

        Index streaming calls this under ``gpu_lock`` and performs the single
        device-to-host transfer immediately after releasing the lock. Other
        callers use :meth:`encode_documents` and receive a CPU NumPy result.
        """
        return cast(
            "Tensor",
            self._encode_documents_output(
                texts,
                batch_size=batch_size,
                retain_on_device=True,
            ),
        )

    def _encode_documents_output(
        self,
        texts: list[str],
        *,
        batch_size: int | None,
        retain_on_device: bool,
    ) -> object:
        """Run the finite dense OOM ladder with an explicit output lifetime.

        The starting batch size is clamped by the instance's learned
        ceiling, so a call after an OOM starts where the last call fit
        instead of rediscovering the ceiling with another discarded
        forward pass.
        """
        import torch

        from .memory_probe import cuda_forward_peak_capture

        if batch_size is None:
            batch_size = self._default_encode_batch_size()
        batch_size = self._dense_batch_ceiling.clamp(batch_size)

        max_chars = self._default_max_embed_chars()
        truncated = [t[:max_chars] for t in texts]

        while True:
            try:
                if retain_on_device:
                    # The on-device path runs under the caller's gpu_lock
                    # hold; that serialisation is what makes the peak
                    # capture attribute this forward's demand to the
                    # calling job alone.
                    with cuda_forward_peak_capture():
                        encoded: object = self._dense_model.encode(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers encode overloads are partially stubbed
                            truncated,
                            batch_size=batch_size,
                            show_progress_bar=len(truncated) > 100,
                            normalize_embeddings=True,
                            convert_to_numpy=False,
                            convert_to_tensor=True,
                        )
                else:
                    encoded = self._dense_model.encode(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers encode overloads are partially stubbed
                        truncated,
                        batch_size=batch_size,
                        show_progress_bar=len(truncated) > 100,
                        normalize_embeddings=True,
                    )
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch_size <= 1:
                    raise
                batch_size = self._dense_batch_ceiling.record_oom(batch_size)
                logger.warning(
                    "CUDA OOM during dense encoding, retrying with batch_size=%d",
                    batch_size,
                )
            else:
                self._dense_batch_ceiling.record_success(batch_size)
                return encoded

    #: Task-specific instruction prompts for the dense encoder. Qwen3
    #: embeddings are instruction-tuned: telling the model what kind of
    #: corpus the query targets measurably improves retrieval. Keys are
    #: search surfaces; ``None``/unknown falls back to the model's
    #: built-in generic ``query`` prompt.
    QUERY_PROMPTS: ClassVar[dict[str, str]] = {
        "vault": (
            "Instruct: Given a documentation search query, retrieve "
            "relevant project documentation passages that answer the "
            "query\nQuery: "
        ),
        "code": (
            "Instruct: Given a code search query, retrieve relevant "
            "source code snippets that implement or relate to it"
            "\nQuery: "
        ),
        "document": (
            "Instruct: Given a document search query, retrieve relevant "
            "passages from explicitly indexed source documents"
            "\nQuery: "
        ),
    }

    def encode_query(self, query: str, *, surface: str | None = None) -> np.ndarray:
        """Encode a search query as a dense embedding on GPU.

        Uses Qwen3's instruction-based encoding: a surface-specific
        instruction when *surface* names one, otherwise the model's
        built-in generic query prompt.

        Args:
            query: Natural language query string.
            surface: Target corpus kind (``"vault"``, ``"code"``, or
                ``"document"``),
                or ``None`` for the generic prompt.

        Returns:
            numpy array of shape ``(dimension,)`` with normalized embedding.

        Raises:
            torch.cuda.OutOfMemoryError: If the GPU runs out of memory.
        """
        import numpy as np

        prompt = self.QUERY_PROMPTS.get(surface) if surface else None
        if prompt is not None:
            embeddings = self._dense_model.encode(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers encode overloads are partially stubbed
                [query],
                prompt=prompt,
                normalize_embeddings=True,
            )
        else:
            embeddings = self._dense_model.encode(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers encode overloads are partially stubbed
                [query],
                prompt_name="query",
                normalize_embeddings=True,
            )
        return np.asarray(embeddings[0], dtype=np.float32)

    def encode_documents_sparse(
        self,
        texts: list[str],
        *,
        batch_size: int | None = None,
        gpu_lock: threading.Lock | None = None,
    ) -> list[SparseResult]:
        """Encode documents in bounded SPLADE batches with forward-only locking.

        Args:
            texts: List of document texts.
            batch_size: Inner sub-batch size for SPLADE encoding.
                Defaults to :meth:`_default_encode_batch_size`
                (config ``embedding_encode_batch_size``) so the
                sparse path mirrors the dense path's length-uniform
                sub-batching strategy.
            gpu_lock: Optional process-wide GPU lock. Each bounded model
                forward holds it independently; device-to-host transfer,
                sparse conversion, and result mapping run after release.

        Returns:
            List of SparseResult objects with .indices and .values.

        Raises:
            torch.cuda.OutOfMemoryError: If encoding fails even at
                batch_size=1.
        """
        import torch

        if batch_size is None:
            batch_size = self._default_encode_batch_size()
        if batch_size <= 0:
            raise ValueError(f"batch_size must be a positive integer, got {batch_size}")
        batch_size = self._sparse_batch_ceiling.clamp(batch_size)

        max_chars = self._default_max_embed_chars()
        truncated = [t[:max_chars] for t in texts]

        while True:
            results: list[SparseResult] = []
            try:
                for start in range(0, len(truncated), batch_size):
                    texts_batch = truncated[start : start + batch_size]
                    try:
                        results.extend(
                            self._encode_sparse_batch(texts_batch, batch_size, gpu_lock)
                        )
                    finally:
                        del texts_batch
            except torch.cuda.OutOfMemoryError:
                del results
                torch.cuda.empty_cache()
                if batch_size <= 1:
                    raise
                batch_size = self._sparse_batch_ceiling.record_oom(batch_size)
                logger.warning(
                    "CUDA OOM during sparse encoding, retrying with batch_size=%d",
                    batch_size,
                )
            else:
                self._sparse_batch_ceiling.record_success(batch_size)
                return results

    def _encode_sparse_batch(
        self,
        texts_batch: list[str],
        batch_size: int,
        gpu_lock: threading.Lock | None,
    ) -> list[SparseResult]:
        """Run one sparse forward, then move and convert it outside the GPU lock."""
        from .memory_probe import cuda_forward_peak_capture

        sparse_model = self._require_sparse_model()
        accelerator_tensor = None
        cpu_tensor = None
        cpu_sparse_tensor = None
        try:
            if gpu_lock is None:
                accelerator_tensor = cast(
                    "Tensor",
                    sparse_model.encode_document(
                        texts_batch,
                        batch_size=batch_size,
                        show_progress_bar=False,
                        convert_to_tensor=True,
                        convert_to_sparse_tensor=False,
                        save_to_cpu=False,
                    ),
                )
            else:
                with timed_gpu_lock(gpu_lock), cuda_forward_peak_capture():
                    accelerator_tensor = cast(
                        "Tensor",
                        sparse_model.encode_document(
                            texts_batch,
                            batch_size=batch_size,
                            show_progress_bar=False,
                            convert_to_tensor=True,
                            convert_to_sparse_tensor=False,
                            save_to_cpu=False,
                        ),
                    )
            # Sentence Transformers otherwise performs this transfer inside
            # encode when save_to_cpu=True. Release the GPU tensor first.
            cpu_tensor = accelerator_tensor.cpu()
            del accelerator_tensor
            accelerator_tensor = None
            cpu_sparse_tensor = cpu_tensor.to_sparse().coalesce()
            del cpu_tensor
            cpu_tensor = None
            return _sparse_tensor_to_results(cpu_sparse_tensor)
        finally:
            del accelerator_tensor
            del cpu_tensor
            del cpu_sparse_tensor

    def encode_query_sparse(self, query: str) -> SparseResult:
        """Encode a search query as a SPLADE sparse vector on GPU.

        Args:
            query: Natural language query string.

        Returns:
            SparseResult with .indices and .values.

        Raises:
            torch.cuda.OutOfMemoryError: If the GPU runs out of memory.
        """
        max_chars = self._default_max_embed_chars()
        sparse_tensor = self._require_sparse_model().encode_query([query[:max_chars]])
        results = _sparse_tensor_to_results(sparse_tensor)
        return results[0]
