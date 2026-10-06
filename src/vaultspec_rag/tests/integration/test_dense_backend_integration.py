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

from ...config._types import EnvVar
from .._config_fixtures import reset_config


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
            # The default dense model is pinned, and its release holds no ONNX
            # graph a digest could vouch for, so the ONNX backend is not
            # attempted for it and the loader must use torch.
            with caplog.at_level(logging.WARNING, logger="vaultspec_rag.embeddings"):
                model = EmbeddingModel()
            vecs = model.encode_documents_on_device(["def f(x):\n    return x + 1\n"])
            assert vecs.shape[0] == 1
            assert vecs.shape[1] == model.dimension
            # Pinned to the reason the torch backend was used: an ONNX graph
            # loaded for a pinned model would be an unverified file, and this
            # must not quietly become a test of that.
            assert any(
                "ONNX dense backend is not used with a pinned model" in r.message
                for r in caplog.records
            ), "expected the warning that a pinned model stays on torch"
        finally:
            if prev is None:
                os.environ.pop(EnvVar.DENSE_BACKEND.value, None)
            else:
                os.environ[EnvVar.DENSE_BACKEND.value] = prev
            reset_config()
