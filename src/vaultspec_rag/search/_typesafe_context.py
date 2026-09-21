"""Request-local hosted classification shared by compound search calls."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._typesafe_policy import prepare_query

if TYPE_CHECKING:
    from collections.abc import Generator

    from ._typesafe_policy import ClassificationSession


@dataclass(slots=True)
class ClassificationScope:
    """One query evaluation and failure state for a whole search request."""

    session: ClassificationSession | None
    query_attempt_ms: float = 0.0


_active: ContextVar[ClassificationScope | None] = ContextVar(
    "search_classification", default=None
)


@contextmanager
def classification_scope(
    query: str, surface: str, filters: dict[str, object]
) -> Generator[ClassificationScope]:
    """Reuse a compound request's evaluation without sharing state across callers."""
    existing = _active.get()
    if existing is not None:
        yield existing
        return
    started = time.monotonic()
    scope = ClassificationScope(prepare_query(query, surface, filters))
    scope.query_attempt_ms = (time.monotonic() - started) * 1000
    token = _active.set(scope)
    try:
        yield scope
    finally:
        _active.reset(token)
