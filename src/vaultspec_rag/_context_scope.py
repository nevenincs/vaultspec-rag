"""Exception-safe, nestable bindings for execution-local state."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from contextvars import ContextVar


@contextmanager
def bind_context[T](variable: ContextVar[T], value: T) -> Generator[None]:
    """Restore the previous binding even when the scoped operation fails."""
    token = variable.set(value)
    try:
        yield
    finally:
        variable.reset(token)
