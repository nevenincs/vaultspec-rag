"""Real-model acceptance coverage for the Apple silicon MPS backend."""

from __future__ import annotations

import os
import platform
import sys
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pytest import MonkeyPatch

pytestmark = [pytest.mark.mps, pytest.mark.timeout(600)]


class _ResidentParameter(Protocol):
    """The one attribute this file needs off a torch parameter."""

    @property
    def device(self) -> object: ...


def _assert_parameters_on_mps(label: str, module: object) -> None:
    """Prove a resident model's parameters, not just its wrapper, use MPS."""
    attribute = getattr(module, "parameters", None)
    assert callable(attribute), f"{label} exposes no parameter iterator"
    parameters = cast("Callable[[], Iterable[_ResidentParameter]]", attribute)
    devices = {str(parameter.device) for parameter in parameters()}
    assert devices, f"{label} exposes no resident parameters"
    assert all(device.startswith("mps") for device in devices), (
        f"{label} parameters are not all on MPS: {sorted(devices)}"
    )


def test_configured_model_stack_runs_together_on_mps(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep all configured models resident while each completes a real forward.

    The hardware tier must fail, rather than skip, when it is routed to the
    wrong host, when its preprovisioned snapshots are absent, or when PyTorch
    cannot execute one of the configured operations on MPS. Running forwards
    serially is intentional: production owns one accelerator consumer and does
    not overlap model kernels on a single device.
    """
    assert sys.platform == "darwin", "the MPS tier requires a macOS runner"
    assert platform.machine().lower() in {
        "arm64",
        "aarch64",
    }, "the MPS tier requires Apple silicon"
    assert os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "0", (
        "the MPS tier must set PYTORCH_ENABLE_MPS_FALLBACK=0 explicitly"
    )

    # The runner image owns the model cache. The support guard reads it without
    # downloading or creating a second cache, so a missing provisioned snapshot
    # is a visible runner failure rather than persistent machine pollution.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("VAULTSPEC_RAG_SPARSE_ENABLED", "1")
    monkeypatch.setenv("VAULTSPEC_RAG_RERANKER_ENABLED", "1")

    from ..._gpu import load_accelerator
    from ...config._settings import get_config, reset_config
    from ...service import ServiceRegistry

    reset_config()
    accelerator = load_accelerator()
    assert accelerator.backend == "mps"
    assert accelerator.device == "mps"
    assert accelerator.memory_kind == "unified"

    cfg = get_config()
    assert cfg.sparse_enabled
    assert cfg.reranker_enabled

    registry = ServiceRegistry()
    model = None
    reranker = None
    try:
        registry.load_model()
        model = registry.model
        reranker = registry.get_reranker()

        # Reaching these forwards with both objects live proves the configured
        # dense, sparse, and reranker stacks fit and execute while co-resident.
        assert model.device == "mps"
        _assert_parameters_on_mps("dense model", model._dense_model)
        _assert_parameters_on_mps("sparse model", model._require_sparse_model())
        _assert_parameters_on_mps("reranker", reranker.model)
        dense = model.encode_query("accelerator backend selection")
        sparse = model.encode_query_sparse("accelerator backend selection")
        scores = reranker.predict(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers stubs incomplete
            [("accelerator backend", "Apple silicon uses the MPS backend.")],
            batch_size=1,
            show_progress_bar=False,
        )

        assert dense.shape == (model.dimension,)
        assert np.isfinite(dense).all()
        assert sparse.indices
        assert sparse.values
        assert np.isfinite(np.asarray(sparse.values, dtype=np.float32)).all()
        assert len(scores) == 1
        assert np.isfinite(np.asarray(scores, dtype=np.float32)).all()
    finally:
        del model
        del reranker
        registry.close_all()
        reset_config()
