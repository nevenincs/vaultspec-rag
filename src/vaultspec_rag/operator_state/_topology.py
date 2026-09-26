"""Which kind of environment an interpreter belongs to.

The kind decides which repair an operator can actually run: a persistent uv
tool environment is only durably fixed through its receipt, a uvx ephemeral
cache environment is not the installation the operator thinks they are running
at all, and a project virtual environment is served by the project surfaces.

Classification is pure path and file logic, so it is safe on the service
control paths, which never import torch and never shell out to ``uv``.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

__all__ = [
    "TOOL_RECEIPT_NAME",
    "RuntimeEnvKind",
    "classify_environment",
    "environment_root",
]

#: uv writes this file at the root of every persistent tool environment and
#: reads it back on upgrade. Its presence is what makes an environment a tool
#: environment; the directory it happens to sit in is a layout uv is free to
#: change, and has changed - a tool tree nested one level deeper than expected
#: is invisible to a parent-directory-name test.
TOOL_RECEIPT_NAME = "uv-receipt.toml"


class RuntimeEnvKind(StrEnum):
    """Classification of the environment a python prefix belongs to.

    Drives which torch remediation is offered: a ``uv tool`` env can only be
    repaired durably through its receipt (the project-scoped CUDA pin never
    reaches it), a uvx ephemeral cache env is almost never the environment the
    operator thinks they are running, and a project venv is served by
    ``vaultspec-rag install``.
    """

    UV_TOOL = "uv-tool"
    UVX_EPHEMERAL = "uvx-ephemeral"
    PROJECT_VENV = "project-venv"
    OTHER = "other"

    @property
    def label(self) -> str:
        """Human-readable form used beside interpreter paths in messages."""
        return {
            RuntimeEnvKind.UV_TOOL: "uv tool install",
            RuntimeEnvKind.UVX_EPHEMERAL: (
                "uvx ephemeral cache env - NOT the installed tool"
            ),
            RuntimeEnvKind.PROJECT_VENV: "project venv",
            RuntimeEnvKind.OTHER: "unrecognized env",
        }[self]


def environment_root(interpreter: str | Path) -> Path:
    """The environment an interpreter BELONGS to, not the one it resolves to.

    Normalised but never resolved. An environment's interpreter is a real file
    inside the tree on Windows and a symlink to the base interpreter on POSIX,
    so resolving it walks out of the environment entirely and lands in the
    shared Python installation. Every consumer is then wrong in the same
    direction: the refusal names a directory the operator is not in, the holder
    scan reports processes belonging to unrelated software using that base
    interpreter and misses the ones actually holding this environment, and the
    receipt is looked for where no receipt exists.
    """
    binary = Path(os.path.abspath(interpreter))
    if binary.parent.name.lower() in {"scripts", "bin"}:
        return binary.parent.parent
    return binary.parent


def _named_under(candidate: Path, directory: str) -> bool:
    """Whether *candidate* sits inside *directory*, both taken as written."""
    if not directory:
        return False
    try:
        return candidate.is_relative_to(Path(os.path.abspath(directory)))
    except (OSError, ValueError):
        return False


def classify_environment(root: str | Path) -> RuntimeEnvKind:
    """Classify the environment rooted at *root*.

    The uvx ephemeral cache is positively identified by the ``archive-v0``
    component of the uv cache layout, or by sitting under ``UV_CACHE_DIR``, and
    is asked first because such an environment also carries no receipt. A
    persistent tool environment is identified by its receipt, with a
    ``UV_TOOL_DIR`` ancestor as the fallback for a tree whose receipt cannot be
    read. Misclassification degrades only which remediation is offered, never
    correctness.
    """
    resolved = Path(os.path.abspath(root))
    parts = {part.lower() for part in resolved.parts}
    if "archive-v0" in parts or _named_under(
        resolved, os.environ.get("UV_CACHE_DIR", "")
    ):
        return RuntimeEnvKind.UVX_EPHEMERAL
    if (resolved / TOOL_RECEIPT_NAME).is_file():
        return RuntimeEnvKind.UV_TOOL
    if _named_under(resolved, os.environ.get("UV_TOOL_DIR", "")):
        return RuntimeEnvKind.UV_TOOL
    if resolved.name.lower() in {".venv", "venv"}:
        return RuntimeEnvKind.PROJECT_VENV
    return RuntimeEnvKind.OTHER
