"""Progress reporting protocol and adapters for the index pipeline.

Defines a lightweight ``ProgressReporter`` Protocol owned by the indexer
layer plus two concrete implementations:

- ``NullProgressReporter`` — no-op used by non-interactive callers.
- ``RichProgressReporter`` — Rich adapter with TTY-aware line fallback.

The indexer modules depend only on the Protocol and never import Rich.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

if TYPE_CHECKING:
    from types import TracebackType

    from rich.console import Console
    from rich.progress import TaskID

__all__ = [
    "NullProgressReporter",
    "ProgressReporter",
    "RichProgressReporter",
]


@runtime_checkable
class ProgressReporter(Protocol):
    """Protocol consumed by the indexer to emit progress events.

    The indexer calls ``phase_start`` before each pipeline phase, then
    ``advance`` as work items complete, then ``phase_end`` once the
    phase concludes. ``log`` is used for ad-hoc informational lines.
    """

    def phase_start(self, name: str, total: int | None) -> None:
        """Begin a new phase with an optional known total."""

    def advance(self, n: int = 1) -> None:
        """Record ``n`` units of completed work in the active phase."""

    def phase_end(self) -> None:
        """End the currently active phase."""

    def log(self, message: str) -> None:
        """Emit an informational message outside of any phase bar."""


class NullProgressReporter:
    """No-op ``ProgressReporter`` implementation."""

    def phase_start(self, name: str, total: int | None) -> None:
        del name, total

    def advance(self, n: int = 1) -> None:
        del n

    def phase_end(self) -> None:
        return None

    def log(self, message: str) -> None:
        del message


class RichProgressReporter:
    """Rich-backed ``ProgressReporter`` with TTY-aware fallback.

    In TTY mode, drives a single ``rich.progress.Progress`` instance and
    swaps the active task row on every ``phase_start``. In non-TTY mode,
    falls back to plain line-based output so piped output stays readable
    and free of live-frame spam. The fallback counter is guarded by a
    ``threading.Lock`` so worker threads in the indexer's parse phase can
    advance it safely.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._is_tty = console.is_terminal
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None
        self._phase_name: str | None = None
        self._phase_total: int | None = None
        self._phase_count: int = 0
        self._lock = threading.Lock()
        self._started = False

    def __enter__(self) -> RichProgressReporter:
        if self._is_tty:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self._console,
            )
            self._progress.__enter__()
        self._started = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._is_tty and self._progress is not None:
            self._progress.__exit__(exc_type, exc, tb)
            self._progress = None
        self._started = False

    def phase_start(self, name: str, total: int | None) -> None:
        if self._is_tty:
            if self._progress is None:
                raise RuntimeError(
                    "RichProgressReporter must be used as a context manager",
                )
            self._task_id = self._progress.add_task(name, total=total)
            self._phase_name = name
            self._phase_total = total
            with self._lock:
                self._phase_count = 0
            return

        with self._lock:
            self._phase_name = name
            self._phase_total = total
            self._phase_count = 0
        count_str = str(total) if total is not None else "?"
        self._console.print(f"==> {name} ({count_str} items)")

    def advance(self, n: int = 1) -> None:
        if self._is_tty:
            if self._progress is not None and self._task_id is not None:
                self._progress.update(self._task_id, advance=n)
            return
        with self._lock:
            self._phase_count += n

    def phase_end(self) -> None:
        if self._is_tty:
            if self._progress is not None and self._task_id is not None:
                if self._phase_total is not None:
                    self._progress.update(
                        self._task_id,
                        completed=self._phase_total,
                    )
                else:
                    self._progress.update(self._task_id, total=1, completed=1)
            self._task_id = None
            self._phase_name = None
            self._phase_total = None
            return

        with self._lock:
            count = self._phase_count
            total = self._phase_total
        if total is not None and total != count:
            self._console.print(f"    done ({count}/{total})")
        else:
            self._console.print(f"    done ({count})")
        with self._lock:
            self._phase_name = None
            self._phase_total = None
            self._phase_count = 0

    def log(self, message: str) -> None:
        if self._is_tty and self._progress is not None:
            self._progress.console.log(message)
        else:
            self._console.print(message)
