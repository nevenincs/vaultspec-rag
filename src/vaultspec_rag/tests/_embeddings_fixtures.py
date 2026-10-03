"""Host-side dense document encoding for tests.

Production keeps the dense document result on the accelerator and pays the
single device-to-host transfer at the indexer's streaming seam. A test that
asserts on the vectors themselves wants an ordinary array instead, so the
conversion lives here rather than as a second production entry point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from ..embeddings import EmbeddingModel


def encode_documents(
    model: EmbeddingModel,
    texts: list[str],
    *,
    batch_size: int | None = None,
) -> np.ndarray:
    """Encode *texts* and materialise the normalized rows as a host array.

    Args:
        model: The embedding model to encode with.
        texts: Document texts (title + body).
        batch_size: Item-count cap per planned encode bucket, applied on top
            of the token budget. Defaults to the configured encode batch size.

    Returns:
        A ``(n, dimension)`` array of normalized embeddings.
    """
    import numpy as np

    embeddings = model._encode_documents_output(  # pyright: ignore[reportPrivateUsage]  # the host-side conversion production does not need
        texts,
        batch_size=batch_size,
        retain_on_device=False,
    )
    return np.asarray(embeddings, dtype=np.float32)
