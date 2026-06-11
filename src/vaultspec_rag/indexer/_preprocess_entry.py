"""Out-of-process runner for ``entry_point`` preprocess rules (#185 follow-up).

Invoked as a subprocess::

    python -m vaultspec_rag.indexer._preprocess_entry "<mod>:<callable>" <path>

It imports the referenced callable, calls it with the source path, and prints the
returned object as one JSON document on stdout - the exact same contract a
``command`` preprocessor satisfies. Running ``entry_point`` rules in this
dedicated subprocess (rather than in-process inside the chunk worker) keeps the
CPU-only isolation and the ``timeout_s`` bound by construction, so an
``entry_point`` cannot initialise CUDA in the spawn worker or hang it - the
hazard that deferred ``entry_point`` in v1 (ADR D9). See the codification
candidate ``preprocessors-run-out-of-process``.

The callable contract: ``def my_callable(source_path: str) -> Mapping | BaseModel``
returning a mapping (or a pydantic model) shaped like ``PreprocOutput``. A
``pydantic.BaseModel`` is dumped via ``model_dump(mode="json")``; any other
mapping is emitted with ``json.dumps``. Import, resolution, call, or
serialisation failures exit non-zero with a stderr message, which the runner
turns into a per-file skip.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

__all__ = ["main", "resolve_entry_point"]


def resolve_entry_point(ref: str) -> Any:
    """Resolve a ``"module:callable"`` reference to the callable object.

    Args:
        ref: A ``"package.module:callable"`` string.

    Returns:
        The resolved attribute (expected to be callable).

    Raises:
        ValueError: If ``ref`` is not of the form ``module:callable``.
        ModuleNotFoundError: If the module cannot be imported.
        AttributeError: If the attribute is absent on the module.
    """
    module_name, sep, attr = ref.partition(":")
    if not sep or not module_name or not attr:
        msg = f"entry_point {ref!r} must be of the form 'module:callable'"
        raise ValueError(msg)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _to_jsonable(result: object) -> object:
    """Coerce a callable's return value into a JSON-serialisable object."""
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return result


def main(argv: list[str] | None = None) -> int:
    """Entry-point CLI: resolve, call, and emit JSON. Returns a process exit code."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: _preprocess_entry <module:callable> <source_path>\n")
        return 2
    ref, source_path = args
    try:
        func = resolve_entry_point(ref)
    except (ValueError, ImportError, AttributeError) as exc:
        sys.stderr.write(f"could not resolve entry_point {ref!r}: {exc}\n")
        return 3
    try:
        result = func(source_path)
    except Exception as exc:
        # Any extractor failure becomes a non-zero exit -> per-file skip.
        sys.stderr.write(f"entry_point {ref!r} raised: {exc}\n")
        return 4
    try:
        sys.stdout.write(json.dumps(_to_jsonable(result)))
    except (TypeError, ValueError) as exc:
        sys.stderr.write(f"entry_point {ref!r} returned non-JSON output: {exc}\n")
        return 5
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
