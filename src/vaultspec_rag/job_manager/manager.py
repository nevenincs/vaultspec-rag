"""Canonical coordinator for durable job identity and service lifecycle."""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Never, cast

if TYPE_CHECKING:
    import asyncio
    import os

    from .. import job_persistence as _job_persistence
    from ..service_quiesce import ServiceQuiesceController
    from .state import AttemptExit

from ..config._settings import get_config, managed_status_dir
from ._control import JobManagerControl
from ._execution import JobManagerExecution
from ._persistence import JobManagerPersistence
from ._progress import JobManagerProgress
from ._records import JobManagerRecords
from .models import MAX_RECORDS, QuiescedDispatchClaim
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
        quiesce_controller: ServiceQuiesceController,
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
        self._quiesce_controller = quiesce_controller
        self._lock = threading.RLock()
        # Serializes every state-file write. Synchronous transition persists
        # write while holding both locks; deferred progress flushes serialize
        # their generation under the manager lock, keep only this lock across
        # the fsync, and skip when it is contended (single-flight), so no
        # older serialization can ever replace a newer one on disk.
        self._write_lock = threading.Lock()
        # Monotonic bookkeeping for deferred progress durability. The
        # generation counter advances on every progress-only mutation; the
        # flushed generation trails it until some write carries the mutation
        # to disk. Deliberately not part of the rollback backup: a spurious
        # pending signal costs one redundant flush, never correctness.
        self._state_generation = 0
        self._flushed_generation = 0
        self._last_flush_monotonic = float("-inf")
        self._active: dict[str, ManagedJob] = {}
        self._terminal: deque[ManagedJob] = deque()
        self._idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding] = (
            OrderedDict()
        )
        self._job_idempotency_keys: dict[str, set[str]] = {}
        self._dispatchers: dict[str, JobDispatchBinding] = {}
        self._next_dispatch_binding_nonce = 0
        self._next_quiesced_dispatch_generation = 0
        self._pending_quiesced_dispatches: dict[str, QuiescedDispatchClaim] = {}
        # The loop that owns managed execution for this service life, adopted
        # at startup. Admission preflights run on ordinary worker threads, so
        # the thread that decides to dispatch routinely has no loop of its
        # own; without this the handoff has nowhere to go. ``None`` in a
        # process that never adopted one (the local CLI), where a loopless
        # dispatch is a genuine caller error rather than a thread boundary.
        self._service_loop: asyncio.AbstractEventLoop | None = None
        self._retiring_tasks: set[asyncio.Task[AttemptExit]] = set()
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
        """Return whether the latest in-memory generation still needs flushing.

        True both after a failed write and while progress-only mutations are
        deferred inside the flush budget; an in-memory manager never needs
        flushing.
        """
        with self._lock:
            if self._state_path is None:
                return False
            return (
                self._persistence_dirty
                or self._flushed_generation != self._state_generation
            )
