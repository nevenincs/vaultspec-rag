"""Torch-free offline checks for complete, loadable model snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, cast

from ._sparse_profile import SPARSE_MODEL_ID, sparse_model_revision

_TOKENIZER_FILENAMES = frozenset(
    {
        "tokenizer.json",
        "tokenizer.model",
        "vocab.json",
        "vocab.txt",
        "spiece.model",
    },
)


class _SnapshotLoader(Protocol):
    def snapshot_download(self, model_id: str, **kwargs: object) -> str: ...


def cached_snapshot_is_complete(
    model_id: str,
    *,
    cache_dir: Path | None = None,
) -> bool:
    """Validate config, tokenizer, and complete local model weights offline."""
    import huggingface_hub

    hub = cast("_SnapshotLoader", huggingface_hub)
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        snapshot_value = hub.snapshot_download(
            model_id,
            revision=sparse_model_revision(model_id),
            cache_dir=cache_dir,
            local_files_only=True,
        )
    except (LocalEntryNotFoundError, OSError):
        return False
    snapshot = Path(snapshot_value)
    if model_id == SPARSE_MODEL_ID and not all(
        (snapshot / name).is_file()
        for name in (
            "modeling_splade.py",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
        )
    ):
        return False
    if not (snapshot / "config.json").is_file():
        return False
    if not any(
        path.name in _TOKENIZER_FILENAMES
        for path in snapshot.rglob("*")
        if path.is_file()
    ):
        return False
    return _snapshot_has_complete_weights(
        snapshot, safetensors_only=model_id == SPARSE_MODEL_ID
    )


def _snapshot_has_complete_weights(
    snapshot: Path, *, safetensors_only: bool = False
) -> bool:
    """Return whether a snapshot has an unsharded weight or every indexed shard."""
    index_files = [
        path
        for path in snapshot.rglob("*.index.json")
        if ("weight" in path.name or "model" in path.name)
        and (not safetensors_only or path.name.endswith(".safetensors.index.json"))
    ]
    saw_weight_index = False
    for index_path in index_files:
        try:
            payload = cast(
                "dict[str, object]",
                json.loads(index_path.read_text(encoding="utf-8")),
            )
            weight_map = payload.get("weight_map", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if isinstance(weight_map, dict) and weight_map:
            saw_weight_index = True
            shard_values = list(
                cast("dict[object, object]", weight_map).values(),
            )
            if all(isinstance(value, str) for value in shard_values) and all(
                (snapshot / cast("str", shard)).is_file() for shard in shard_values
            ):
                return True

    if saw_weight_index:
        return False
    return any(snapshot.rglob("*.safetensors")) or (
        not safetensors_only and any(snapshot.rglob("pytorch_model*.bin"))
    )
