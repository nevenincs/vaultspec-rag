"""Small cross-cutting helpers for the enrollment commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._models import ConfirmFn

logger = logging.getLogger(__name__)

__all__ = ["_exception_caused_by", "confirmation_outcome"]


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


def confirmation_outcome(confirm: ConfirmFn, prompt: str) -> str:
    """Run one interactive confirmation without exposing callback failures.

    The four ways an answer can fail to arrive need different words from the
    caller: a decline is the operator's choice, an end of input is a
    non-interactive run that has to be told about ``--yes``, an interrupt is
    an abandoned command, and a raising callback is a defect. Collapsing them
    into a boolean is how a script that never had a terminal came to read as
    a user who said no.
    """
    try:
        return "approved" if confirm(prompt) else "declined"
    except KeyboardInterrupt:
        return "interrupted"
    except EOFError:
        return "eof"
    except Exception as exc:
        if _exception_caused_by(exc, EOFError):
            return "eof"
        logger.warning("confirm() raised %s: %s", type(exc).__name__, exc)
        return f"error:{type(exc).__name__}"
