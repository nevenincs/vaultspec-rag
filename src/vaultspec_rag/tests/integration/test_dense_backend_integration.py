"""Real-GPU test: the ONNX dense backend degrades to torch, never crashes (#155).

Selecting ``dense_backend=onnx`` without ``optimum`` / ``onnxruntime-gpu`` (or
in an onnxruntime-incompatible CUDA environment) must fall back to the torch
construction and still produce valid embeddings - the
``embedding-backend-falls-back-to-torch`` rule. No mocks: a real EmbeddingModel
is built on the GPU.
"""

from __future__ import annotations

import logging
import os

import pytest

from ...config import EnvVar, reset_config


@pytest.mark.integration
class TestDenseBackendFallback:
    @pytest.mark.timeout(300)
    def test_onnx_backend_falls_back_to_torch(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from ... import EmbeddingModel

        prev = os.environ.get(EnvVar.DENSE_BACKEND.value)
        os.environ[EnvVar.DENSE_BACKEND.value] = "onnx"
        reset_config()
        try:
            # optimum / onnxruntime-gpu are not project deps, so the ONNX
            # construction fails and the loader must degrade to torch.
            with caplog.at_level(logging.WARNING, logger="vaultspec_rag.embeddings"):
                model = EmbeddingModel()
            vecs = model.encode_documents(["def f(x):\n    return x + 1\n"])
            assert vecs.shape[0] == 1
            assert vecs.shape[1] == model.dimension
            # Pin the test to the fallback path: a future ONNX dep must not
            # silently convert this into a happy-path test (review M1).
            assert any(
                "ONNX dense backend unavailable" in r.message for r in caplog.records
            ), "expected the ONNX->torch fallback warning"
        finally:
            if prev is None:
                os.environ.pop(EnvVar.DENSE_BACKEND.value, None)
            else:
                os.environ[EnvVar.DENSE_BACKEND.value] = prev
            reset_config()
