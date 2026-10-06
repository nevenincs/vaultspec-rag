"""Pinned upstream sparse inference with CPU preparation separated from forward.

The sparse model's repository ships the Python that builds it. That file is
the one piece of a default model this package executes, so it is handled
apart from everything else: it is read once from the verified snapshot,
checked against its committed digest, and imported from that same buffer.
The model library's own route for repository code is never used, because it
imports a copy from a cache of its own without comparing it to the snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from ._model_pins import committed_manifest
from ._sparse_profile import SPARSE_MODEL_ID, SPARSE_MODEL_REVISION, SPARSE_VOCAB_SIZE
from ._verified_import import import_verified_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from torch import Tensor

    from ._gpu import AcceleratorContext
    from ._model_cache import VerifiedSnapshot

#: The file in the sparse model's repository that defines the model, and the
#: class in it this package constructs.
_MODEL_SOURCE = "modeling_splade.py"
_MODEL_CLASS = "SpladeModel"


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


def require_reviewed_sparse_model(model_id: str) -> None:
    """Refuse any sparse repository but the reviewed one.

    Raises:
        ValueError: If *model_id* is not the reviewed sparse model. Raised
            before anything is fetched, so naming another repository never
            downloads it.
    """
    if model_id != SPARSE_MODEL_ID:
        raise ValueError(
            f"Unsupported sparse model {model_id!r}; use {SPARSE_MODEL_ID}"
        )


def class_from_verified_source(
    snapshot: VerifiedSnapshot, *, source: str, expected_sha256: str, name: str
) -> object:
    """Return class *name* from a source file in *snapshot*, verified first.

    The file is read through the handle the snapshot check holds, so the
    bytes hashed here are bytes of the file that check hashed, and the buffer
    hashed here is the buffer executed. The model library's machinery for
    repository code is not entered at all.

    Args:
        snapshot: A snapshot that passed its check and is still held.
        source: The source file, relative to the snapshot.
        expected_sha256: The digest committed for that file.
        name: The class to return from it.

    Raises:
        UnverifiedSourceError: If the source does not match its digest.
            Nothing from it has run.
    """
    module = import_verified_source(
        snapshot.read(source),
        expected_sha256=expected_sha256,
        filename=str(snapshot.directory / source),
    )
    return vars(module)[name]


def reviewed_model_class(snapshot: VerifiedSnapshot) -> object:
    """Import the sparse model's class from the verified snapshot."""
    manifest = committed_manifest(SPARSE_MODEL_ID, SPARSE_MODEL_REVISION)
    if manifest is None:
        raise RuntimeError(f"no file digests are committed for {SPARSE_MODEL_ID}")
    return class_from_verified_source(
        snapshot,
        source=_MODEL_SOURCE,
        expected_sha256=manifest[_MODEL_SOURCE],
        name=_MODEL_CLASS,
    )


class SparseModelAdapter:
    """Keep the reviewed model's preprocessing, pooling and vocabulary folding."""

    def __init__(
        self,
        model_id: str,
        *,
        snapshot: VerifiedSnapshot,
        accelerator: AcceleratorContext,
    ) -> None:
        torch = accelerator.torch
        from transformers import AutoTokenizer

        require_reviewed_sparse_model(model_id)
        directory = str(snapshot.directory)
        loader = cast("_PretrainedLoader", reviewed_model_class(snapshot))
        model = cast(
            "_UpstreamSparseModel",
            loader.from_pretrained(
                directory,
                local_files_only=True,
                use_safetensors=True,
                dtype=torch.float32,
                attn_implementation="sdpa",
            ),
        )
        model.to(accelerator.device).eval()
        self._model = model
        tokenizer_loader = cast("_PretrainedLoader", AutoTokenizer)
        tokenizer = tokenizer_loader.from_pretrained(directory, local_files_only=True)
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
