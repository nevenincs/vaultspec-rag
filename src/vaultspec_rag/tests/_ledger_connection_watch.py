"""Watch the connections production opens on a run ledger, without replacing any.

SQLite reports instruction counts, statement text, row changes and authorisation
checks only to callbacks registered on a connection, and a ledger opens its own
connection inside the call under test. The interpreter announces every new
connection through an audit event that carries the connection itself, so a test
can attach its callbacks to the very connection production is about to use. The
production functions, their names and their bindings are never touched.

The audit hook cannot be removed once added, so it is installed once and stays
inert unless a watch is active.
"""

from __future__ import annotations

import functools
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_watchers: list[Callable[[sqlite3.Connection, object], None]] = []
_announced = threading.local()


def _on_audit_event(event: str, args: tuple[object, ...]) -> None:
    """Note a connection the moment it exists, and attach after it is usable.

    The announcement arrives before the connection is initialised, when no
    callback can be registered on it yet. The next profile event on this
    thread is the first moment production runs any code after ``connect``
    returns, so the watchers are attached there, ahead of its first statement.
    """
    if event == "sqlite3.connect":
        _announced.database = args[0]
    elif event == "sqlite3.connect/handle" and _watchers:
        _announced.connection = args[0]
        _announced.previous = sys.getprofile()
        sys.setprofile(_attach_pending)


def _attach_pending(_frame: object, _event: str, _arg: object) -> None:
    sys.setprofile(_announced.previous)
    connection = _announced.connection
    database = getattr(_announced, "database", None)
    _announced.connection = None
    _announced.database = None
    if isinstance(connection, sqlite3.Connection):
        for watcher in tuple(_watchers):
            watcher(connection, database)


@functools.cache
def _install_hook() -> None:
    sys.addaudithook(_on_audit_event)


@contextmanager
def watch_ledger_connections(
    path: Path,
    on_connection: Callable[[sqlite3.Connection, bool], None],
) -> Generator[None]:
    """Call *on_connection* with each connection opened on the ledger at *path*.

    The callback runs on the opening thread, before production issues its first
    statement, and receives whether the connection is the read-only one a
    ledger opens to inspect an existing file's schema. Connections to any other
    database are ignored.
    """
    _install_hook()
    target = Path(path)
    read_only = f"{target.resolve().as_uri()}?mode=ro"

    def watcher(connection: sqlite3.Connection, database: object) -> None:
        if not isinstance(database, str | Path):
            return
        named = os.fspath(database)
        if named == read_only:
            on_connection(connection, True)
        elif Path(named) == target:
            on_connection(connection, False)

    _watchers.append(watcher)
    try:
        yield
    finally:
        _watchers.remove(watcher)


@dataclass(slots=True)
class LedgerCost:
    """What the production statements on a ledger actually made SQLite do."""

    connections: int = 0
    vm_steps: int = 0
    """Virtual-machine instructions retired. Grows with rows examined."""

    changed_rows: int = 0
    statements: list[str] = field(default_factory=list)
    """Every statement production issued, as SQLite expanded it."""

    @property
    def selects(self) -> list[str]:
        """The SELECT statements, whitespace-normalised."""
        return [
            " ".join(statement.split())
            for statement in self.statements
            if statement.lstrip().upper().startswith("SELECT")
        ]


class _Meter:
    """Counts one connection's work, from its first statement that is not setup.

    A ledger opens by selecting its journal mode and enabling foreign keys. That
    cost is the same for every call and says nothing about the call under test,
    so statements and instructions are counted from the first one after it.
    """

    def __init__(self, connection: sqlite3.Connection, cost: LedgerCost) -> None:
        self._connection = connection
        self._cost = cost
        self._opened = False
        self._counting = False
        self._seen_changes = 0

    def on_statement(self, statement: str) -> None:
        self._take_changes()
        if not self._opened and statement.lstrip().upper().startswith("PRAGMA"):
            return
        self._opened = True
        self._counting = True
        self._cost.statements.append(statement)

    def on_instruction(self) -> None:
        if self._counting:
            self._cost.vm_steps += 1

    def _take_changes(self) -> None:
        total = self._connection.total_changes
        self._cost.changed_rows += total - self._seen_changes
        self._seen_changes = total


@contextmanager
def measure_ledger_connections(path: Path) -> Generator[LedgerCost]:
    """Measure every statement production runs on the ledger at *path*."""
    cost = LedgerCost()

    def attach(connection: sqlite3.Connection, read_only: bool) -> None:
        if read_only:
            return
        cost.connections += 1
        meter = _Meter(connection, cost)
        connection.set_trace_callback(meter.on_statement)
        connection.set_progress_handler(meter.on_instruction, 1)

    with watch_ledger_connections(path, attach):
        yield cost
