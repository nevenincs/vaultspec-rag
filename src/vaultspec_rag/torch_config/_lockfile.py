"""The one derivation of the accelerated torch version from a lockfile.

The version this project pins for CUDA is a single fact with a single source:
the ``uv.lock`` entry resolved against the accelerated index. It is read here,
never written, so a lock bump cannot leave a copy of it behind somewhere else.

A published wheel ships neither ``uv.lock`` nor ``pyproject.toml``, so this
derivation is available to the build tooling and to tests running from a
checkout, and not to an installed runtime. That is why
:data:`TORCH_TOOL_PIN_VERSION` still exists as a last-resort fallback for an
environment holding no torch to read a version from - and why a test asserts
the two agree wherever the lockfile is reachable.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from ._constants import CU130_INDEX_URL

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["LockedTorchVersionError", "locked_torch_version"]


class LockedTorchVersionError(RuntimeError):
    """The accelerated torch version cannot be resolved from the lockfile."""


def locked_torch_version(root: Path, index_url: str = CU130_INDEX_URL) -> str:
    """Return the torch version *root*'s lockfile pins against *index_url*.

    Refuses anything but exactly one match: no entry means the accelerated
    index is not being resolved against at all, and several mean the pin is
    ambiguous, which a caller must not resolve by picking one.
    """
    lock_path = root / "uv.lock"
    try:
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LockedTorchVersionError(f"cannot read {lock_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LockedTorchVersionError(f"{lock_path} is not valid TOML: {exc}") from exc

    wanted = index_url.rstrip("/")
    versions = {
        str(package["version"])
        for package in lock.get("package", [])
        if package.get("name") == "torch"
        and str(package.get("source", {}).get("registry", "")).rstrip("/") == wanted
    }
    if len(versions) != 1:
        raise LockedTorchVersionError(
            f"expected exactly one torch version locked against {wanted}; "
            f"got {sorted(versions)!r}"
        )
    return versions.pop()
