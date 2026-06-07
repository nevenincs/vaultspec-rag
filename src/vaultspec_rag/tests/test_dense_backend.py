"""Unit tests for the dense-encoder backend config seam (#155).

The dense backend defaults to torch and is overridable by env var. The actual
ONNX path is exercised by the real-GPU fallback test in
``integration/test_dense_backend_integration.py``.
"""

from __future__ import annotations

import os

from ..config import EnvVar, get_config, reset_config


class TestDenseBackendConfig:
    def test_default_is_torch(self) -> None:
        reset_config()
        assert get_config().dense_backend == "torch"
        assert get_config().dense_onnx_file == "onnx/model_O4.onnx"

    def test_env_override(self) -> None:
        prev = os.environ.get(EnvVar.DENSE_BACKEND.value)
        os.environ[EnvVar.DENSE_BACKEND.value] = "onnx"
        reset_config()
        try:
            assert get_config().dense_backend == "onnx"
        finally:
            if prev is None:
                os.environ.pop(EnvVar.DENSE_BACKEND.value, None)
            else:
                os.environ[EnvVar.DENSE_BACKEND.value] = prev
            reset_config()
