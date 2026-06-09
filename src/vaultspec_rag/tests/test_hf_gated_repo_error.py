"""Unit tests for HuggingFace gated/inaccessible repo error mapping.

Verifies that ``_raise_for_hf_access`` converts ``GatedRepoError`` and
``RepositoryNotFoundError`` into actionable ``RuntimeError`` messages
without any mocks -- just real exception instances.

``HfHubHTTPError.__init__`` requires an ``httpx.Response`` (which is a
transitive dependency of huggingface-hub). We construct minimal real
``httpx.Request`` / ``httpx.Response`` values to satisfy the signature.
"""

from __future__ import annotations

import httpx
import pytest
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

from ..embeddings import _raise_for_hf_access


def _gated_exc(model_id: str) -> GatedRepoError:
    req = httpx.Request("GET", f"https://huggingface.co/{model_id}")
    resp = httpx.Response(403, request=req)
    return GatedRepoError("403 Forbidden", response=resp)


def _not_found_exc(model_id: str) -> RepositoryNotFoundError:
    req = httpx.Request("GET", f"https://huggingface.co/{model_id}")
    resp = httpx.Response(404, request=req)
    return RepositoryNotFoundError("404 Not Found", response=resp)


@pytest.mark.unit
class TestRaiseForHfAccess:
    def test_gated_repo_error_contains_model_id(self) -> None:
        model_id = "naver/splade-v3"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _gated_exc(model_id))
        assert model_id in str(exc_info.value)

    def test_gated_repo_error_contains_hf_token(self) -> None:
        model_id = "naver/splade-v3"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _gated_exc(model_id))
        assert "HF_TOKEN" in str(exc_info.value)

    def test_gated_repo_error_contains_model_url(self) -> None:
        model_id = "naver/splade-v3"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _gated_exc(model_id))
        assert f"https://huggingface.co/{model_id}" in str(exc_info.value)

    def test_gated_repo_error_chained(self) -> None:
        model_id = "naver/splade-v3"
        original = _gated_exc(model_id)
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, original)
        assert exc_info.value.__cause__ is original

    def test_repository_not_found_error_contains_model_id(self) -> None:
        model_id = "Qwen/Qwen3-Embedding-0.6B"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _not_found_exc(model_id))
        assert model_id in str(exc_info.value)

    def test_repository_not_found_error_contains_hf_token(self) -> None:
        model_id = "Qwen/Qwen3-Embedding-0.6B"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _not_found_exc(model_id))
        assert "HF_TOKEN" in str(exc_info.value)

    def test_repository_not_found_error_contains_model_url(self) -> None:
        model_id = "Qwen/Qwen3-Embedding-0.6B"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _not_found_exc(model_id))
        assert f"https://huggingface.co/{model_id}" in str(exc_info.value)

    def test_repository_not_found_error_chained(self) -> None:
        model_id = "Qwen/Qwen3-Embedding-0.6B"
        original = _not_found_exc(model_id)
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, original)
        assert exc_info.value.__cause__ is original

    def test_gated_message_uses_gated_wording(self) -> None:
        model_id = "naver/splade-v3"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _gated_exc(model_id))
        assert "gated" in str(exc_info.value).lower()

    def test_not_found_message_distinguishes_from_gated(self) -> None:
        model_id = "Qwen/Qwen3-Embedding-0.6B"
        with pytest.raises(RuntimeError) as exc_info:
            _raise_for_hf_access(model_id, _not_found_exc(model_id))
        # must NOT say "gated" for a 404
        assert "gated" not in str(exc_info.value).lower()
