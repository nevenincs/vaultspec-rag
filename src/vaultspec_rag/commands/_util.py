"""Small cross-cutting helpers for the enrollment commands."""

from __future__ import annotations

__all__ = ["_exception_caused_by"]


def _exception_caused_by(exc: BaseException, target_type: type) -> bool:
    """Return True if any exception in ``exc``'s ``__cause__`` /
    ``__context__`` chain (or ``exc`` itself) is a ``target_type``.

    Rich's ``Confirm.ask`` on some non-TTY platforms wraps an
    ``EOFError`` from stdin in a ``click.Abort``; the chain still
    points back to the original cause. Without walking the chain,
    we'd misclassify those as user-intent declines.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, target_type):
            return True
        cur = cur.__cause__ or cur.__context__
    return False
