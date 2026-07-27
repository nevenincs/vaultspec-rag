"""Fail-closed containment for machine-singleton effects during pytest runs.

The resident service lock, discovery records, and managed Qdrant identity are
machine-scoped state.  A test that redirects either configured directory must
not be able to mutate state or signal a process outside pytest's own temporary
tree. Production execution stays untouched: the session fixture explicitly
activates the guard, and child processes adopt that inherited activation. Once
active, the canonical root is process-local authority; mutable environment
values can neither disable the guard nor move its boundary.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from os import PathLike

__all__ = [
    "PYTEST_MANAGED_SINGLETON_ACTIVE_ENV",
    "PYTEST_MANAGED_SINGLETON_BOOTSTRAP_ENV",
    "PYTEST_MANAGED_SINGLETON_ROOT_ENV",
    "ManagedSingletonIsolationError",
    "anchor_spawned_process_to_pytest",
    "enforce_pytest_managed_singleton_containment",
    "enforce_pytest_singleton_containment",
    "pytest_singleton_containment_active",
    "register_pytest_singleton_root",
    "sweep_orphaned_singleton_roots",
]

# This is deliberately separate from the two operator-facing path overrides.
# The session fixture owns it, and child processes inherit it, so changing a
# configured singleton path cannot redefine the boundary it must remain under.
PYTEST_MANAGED_SINGLETON_ROOT_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"
PYTEST_MANAGED_SINGLETON_ACTIVE_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"
PYTEST_MANAGED_SINGLETON_BOOTSTRAP_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"
_PYTEST_MANAGED_SINGLETON_ACTIVE_VALUE = "1"

# Environment carries the session root across an exec boundary, but it is not
# authority inside a process: the first successful registration pins one
# canonical root for that process's lifetime. A lock keeps simultaneous first
# use from two daemon threads from racing two candidate roots into the slot.
_registration_lock = threading.Lock()
_registered_root: Path | None = None


class ManagedSingletonIsolationError(RuntimeError):
    """A pytest singleton effect was not contained by its session temp root."""


def _without_windows_extended_prefix(raw: str) -> str:
    """Return the ordinary spelling of a Windows extended-length path."""
    if os.name != "nt":
        return raw
    normalized = raw.replace("/", "\\")
    folded = normalized.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        return f"\\\\{normalized[8:]}"
    if folded.startswith("\\\\?\\"):
        return normalized[4:]
    if folded.startswith("\\??\\"):
        return normalized[4:]
    if folded.startswith("\\\\.\\"):
        raise ManagedSingletonIsolationError(
            f"Windows device paths cannot identify a pytest containment target: {raw!r}"
        )
    return raw


def _canonical_path(path: str | PathLike[str]) -> Path:
    """Resolve aliases, links, junctions, ``..``, and path casing."""
    raw = os.fspath(path)
    if not raw:
        raise ManagedSingletonIsolationError(
            "an empty path cannot identify a pytest containment target"
        )
    try:
        candidate = Path(_without_windows_extended_prefix(raw)).expanduser()
        resolved = candidate.resolve(strict=False)
        normalized = os.path.normcase(
            os.path.normpath(_without_windows_extended_prefix(str(resolved)))
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ManagedSingletonIsolationError(
            f"could not canonicalize pytest containment path {raw!r}: {exc}"
        ) from exc
    return Path(normalized)


def _publish_registered_root(root: Path) -> None:
    """Keep the child-process transport aligned with process-local authority."""
    os.environ[PYTEST_MANAGED_SINGLETON_ROOT_ENV] = str(root)
    os.environ[PYTEST_MANAGED_SINGLETON_ACTIVE_ENV] = (
        _PYTEST_MANAGED_SINGLETON_ACTIVE_VALUE
    )


def pytest_singleton_containment_active() -> bool:
    """Return whether this process is identifiable as pytest-owned.

    The repository-root conftest publishes the bootstrap sentinel before
    pytest imports project test modules, then replaces that bootstrap-only
    state with a registered root during ``pytest_configure``.  Exec children
    inherit the active/root pair.  A registered process remains identified
    even if a test tampers with every transport environment variable.
    """
    return (
        _registered_root is not None
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get(PYTEST_MANAGED_SINGLETON_ACTIVE_ENV)
        == _PYTEST_MANAGED_SINGLETON_ACTIVE_VALUE
        or os.environ.get(PYTEST_MANAGED_SINGLETON_BOOTSTRAP_ENV)
        == _PYTEST_MANAGED_SINGLETON_ACTIVE_VALUE
    )


def register_pytest_singleton_root(root: str | PathLike[str]) -> Path:
    """Pin pytest's canonical singleton-containment root in this process.

    Registration is intentionally one-way. Re-registering the same canonical
    directory is idempotent, while a different directory is rejected so a test
    cannot re-anchor containment by changing an environment variable. The
    registered value is also republished for children created after same-test
    environment tampering.
    """
    canonical_root = _canonical_path(root)
    if not canonical_root.is_dir():
        raise ManagedSingletonIsolationError(
            "managed-singleton session root does not exist or is not a "
            f"directory: {canonical_root}"
        )

    global _registered_root
    with _registration_lock:
        if _registered_root is None:
            _registered_root = canonical_root
        elif _registered_root != canonical_root:
            raise ManagedSingletonIsolationError(
                "refusing to re-anchor pytest managed-singleton containment "
                f"from {_registered_root} to {canonical_root}"
            )
        pinned_root = _registered_root
        _publish_registered_root(pinned_root)
        return pinned_root


_PYTEST_SINGLETON_ROOT_PREFIX = "vaultspec-rag-pytest-"
# A concurrently live pytest run writes into its session root throughout the
# run, so a root untouched for this long cannot be a live session and is a
# leftover from a run killed before its cleanup ran. Generous, so a parallel
# run is never reclaimed out from under it.
_ORPHAN_SWEEP_LIVENESS_WINDOW_SECONDS = 3600.0


def _root_recently_touched(root: Path, *, now: float) -> bool:
    """Return whether *root* or a direct child was modified within the window.

    A stat failure is treated as recently touched so an unreadable or
    disappearing root is never reclaimed on a guess.
    """
    try:
        newest = root.stat().st_mtime
        for child in root.iterdir():
            newest = max(newest, child.stat().st_mtime)
    except OSError:
        return True
    return (now - newest) < _ORPHAN_SWEEP_LIVENESS_WINDOW_SECONDS


def sweep_orphaned_singleton_roots(
    *,
    keep: str | PathLike[str],
    now: float,
    base_dir: str | PathLike[str] | None = None,
) -> list[Path]:
    """Reclaim leftover pytest singleton roots from prior killed sessions.

    A pytest run killed externally (a sandbox timeout, ``taskkill``) never
    reaches ``pytest_unconfigure`` or its atexit backstop, so its session root -
    the isolated machine-singleton status and Qdrant storage dirs, on the order
    of 100 MB - leaks. On the next run's startup, reclaim every
    ``vaultspec-rag-pytest-*`` root that is neither *keep* (the current run's
    own root) nor touched within the liveness window, which cannot be a
    concurrently live run. *now* is supplied by the caller and *base_dir*
    defaults to the system temp dir, so the sweep is deterministic and testable.
    Returns the roots actually reclaimed.
    """
    parent = (
        _canonical_path(base_dir)
        if base_dir is not None
        else Path(tempfile.gettempdir())
    )
    keep_resolved = _canonical_path(keep)
    reclaimed: list[Path] = []
    try:
        candidates = sorted(parent.glob(f"{_PYTEST_SINGLETON_ROOT_PREFIX}*"))
    except OSError:
        return reclaimed
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            if _canonical_path(candidate) == keep_resolved:
                continue
            if _root_recently_touched(candidate, now=now):
                continue
        except OSError:
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            reclaimed.append(candidate)
    return reclaimed


#: The kill-on-close job every pytest-spawned daemon joins. Created on first
#: use and then held for the run: the handle IS the guarantee, so it is
#: deliberately never closed by this module. Process exit closes it, which is
#: exactly the event that must take the daemons down.
_pytest_process_job: int | None = None
_pytest_job_lock = threading.Lock()

#: ``PROCESS_SET_QUOTA | PROCESS_TERMINATE`` - the access
#: ``AssignProcessToJobObject`` requires on the target.
_PROCESS_SET_QUOTA_AND_TERMINATE = 0x0100 | 0x0001


def anchor_spawned_process_to_pytest(pid: int) -> bool:
    """Bind a pytest-spawned daemon's lifetime to this pytest process.

    ``sweep_orphaned_singleton_roots`` already exists because a pytest run
    killed externally never reaches its teardown, stranding the session root.
    The daemons that run cost more than the directory does - they hold ports,
    a machine lock, and the GPU - and every mechanism that could stop them
    lives inside the run that just died: the fixture teardown, the atexit
    backstop, any watchdog thread. So a hard-killed pytest strands a daemon
    with nothing left to reap it, and the daemon is built to survive exactly
    that (``_spawn_service`` breaks away from the launching Job Object on
    Windows and calls ``start_new_session`` on POSIX, both deliberately, so it
    outlives the operator's shell).

    A kill-on-close Job Object is the one guarantee that does not live inside
    the dying process: the kernel destroys every member when the last handle
    closes, and a handle closes however the owner dies. Membership is
    established here rather than at spawn time because the daemon must break
    away from whatever job it was born into first.

    Returns whether the anchor was established. ``False`` is not a failure to
    propagate - off-Windows, outside pytest, or when the OS refuses, the
    fixture teardown remains the guarantee it has always been - so callers
    spawn regardless.
    """
    if not pytest_singleton_containment_active():
        return False
    if os.name != "nt":
        # POSIX has no equivalent the owner can enforce from outside the
        # target; ``prctl(PDEATHSIG)`` is the child's own call and does not
        # survive the ``start_new_session`` this daemon needs. Fixture
        # teardown stays the guarantee there, so say so rather than imply a
        # containment that is not in force.
        return False
    from ._process_probe import close_process_handle, open_process_handle
    from ._win32 import assign_process_to_job, create_kill_on_close_job

    global _pytest_process_job
    with _pytest_job_lock:
        if _pytest_process_job is None:
            _pytest_process_job = create_kill_on_close_job(purpose="pytest-spawned")
        job = _pytest_process_job
    if job is None:
        return False

    handle = open_process_handle(pid, _PROCESS_SET_QUOTA_AND_TERMINATE)
    if handle is None:
        return False
    try:
        return assign_process_to_job(job, handle, pid, purpose="pytest-spawned")
    finally:
        close_process_handle(handle)


def _adopt_inherited_pytest_singleton_root() -> None:
    """Pin a fixture-exported root immediately on import in an exec'd child."""
    if (
        os.environ.get(PYTEST_MANAGED_SINGLETON_ACTIVE_ENV)
        != _PYTEST_MANAGED_SINGLETON_ACTIVE_VALUE
    ):
        return
    raw_root = os.environ.get(PYTEST_MANAGED_SINGLETON_ROOT_ENV)
    if not raw_root:
        raise ManagedSingletonIsolationError(
            "pytest managed-singleton containment is active but its inherited "
            "session root is missing"
        )
    register_pytest_singleton_root(raw_root)


def enforce_pytest_singleton_containment(
    target: str | PathLike[str],
    *,
    operation: str,
) -> None:
    """Require *target* to resolve beneath pytest's inherited session root.

    The function is intentionally inert for ordinary operator and daemon
    execution.  Under pytest it fails before the caller writes, deletes,
    acquires a singleton lock, or signals a managed process when the anchor is
    absent, invalid, or does not contain the canonical target.
    """
    root = _registered_root
    if root is None:
        if not pytest_singleton_containment_active():
            return
        raw_root = os.environ.get(PYTEST_MANAGED_SINGLETON_ROOT_ENV)
        if not raw_root:
            raise ManagedSingletonIsolationError(
                f"refusing to {operation} during pytest: the inherited managed-"
                "singleton session root is missing"
            )
        root = register_pytest_singleton_root(raw_root)
    else:
        # Environment is only child transport. Repair it here so a guarded
        # process spawn inherits the already-pinned root after env tampering.
        _publish_registered_root(root)

    if not root.is_dir():
        raise ManagedSingletonIsolationError(
            f"refusing to {operation} during pytest: managed-singleton session "
            f"root does not exist or is not a directory: {root}"
        )

    canonical_target = _canonical_path(target)
    if canonical_target != root and root not in canonical_target.parents:
        raise ManagedSingletonIsolationError(
            f"refusing to {operation} during pytest: target {canonical_target} "
            f"escapes managed-singleton session root {root}"
        )


def enforce_pytest_managed_singleton_containment(
    *,
    operation: str,
    targets: Iterable[str | PathLike[str]] = (),
) -> None:
    """Contain one managed-singleton operation and all configured anchors.

    A process-control operation may not have a filesystem target of its own,
    while a writer can be passed an explicit path that differs from the current
    configuration.  Under pytest, validate both configured singleton anchors
    and every effect-specific target before the caller performs its first
    mutation, lock acquisition, spawn, or signal.  Ordinary production calls
    return before importing or resolving configuration.
    """
    if not pytest_singleton_containment_active():
        return

    from .config._settings import get_config

    cfg = get_config()
    configured_targets: tuple[str | PathLike[str], ...] = (
        str(cfg.status_dir),
        str(cfg.qdrant_storage_dir),
    )
    for target in (*configured_targets, *targets):
        enforce_pytest_singleton_containment(target, operation=operation)


_adopt_inherited_pytest_singleton_root()
