"""GPU-native embedding model wrapper for vault semantic search.

Uses sentence-transformers with Qwen3-Embedding-0.6B (1024d) for dense
embeddings and SPLADE v3 via SparseEncoder for sparse embeddings.
Requires CUDA GPU -- no CPU fallback.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import EnvVar

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["EmbeddingModel", "SparseResult"]


@dataclass
class SparseResult:
    """Sparse embedding result compatible with Qdrant SparseVector interface.

    Wraps SPLADE COO tensor output into .indices / .values arrays
    that match the interface expected by VaultStore.hybrid_search.
    """

    indices: list[int]
    values: list[float]


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
            "Run: uv pip install sentence-transformers torch",
        ) from None

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. "
            "Run: uv pip install sentence-transformers>=5.0",
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
        results = []
        for i in range(csr.shape[0]):
            row = csr.getrow(i)
            indices = row.indices.tolist()
            values = row.data.tolist()
            results.append(SparseResult(indices=indices, values=values))
        return results

    if isinstance(sparse_tensor, torch.Tensor):
        if sparse_tensor.is_sparse or sparse_tensor.is_sparse_csr:
            dense = sparse_tensor.to_dense()
        else:
            dense = sparse_tensor
        results = []
        for i in range(dense.shape[0]):
            row = dense[i]
            nz = row.nonzero(as_tuple=True)[0]
            indices = nz.tolist()
            values = row[nz].tolist()
            results.append(SparseResult(indices=indices, values=values))
        return results

    # numpy array fallback
    import numpy as _np

    arr = _np.asarray(sparse_tensor)
    results = []
    for i in range(arr.shape[0]):
        row = arr[i]
        nz = row.nonzero()[0]
        indices = nz.tolist()
        values = row[nz].tolist()
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
        """Return the configured embedding batch size.

        Returns:
            Batch size from VaultSpecConfigWrapper.
        """
        from .config import get_config

        return get_config().embedding_batch_size

    @staticmethod
    def _default_max_embed_chars() -> int:
        """Return the configured max characters per document.

        Returns:
            Character limit from VaultSpecConfigWrapper.
        """
        from .config import get_config

        return get_config().max_embed_chars

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
        from sentence_transformers import SentenceTransformer, SparseEncoder

        from .config import get_config

        cfg = get_config()
        dense_name = model_name or cfg.embedding_model
        sparse_name = (
            cfg.sparse_model
            if hasattr(cfg, "sparse_model") and cfg.sparse_model
            else self.SPARSE_MODEL_NAME
        )

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
        self._dense_model = SentenceTransformer(
            dense_name,
            model_kwargs=model_kwargs,
            tokenizer_kwargs={"padding_side": "left"},
        )
        logger.info("Dense model loaded in %.2fs", time.perf_counter() - t0)

        t0 = time.perf_counter()
        self._sparse_model = SparseEncoder(
            sparse_name,
            device="cuda",
            model_kwargs={"torch_dtype": torch.float16},
        )
        logger.info("Sparse model loaded in %.2fs", time.perf_counter() - t0)

        self._device = "cuda"
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
            batch_size: Max texts per encoding batch.

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
            batch_size = self._default_batch_size()

        max_chars = self._default_max_embed_chars()
        truncated = [t[:max_chars] for t in texts]

        while True:
            try:
                embeddings = self._dense_model.encode(
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

    def encode_query(self, query: str) -> np.ndarray:
        """Encode a search query as a dense embedding on GPU.

        Uses prompt_name="query" for Qwen3's instruction-based encoding.

        Args:
            query: Natural language query string.

        Returns:
            numpy array of shape ``(dimension,)`` with normalized embedding.

        Raises:
            torch.cuda.OutOfMemoryError: If the GPU runs out of memory.
        """
        import numpy as np

        embeddings = self._dense_model.encode(
            [query],
            prompt_name="query",
            normalize_embeddings=True,
        )
        return np.asarray(embeddings[0], dtype=np.float32)

    def encode_documents_sparse(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
    ) -> list[SparseResult]:
        """Encode document texts as SPLADE sparse vectors on GPU.

        Args:
            texts: List of document texts.
            batch_size: Max texts per encoding batch.

        Returns:
            List of SparseResult objects with .indices and .values.

        Raises:
            torch.cuda.OutOfMemoryError: If encoding fails even at
                batch_size=1.
        """
        import torch

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
