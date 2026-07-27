"""Canonical coordinator for durable job identity and service lifecycle."""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Never, cast

if TYPE_CHECKING:
    import asyncio
    import os

    from .. import job_persistence as _job_persistence
    from ..job_control import QuiesceGate

from ..config._settings import get_config, managed_status_dir
from ._control import JobManagerControl
from ._execution import JobManagerExecution
from ._persistence import JobManagerPersistence
from ._progress import JobManagerProgress
from ._records import JobManagerRecords
from .models import MAX_RECORDS
from .state import (
    CONFIGURED_STATE_PATH,
    MANAGED_STATE_FILENAME,
    ConfiguredStatePath,
    JobDispatchBinding,
    ManagedJob,
)


class JobManager(
    JobManagerExecution,
    JobManagerRecords,
    JobManagerProgress,
    JobManagerControl,
    JobManagerPersistence,
):
    """Own canonical job identity, runtime handles, transitions, and snapshots."""

    def __getattr__(self, name: str) -> Never:
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def __init__(
        self,
        *,
        max_nonterminal: int | None = None,
        max_terminal_history: int = MAX_RECORDS,
        state_path: (
            str | os.PathLike[str] | ConfiguredStatePath | None
        ) = CONFIGURED_STATE_PATH,
        quiesce_gate: QuiesceGate | None = None,
    ) -> None:
        resolved_max = (
            get_config().job_max_nonterminal
            if max_nonterminal is None
            else max_nonterminal
        )
        if isinstance(resolved_max, bool) or resolved_max < 1:
            raise ValueError("max_nonterminal must be at least 1")
        if isinstance(max_terminal_history, bool) or max_terminal_history < 1:
            raise ValueError("max_terminal_history must be at least 1")

        self._max_nonterminal = resolved_max
        self._max_terminal_history = max_terminal_history
        self._max_idempotency = resolved_max + max_terminal_history
        if state_path is CONFIGURED_STATE_PATH:
            self._state_path = managed_status_dir() / MANAGED_STATE_FILENAME
        else:
            resolved_path = cast("str | os.PathLike[str] | None", state_path)
            self._state_path = (
                Path(resolved_path) if resolved_path is not None else None
            )
        # One shared hold gate injected into every attempt's control token
        # so a single process-global pause quiesces all in-flight jobs.
        # ``None`` keeps tokens gateless (no hold behavior).
        self._quiesce_gate = quiesce_gate
        self._lock = threading.RLock()
        self._active: dict[str, ManagedJob] = {}
        self._terminal: deque[ManagedJob] = deque()
        self._idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding] = (
            OrderedDict()
        )
        self._job_idempotency_keys: dict[str, set[str]] = {}
        self._dispatchers: dict[str, JobDispatchBinding] = {}
        self._retiring_tasks: set[asyncio.Task[Any]] = set()
        self._persistence_dirty = False
        self._accepting_dispatch = True
        self._lifecycle_state: Literal["new", "running", "stopping", "stopped"] = "new"
        self._startup_restore_incomplete = False

    def prepare_startup(self) -> bool:
        """Open dispatch for one service life and report whether restore is needed.

        A cleanly stopped manager is reused in place so queued and paused jobs keep
        their exact identities. An unclean manager cannot be reopened while live
        ownership may still exist.

        Returns:
            ``True`` for a fresh manager that must restore its persisted state;
            ``False`` when reopening the clean in-memory generation.
        """
        with self._lock:
            if self._lifecycle_state == "new":
                self._lifecycle_state = "running"
                self._accepting_dispatch = True
                self._startup_restore_incomplete = True
                return True
            if self._lifecycle_state == "stopped":
                self._lifecycle_state = "running"
                self._accepting_dispatch = True
                self._startup_restore_incomplete = False
                return False
            if self._lifecycle_state == "stopping":
                raise RuntimeError(
                    "JobManager cannot restart after an unclean shutdown while "
                    "runtime ownership may still be live."
                )
            raise RuntimeError("JobManager service lifecycle is already running.")

    def complete_startup(self) -> None:
        """Mark the fresh manager generation restored before dispatch begins."""
        with self._lock:
            if self._lifecycle_state != "running":
                raise RuntimeError("JobManager startup is not active.")
            self._startup_restore_incomplete = False

    def abort_startup(self) -> bool:
        """Return an untouched manager to ``new``, or report retained state."""
        with self._lock:
            if not self._startup_restore_incomplete:
                raise RuntimeError("JobManager startup restore is not pending.")
            if self._active or self._terminal or self._live_runtime_ids_locked():
                return False
            self._lifecycle_state = "new"
            self._accepting_dispatch = True
            self._startup_restore_incomplete = False
            return True

    def complete_shutdown(self, *, resources_released: bool) -> None:
        """Close the service life only after every reachable owner is released."""
        with self._lock:
            if not resources_released:
                self._lifecycle_state = "stopping"
                return
            survivors = self._live_runtime_ids_locked()
            if survivors:
                raise RuntimeError(
                    "JobManager cannot complete clean shutdown with live runtimes: "
                    + ", ".join(survivors)
                )
            self._lifecycle_state = (
                "new" if self._startup_restore_incomplete else "stopped"
            )
            self._startup_restore_incomplete = False

    @property
    def max_nonterminal(self) -> int:
        """Configured admission bound for exact-addressable active work."""
        return self._max_nonterminal

    @property
    def max_terminal_history(self) -> int:
        """Retention bound for completed job resources."""
        return self._max_terminal_history

    @property
    def state_path(self) -> Path | None:
        """Atomic state-file path, or ``None`` for an in-memory manager."""
        return self._state_path

    @property
    def persistence_dirty(self) -> bool:
        """Return whether the latest in-memory generation still needs flushing."""
        with self._lock:
            return self._persistence_dirty
