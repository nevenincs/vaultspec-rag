"""Bounded Hugging Face acquisition for real model-backed test fixtures."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_SETUP_TIMEOUT_SECONDS = 600.0
_SETUP_TIMEOUT_ENV = "VAULTSPEC_RAG_TEST_MODEL_SETUP_TIMEOUT"
_OUTPUT_TAIL_CHARS = 12_000
_TERMINATE_GRACE_SECONDS = 5.0
_TOKENIZER_FILENAMES = frozenset(
    {
        "tokenizer.json",
        "tokenizer.model",
        "vocab.json",
        "vocab.txt",
        "spiece.model",
    },
)


def model_setup_timeout_seconds() -> float:
    """Return the explicit wall-clock budget for fixture model acquisition."""
    raw = os.environ.get(_SETUP_TIMEOUT_ENV)
    if raw is None:
        return _DEFAULT_SETUP_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as exc:
        msg = f"{_SETUP_TIMEOUT_ENV} must be a positive number, got {raw!r}"
        raise ValueError(msg) from exc
    if timeout <= 0:
        msg = f"{_SETUP_TIMEOUT_ENV} must be positive, got {raw!r}"
        raise ValueError(msg)
    return timeout


def configured_service_model_ids() -> tuple[str, ...]:
    """Return every model the resident service will load during startup."""
    from ..config import get_config

    cfg = get_config()
    model_ids = [str(cfg.embedding_model), str(cfg.sparse_model)]
    if bool(cfg.reranker_enabled):
        model_ids.append(str(cfg.reranker_model))
    return tuple(dict.fromkeys(model_id for model_id in model_ids if model_id))


def ensure_model_snapshots(
    model_ids: Sequence[str],
    *,
    timeout_seconds: float,
    cache_dir: Path | None = None,
    endpoint: str | None = None,
) -> None:
    """Ensure real model snapshots exist, bounding every online metadata retry.

    Warm caches return without spawning a process or touching the network.
    Missing snapshots are acquired by a child process so the caller can
    terminate persistent Hugging Face retries at a fixture-local deadline.
    """
    if timeout_seconds <= 0:
        msg = f"model setup timeout must be positive, got {timeout_seconds}"
        raise ValueError(msg)

    missing = _missing_model_ids(model_ids, cache_dir=cache_dir)
    if not missing:
        return

    command = [
        sys.executable,
        "-m",
        "vaultspec_rag.tests._model_setup",
        "--worker",
        "--models",
        *missing,
    ]
    if cache_dir is not None:
        command.extend(["--cache-dir", str(cache_dir)])
    if endpoint is not None:
        command.extend(["--endpoint", endpoint])

    context = _setup_context(
        missing,
        timeout_seconds=timeout_seconds,
        cache_dir=cache_dir,
        endpoint=endpoint,
    )
    output = run_bounded_process(
        command,
        timeout_seconds=timeout_seconds,
        operation="real Hugging Face model acquisition",
        context=context,
    )

    still_missing = _missing_model_ids(model_ids, cache_dir=cache_dir)
    if still_missing:
        context = _setup_context(
            still_missing,
            timeout_seconds=timeout_seconds,
            cache_dir=cache_dir,
            endpoint=endpoint,
        )
        msg = (
            "model acquisition worker exited successfully but required cached "
            f"config files are still absent; {context}\nworker output tail:\n"
            f"{_output_tail(output)}"
        )
        raise RuntimeError(msg)


def models_are_cached(
    model_ids: Sequence[str],
    *,
    cache_dir: Path | None = None,
) -> bool:
    """Return whether every configured model has a real cached config."""
    return not _missing_model_ids(model_ids, cache_dir=cache_dir)


def run_bounded_process(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    operation: str,
    context: str,
) -> str:
    """Run a real worker process with retained output and a hard deadline."""
    if timeout_seconds <= 0:
        msg = f"worker timeout must be positive, got {timeout_seconds}"
        raise ValueError(msg)

    deadline = time.monotonic() + timeout_seconds
    termination_grace = min(
        _TERMINATE_GRACE_SECONDS,
        max(0.05, timeout_seconds * 0.20),
        timeout_seconds * 0.50,
    )
    worker_deadline = deadline - termination_grace
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = ""
    worker_timeout = worker_deadline - time.monotonic()
    if worker_timeout <= 0.0:
        process.terminate()
        try:
            trailing, _ = process.communicate(
                timeout=max(0.001, deadline - time.monotonic())
            )
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                trailing, _ = process.communicate(
                    timeout=max(0.001, deadline - time.monotonic())
                )
            except subprocess.TimeoutExpired as kill_exc:
                output += _coerce_output(kill_exc.output)
                msg = (
                    f"{operation} exceeded {timeout_seconds:.3f}s "
                    "whole-operation deadline during process creation and the "
                    "killed worker did not exit; "
                    f"termination_grace={termination_grace:.3f}s; {context}\n"
                    f"worker output tail:\n{_output_tail(output)}"
                )
                raise RuntimeError(msg) from kill_exc
        output += trailing or ""
        msg = (
            f"{operation} exceeded {timeout_seconds:.3f}s whole-operation "
            "deadline during process creation; "
            f"termination_grace={termination_grace:.3f}s; {context}\n"
            f"worker output tail:\n{_output_tail(output)}"
        )
        raise RuntimeError(msg)
    try:
        output, _ = process.communicate(timeout=worker_timeout)
    except subprocess.TimeoutExpired as exc:
        output = _coerce_output(exc.output)
        process.terminate()
        try:
            trailing, _ = process.communicate(
                timeout=max(0.001, deadline - time.monotonic())
            )
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                trailing, _ = process.communicate(
                    timeout=max(0.001, deadline - time.monotonic())
                )
            except subprocess.TimeoutExpired as kill_exc:
                output += _coerce_output(kill_exc.output)
                msg = (
                    f"{operation} exceeded {timeout_seconds:.3f}s "
                    "whole-operation deadline and the killed worker did not "
                    f"exit; termination_grace={termination_grace:.3f}s; "
                    f"{context}\nworker output tail:\n{_output_tail(output)}"
                )
                raise RuntimeError(msg) from kill_exc
        output += trailing or ""
        msg = (
            f"{operation} exceeded {timeout_seconds:.3f}s whole-operation "
            f"deadline; termination_grace={termination_grace:.3f}s; {context}\n"
            f"worker output tail:\n{_output_tail(output)}"
        )
        raise RuntimeError(msg) from exc

    if process.returncode != 0:
        msg = (
            f"{operation} failed with exit code {process.returncode}; {context}\n"
            f"worker output tail:\n{_output_tail(output)}"
        )
        raise RuntimeError(msg)
    return output


def _missing_model_ids(
    model_ids: Sequence[str],
    *,
    cache_dir: Path | None,
) -> list[str]:
    """Return model repos without a locally complete loadable snapshot."""
    return [
        model_id
        for model_id in model_ids
        if not _cached_snapshot_is_complete(model_id, cache_dir=cache_dir)
    ]


def _cached_snapshot_is_complete(
    model_id: str,
    *,
    cache_dir: Path | None,
) -> bool:
    """Validate config, tokenizer, and complete local model weights offline."""
    from huggingface_hub import (
        snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # stubs partially unknown
    )
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        snapshot_value = snapshot_download(
            model_id,
            cache_dir=cache_dir,
            local_files_only=True,
        )
    except (LocalEntryNotFoundError, OSError):
        return False
    snapshot = Path(snapshot_value)
    if not (snapshot / "config.json").is_file():
        return False
    if not any(
        path.name in _TOKENIZER_FILENAMES
        for path in snapshot.rglob("*")
        if path.is_file()
    ):
        return False
    return _snapshot_has_complete_weights(snapshot)


def _snapshot_has_complete_weights(snapshot: Path) -> bool:
    """Return whether a snapshot has an unsharded weight or every indexed shard."""
    index_files = [
        path
        for path in snapshot.rglob("*.index.json")
        if "weight" in path.name or "model" in path.name
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
    return any(snapshot.rglob("*.safetensors")) or any(
        snapshot.rglob("pytorch_model*.bin"),
    )


def _setup_context(
    model_ids: Sequence[str],
    *,
    timeout_seconds: float,
    cache_dir: Path | None,
    endpoint: str | None,
) -> str:
    """Render stable failure context for fixture diagnostics."""
    from ..config import EnvVar

    effective_endpoint = endpoint or os.environ.get(
        EnvVar.HF_ENDPOINT.value,
        "https://huggingface.co",
    )
    effective_cache = str(cache_dir) if cache_dir is not None else "<default HF cache>"
    return (
        f"models={list(model_ids)!r}, endpoint={effective_endpoint!r}, "
        f"cache={effective_cache!r}, deadline={timeout_seconds:.3f}s"
    )


def _coerce_output(output: str | bytes | None) -> str:
    """Normalize ``TimeoutExpired.output`` across Python platforms."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _output_tail(output: str) -> str:
    """Retain bounded final worker diagnostics, including the last URL/response."""
    cleaned = output.rstrip()
    if not cleaned:
        return "<no worker output>"
    return cleaned[-_OUTPUT_TAIL_CHARS:]


def _worker(
    model_ids: Sequence[str],
    *,
    cache_dir: Path | None,
    endpoint: str | None,
) -> int:
    """Download real model snapshots in the killable child process."""
    from huggingface_hub import (
        snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # stubs partially unknown
    )

    from ..config import EnvVar

    for model_id in model_ids:
        effective_endpoint = endpoint or os.environ.get(
            EnvVar.HF_ENDPOINT.value,
            "https://huggingface.co",
        )
        metadata_url = (
            f"{effective_endpoint.rstrip('/')}/api/models/"
            f"{quote(model_id, safe='/')}/revision/main"
        )
        print(
            f"acquiring model={model_id!r} metadata_url={metadata_url!r} "
            f"cache={str(cache_dir) if cache_dir is not None else '<default>'!r}",
            flush=True,
        )
        snapshot = snapshot_download(
            model_id,
            cache_dir=cache_dir,
            endpoint=endpoint,
        )
        print(f"acquired model={model_id!r} snapshot={snapshot!r}", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse the private worker command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--models", nargs="+", default=[])
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--endpoint")
    return parser.parse_args()


def main() -> int:
    """Run the private snapshot-acquisition worker."""
    args = _parse_args()
    if not args.worker:
        raise SystemExit("this module is a private model-acquisition worker")
    return _worker(
        args.models,
        cache_dir=args.cache_dir,
        endpoint=args.endpoint,
    )


if __name__ == "__main__":
    raise SystemExit(main())
