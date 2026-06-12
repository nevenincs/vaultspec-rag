"""GPU-native embedding model wrapper for vault semantic search.

Uses sentence-transformers with Qwen3-Embedding-0.6B (1024d) for dense
embeddings and SPLADE v3 via SparseEncoder for sparse embeddings.
Requires CUDA GPU -- no CPU fallback.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from .config import EnvVar

if TYPE_CHECKING:
    import numpy as np
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

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
        """Return the cached entry for *key*, refreshing its recency."""
        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                self._data.move_to_end(key)
            return entry

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
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA GPU required. No CUDA device found. "
                "Install torch with CUDA support.",
            )
    except ImportError:
        raise ImportError(
            "GPU RAG dependencies not installed. "
            "Run: uv sync (then `vaultspec-rag install` for CUDA torch wheels).",
        ) from None

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
    """

    MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
    SPARSE_MODEL_NAME = "naver/splade-v3"
    DEFAULT_DIMENSION = 1024
    DEFAULT_BATCH_SIZE = 64
    MAX_EMBED_CHARS = 8000

    @staticmethod
    def _default_batch_size() -> int:
        """Return the configured streaming slice size.

        Note this is the *slice* size (one slice's worth of docs is
        encoded + upserted before the next slice begins). It is NOT
        the inner sub-batch size that the model's encode call uses
        for its forward passes - that is governed by
        :meth:`_default_encode_batch_size`.
        """
        from .config import get_config

        return get_config().embedding_batch_size

    @staticmethod
    def _default_encode_batch_size() -> int:
        """Return the configured inner sub-batch size for ``encode``.

        SentenceTransformer sorts each ``encode`` call's input by
        sequence length, then iterates ``encode_batch_size``-item
        sub-batches of the sorted list. A small value (default 8)
        keeps each sub-batch length-uniform and minimises padding
        waste on variable-length corpora.
        """
        from .config import get_config

        return get_config().embedding_encode_batch_size

    @staticmethod
    def _default_max_embed_chars() -> int:
        """Return the configured max characters per document.

        Returns:
            Character limit from VaultSpecConfigWrapper.
        """
        from .config import get_config

        return get_config().max_embed_chars

    @staticmethod
    def _load_dense_model(
        dense_name: str,
        model_kwargs: dict[str, object],
        cfg: object,
    ) -> SentenceTransformer:
        """Construct the dense SentenceTransformer for the configured backend.

        The default backend is ``torch``. When ``dense_backend == "onnx"`` the
        model is loaded with the ONNX backend on ``CUDAExecutionProvider`` using
        the cached O4 file (``dense_onnx_file``). Any failure - missing
        ``optimum`` / ``onnxruntime-gpu``, export error, or a GPU provider that
        cannot load (e.g. the onnxruntime CUDA-12 vs torch CUDA-13 mismatch) -
        logs a warning and falls back to the torch construction, so a
        misconfigured backend never breaks indexing or search (rule
        ``embedding-backend-falls-back-to-torch``; see ADR
        ``2026-06-02-onnx-encoder-backend``). The ONNX path is experimental and
        opt-in: selecting it requires ``sentence-transformers[onnx-gpu]`` in an
        onnxruntime-compatible CUDA environment.
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
                model_kwargs=model_kwargs,
                processor_kwargs={"padding_side": "left"},
            )
        except Exception as exc:
            from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

            if isinstance(exc, (GatedRepoError, RepositoryNotFoundError)):
                _raise_for_hf_access(dense_name, exc)
            raise

    def __init__(self, model_name: str | None = None) -> None:
        """Load dense and sparse models onto GPU.

        Args:
            model_name: Override the dense embedding model name.
                Defaults to the config value or MODEL_NAME.

        Raises:
            ImportError: If sentence-transformers or torch not installed.
            RuntimeError: If no CUDA GPU is available.
        """
        _check_rag_deps()

        import torch
        from sentence_transformers import SparseEncoder

        from .config import get_config

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
            os.environ.get(EnvVar.HF_HOME, "~/.cache/huggingface"),
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
        self._dense_model = self._load_dense_model(dense_name, model_kwargs, cfg)
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

        t0 = time.perf_counter()
        try:
            self._sparse_model = SparseEncoder(
                sparse_name,
                device="cuda",
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
        logger.info(
            "Sparse model loaded in %.2fs (max_seq_length=%d, native cap)",
            time.perf_counter() - t0,
            sparse_max,
        )

        self._device = "cuda"
        self.query_cache = QueryEmbeddingCache()
        self.dimension: int = (
            cfg.embedding_dimension
            if hasattr(cfg, "embedding_dimension")
            else self.DEFAULT_DIMENSION
        )

        gpu_name = torch.cuda.get_device_name(0)
        logger.info(
            "Embedding models loaded on %s (dense=%s, sparse=%s, dim=%d)",
            gpu_name,
            dense_name,
            sparse_name,
            self.dimension,
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
        import torch

        if batch_size is None:
            batch_size = self._default_encode_batch_size()

        max_chars = self._default_max_embed_chars()
        truncated = [t[:max_chars] for t in texts]

        while True:
            try:
                embeddings = self._dense_model.encode(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers encode overloads are partially stubbed
                    truncated,
                    batch_size=batch_size,
                    show_progress_bar=len(truncated) > 100,
                    normalize_embeddings=True,
                )
                return np.asarray(embeddings, dtype=np.float32)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch_size <= 1:
                    raise
                batch_size = max(1, batch_size // 2)
                logger.warning(
                    "CUDA OOM during dense encoding, retrying with batch_size=%d",
                    batch_size,
                )

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
    }

    def encode_query(self, query: str, *, surface: str | None = None) -> np.ndarray:
        """Encode a search query as a dense embedding on GPU.

        Uses Qwen3's instruction-based encoding: a surface-specific
        instruction when *surface* names one, otherwise the model's
        built-in generic query prompt.

        Args:
            query: Natural language query string.
            surface: Target corpus kind (``"vault"`` or ``"code"``),
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
    ) -> list[SparseResult]:
        """Encode document texts as SPLADE sparse vectors on GPU.

        Args:
            texts: List of document texts.
            batch_size: Inner sub-batch size for SPLADE encoding.
                Defaults to :meth:`_default_encode_batch_size`
                (config ``embedding_encode_batch_size``) so the
                sparse path mirrors the dense path's length-uniform
                sub-batching strategy.

        Returns:
            List of SparseResult objects with .indices and .values.

        Raises:
            torch.cuda.OutOfMemoryError: If encoding fails even at
                batch_size=1.
        """
        import torch

        if batch_size is None:
            batch_size = self._default_encode_batch_size()

        max_chars = self._default_max_embed_chars()
        truncated = [t[:max_chars] for t in texts]

        while True:
            try:
                sparse_tensor = self._sparse_model.encode_document(
                    truncated,
                    batch_size=batch_size,
                )
                return _sparse_tensor_to_results(sparse_tensor)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch_size <= 1:
                    raise
                batch_size = max(1, batch_size // 2)
                logger.warning(
                    "CUDA OOM during sparse encoding, retrying with batch_size=%d",
                    batch_size,
                )

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
        sparse_tensor = self._sparse_model.encode_query([query[:max_chars]])
        results = _sparse_tensor_to_results(sparse_tensor)
        return results[0]
