"""Path-containment safety for destructive storage operations.

The storage lifecycle surface deletes user data: a local store tree, or a
server-mode namespace's collections. A single out-of-scope deletion is
unacceptable, so every filesystem path a destructive verb is about to
remove must be proven to lie inside an explicitly permitted base
directory before the removal runs.

This module is that proof. ``resolve_within`` fully resolves both the
target and the base (normalising ``..`` and following symlinks) and
confirms the resolved target is the base itself or a descendant of it,
raising :class:`StorageSafetyError` otherwise. Resolving before comparing
is what closes the two escape classes a naive string-prefix check misses:
parent traversal (``base/../../etc``) and symlink escape (a link inside
the base that points outside it both resolve out of the base and are
rejected).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["StorageSafetyError", "is_within", "resolve_within"]


class StorageSafetyError(RuntimeError):
    """Raised when a target path escapes its permitted base directory."""


def resolve_within(target: Path | str, base: Path | str) -> Path:
    """Resolve ``target`` and verify it is contained within ``base``.

    Both paths are resolved (``..`` normalised, symlinks followed) before
    comparison, so parent-traversal and symlink escapes are rejected, not
    just literal-prefix mismatches. The base itself is permitted as well as
    any descendant.

    Args:
        target: The path a destructive verb intends to act on.
        base: The permitted root the target must stay within.

    Returns:
        The resolved, validated target path.

    Raises:
        StorageSafetyError: If the resolved target is neither the resolved
            base nor a descendant of it.
    """
    base_resolved = Path(base).resolve()
    target_resolved = Path(target).resolve()
    if (
        target_resolved != base_resolved
        and base_resolved not in target_resolved.parents
    ):
        raise StorageSafetyError(
            f"refusing to operate on {target_resolved}: outside the permitted "
            f"base {base_resolved}"
        )
    return target_resolved


def is_within(target: Path | str, base: Path | str) -> bool:
    """Return whether ``target`` resolves inside ``base`` (or equals it).

    The non-raising companion to :func:`resolve_within`, for survey/preview
    paths that need to classify rather than enforce.

    Args:
        target: The path to test.
        base: The permitted root.

    Returns:
        ``True`` if the resolved target is the resolved base or a descendant.
    """
    try:
        resolve_within(target, base)
    except StorageSafetyError:
        return False
    return True
