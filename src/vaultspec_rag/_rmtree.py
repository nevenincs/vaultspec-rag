"""Removing a directory tree without following a link out of it.

``shutil.rmtree`` refuses to recurse into a symlink, but on the failure it
raises rather than clearing the link, so a tree containing one cannot be
removed at all. The handler here unlinks the link itself and lets the walk
continue, and re-raises anything else untouched.

This is defence in depth, not the primary check: both callers test the top of
the tree with ``is_symlink`` first. It covers the link that appears further
down, which on Windows includes a junction - a reparse point that a naive
recursive delete would follow into the target's contents.

Two modules had grown this handler independently, byte-for-byte the same apart
from the name each gave the caught exception. That rename is the whole reason
the structural duplicate scan could not see them: it blinds identifiers and
constants, but an ``except ... as`` alias is stored as a bare string on the
handler node, so two identical bodies hashed differently.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

__all__ = ["remove_tree"]

logger = logging.getLogger(__name__)


def _unlink_link_or_reraise(
    _func: object,
    path: str | bytes,
    exc: BaseException,
) -> None:
    """``shutil.rmtree`` error handler in the ``onexc`` form 3.12 introduced.

    ``onexc`` receives the exception instance; the older ``onerror`` received
    an ``exc_info`` triple.
    """
    target = Path(os.fsdecode(path))
    if target.is_symlink():
        try:
            target.unlink()
        except OSError as unlink_error:
            logger.warning("Failed to unlink symlink %s: %s", target, unlink_error)
        return
    raise exc


def remove_tree(path: Path) -> None:
    """Delete *path* and everything beneath it, unlinking links rather than
    descending through them."""
    shutil.rmtree(path, onexc=_unlink_link_or_reraise)
