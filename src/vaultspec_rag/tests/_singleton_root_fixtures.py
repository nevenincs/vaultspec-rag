"""Session-root naming and reclaim for the pytest managed-singleton tree.

The pytest session owns a temporary root holding its isolated status dir,
Qdrant storage and per-participant basetemp. Naming that pair and reclaiming
it - this run's at teardown, a killed run's leftovers at startup - is the test
session's own housekeeping, so it lives beside the tests rather than in the
module that enforces containment. So does deciding whether uv's project
environment has to be moved into that root for the session's duration.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ._operator_directory_guard import canonical_path

if TYPE_CHECKING:
    from os import PathLike

#: The session root, and the marker saying one is already pinned above this
#: process. Both are set by the repository-root conftest and inherited by a
#: nested pytest session, which is the only thing that reads them: production
#: knows nothing about either. Declared here so the conftest, the package
#: conftest and the tests all spell them the same way.
PYTEST_SESSION_ACTIVE_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"
PYTEST_SESSION_ROOT_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"

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


def singleton_child_names(worker: str | None) -> tuple[str, str]:
    """Return the singleton and basetemp names for a session participant.

    The xdist controller and each worker place their own pair side by side in one
    session root. Session participants include their process id so nested pytest
    factories cannot clear a live parent's basetemp. Reclaiming addresses only
    the caller's own pair rather than the root wholesale.
    """
    suffix = f"-{worker}" if worker else ""
    return f"machine-singleton{suffix}", f"pytest-temp{suffix}"


def uv_project_environment_redirect(
    *,
    prefix: str | PathLike[str],
    rootdir: str | PathLike[str],
    configured: str | None,
    scratch: str | PathLike[str],
) -> Path | None:
    """Return where a session must point uv's project environment, if anywhere.

    The session's audit hook judges the uv launches this process makes and
    sees none of the launches its children make. A child that runs uv in the
    checkout creates or replaces the checkout's ``.venv`` unless that
    environment is usable to it, and the only one known to be is the one this
    session is running from. So a session running from any other interpreter
    names an environment under its own temporary tree, which every descendant
    inherits.

    Args:
        prefix: The environment the session's interpreter runs from.
        rootdir: The checkout the session is collecting.
        configured: What the environment already names as uv's project
            environment, if anything.
        scratch: The session's own temporary tree.

    Returns:
        The environment path to export, or ``None`` to leave the variable as
        it is: an operator who named one is taken at their word, and a session
        running from the checkout's own environment changes nothing.
    """
    if configured:
        return None
    if canonical_path(prefix) == canonical_path(Path(rootdir) / ".venv"):
        return None
    return Path(scratch) / "uv-project-environment"


def reclaim_singleton_paths(
    root: str | PathLike[str],
    *,
    owned_root: bool,
    owned_pair: bool,
    keep_diagnostics: bool,
    worker: str | None = None,
) -> None:
    """Reclaim what this process wrote under *root*, sparing failure evidence.

    Three things make a blanket ``rmtree(root)`` wrong.

    The machine-singleton tree - the isolated status dir and Qdrant storage - is
    the bulk of a run's footprint and holds no per-test diagnostics, so it always
    goes. Under an inherited root it is reclaimed here too: an xdist worker
    created the pair it writes even though it did not create the root, and
    nothing reclaimed those before.

    ``basetemp`` sits inside the same root, so removing the root wholesale also
    destroyed the ``tmp_path`` directories pytest deliberately retained under
    ``tmp_path_retention_policy = "failed"``. A failing run's evidence is the one
    thing cleanup must not take, so it survives when *keep_diagnostics*.

    Both removals are gated on *owned_pair*, and the root itself additionally on
    *owned_root*. A nested pytest subprocess inherits the root **and**
    ``PYTEST_XDIST_WORKER``, but configuration adds its process id to the pair
    names. Ownership still matters: a caller handed an existing pair must not
    reclaim it merely because it knows its name.
    """
    root_path = Path(root)
    if not owned_pair:
        return
    machine_singleton, basetemp = singleton_child_names(worker)
    shutil.rmtree(root_path / machine_singleton, ignore_errors=True)
    if keep_diagnostics:
        return
    shutil.rmtree(root_path / basetemp, ignore_errors=True)
    if owned_root:
        shutil.rmtree(root_path, ignore_errors=True)


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
        canonical_path(base_dir)
        if base_dir is not None
        else Path(tempfile.gettempdir())
    )
    keep_resolved = canonical_path(keep)
    reclaimed: list[Path] = []
    try:
        candidates = sorted(parent.glob(f"{_PYTEST_SINGLETON_ROOT_PREFIX}*"))
    except OSError:
        return reclaimed
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            if canonical_path(candidate) == keep_resolved:
                continue
            if _root_recently_touched(candidate, now=now):
                continue
        except OSError:
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            reclaimed.append(candidate)
    return reclaimed
