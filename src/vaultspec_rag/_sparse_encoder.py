"""Pinned upstream sparse inference with CPU preparation separated from forward."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from ._sparse_profile import SPARSE_MODEL_ID, SPARSE_VOCAB_SIZE, sparse_model_revision

if TYPE_CHECKING:
    from collections.abc import Callable

    from torch import Tensor

    from ._gpu import AcceleratorContext


class _UpstreamSparseModel(Protocol):
    def to(self, device: str) -> _UpstreamSparseModel: ...
    def eval(self) -> _UpstreamSparseModel: ...
    def encode(
        self, texts: list[str], kind: str = "document", batch_size: int = 32
    ) -> Tensor: ...
    def __call__(
        self, _input_ids: Tensor, _attention_mask: Tensor, _pooling_mask: Tensor, /
    ) -> Tensor: ...


class _PretrainedLoader(Protocol):
    def from_pretrained(self, model_id: str, **kwargs: object) -> object: ...


class SparseModelAdapter:
    """Keep the reviewed model's preprocessing, pooling and vocabulary folding."""

    def __init__(
        self, model_id: str, *, accelerator: AcceleratorContext, local_files_only: bool
    ) -> None:
        torch = accelerator.torch
        from transformers import AutoModel, AutoTokenizer

        if model_id != SPARSE_MODEL_ID:
            raise ValueError(
                f"Unsupported sparse model {model_id!r}; use {SPARSE_MODEL_ID}"
            )
        revision = sparse_model_revision(model_id)
        loader = cast("_PretrainedLoader", AutoModel)
        model = cast(
            "_UpstreamSparseModel",
            loader.from_pretrained(
                model_id,
                revision=revision,
                code_revision=revision,
                trust_remote_code=True,
                token=False,
                local_files_only=local_files_only,
                use_safetensors=True,
                dtype=torch.float32,
                attn_implementation="sdpa",
            ),
        )
        model.to(accelerator.device).eval()
        self._model = model
        tokenizer_loader = cast("_PretrainedLoader", AutoTokenizer)
        tokenizer = tokenizer_loader.from_pretrained(
            model_id, revision=revision, local_files_only=local_files_only, token=False
        )
        # The pinned upstream convenience API lazily loads an unpinned tokenizer.
        # Supply the reviewed tokenizer before using its preprocessing seam.
        tokenizer_attribute = "_tokenizer"
        encode_args_attribute = "_encode_args"
        tokenize_attribute = "_tokenize"
        setattr(model, tokenizer_attribute, tokenizer)
        self._encode_args = cast(
            "Callable[[str, int | None], tuple[str, int]]",
            getattr(model, encode_args_attribute),
        )
        self._tokenize = cast(
            "Callable[[list[str], str, int], tuple[Tensor, Tensor, Tensor, Tensor]]",
            getattr(model, tokenize_attribute),
        )
        self._device = accelerator.device
        self._accelerator = accelerator

    def get_embedding_dimension(self) -> int:
        """Return the reviewed output vocabulary width."""
        return SPARSE_VOCAB_SIZE

    def prepare(self, texts: list[str], *, kind: str) -> tuple[Tensor, Tensor, Tensor]:
        """Run upstream tokenization on CPU before acquiring the forward lock."""
        prefix, max_length = self._encode_args(kind, None)
        ids, attention, pooling, _offsets = self._tokenize(texts, prefix, max_length)
        return ids, attention, pooling

    def forward(self, prepared: tuple[Tensor, Tensor, Tensor]) -> Tensor:
        """Move prepared inputs and run one pooled batch on the accelerator."""
        torch = self._accelerator.torch
        ids, attention, pooling = prepared
        with torch.inference_mode():
            return self._model(
                ids.to(self._device),
                attention.to(self._device),
                pooling.to(self._device),
            )
