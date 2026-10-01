"""Unit coverage for lazy embedding compute-dependency remediation."""

from __future__ import annotations

import importlib.util

import pytest


@pytest.mark.unit
def test_missing_torch_explains_cuda_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thin base directs a compute request to explicit CUDA provisioning."""
    from .. import _gpu, embeddings

    def missing_torch() -> object:
        raise ImportError("torch is absent")

    monkeypatch.setattr(_gpu, "load_accelerator", missing_torch)

    with pytest.raises(ImportError) as raised:
        embeddings._check_rag_deps()

    from ..operator_state._provisioning import host_install_command

    message = str(raised.value)
    assert "torch is missing" in message
    assert host_install_command() in message


@pytest.mark.unit
def test_missing_sentence_transformers_explains_cuda_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete CUDA environment receives the same actionable remedy."""
    from .. import _gpu, embeddings

    original_find_spec = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object:
        if name == "sentence_transformers":
            return None
        return original_find_spec(name, package)

    monkeypatch.setattr(_gpu, "load_accelerator", lambda: object())
    monkeypatch.setattr(importlib.util, "find_spec", find_spec)

    with pytest.raises(ImportError) as raised:
        embeddings._check_rag_deps()

    from ..operator_state._provisioning import host_install_command

    message = str(raised.value)
    assert "sentence-transformers is missing" in message
    assert host_install_command() in message
