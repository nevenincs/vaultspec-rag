"""Removing a directory tree without following a link out of it.

``shutil.rmtree`` refuses to recurse into a symlink, but on the failure it
raises rather than clearing the link, so a tree containing one cannot be
removed at all. The handler here unlinks the link itself and lets the walk
continue, and re-raises anything else untouched.

This is defence in depth, not the primary check: every caller establishes that
the top of the tree is a real directory first. It covers the link that appears
further down, which on Windows includes a junction - a reparse point that a
naive recursive delete would follow into the target's contents.

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
import stat
from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["remove_tree"]

logger = logging.getLogger(__name__)


def _unlink_link_or_reraise(
    _func: object,
    path: str | bytes,
    exc: BaseException,
    *,
    dir_fd: int | None = None,
) -> None:
    """``shutil.rmtree`` error handler in the ``onexc`` form 3.12 introduced.

    ``onexc`` receives the exception instance; the older ``onerror`` received
    an ``exc_info`` triple. A walk rooted at a directory descriptor reports
    its failures relative to that descriptor, so the same *dir_fd* is needed
    here to look at the node the walk actually failed on.
    """
    try:
        is_link = stat.S_ISLNK(
            os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode
        )
    except OSError:
        is_link = False
    if is_link:
        try:
            os.unlink(path, dir_fd=dir_fd)
        except OSError as unlink_error:
            logger.warning(
                "Failed to unlink symlink %s: %s", os.fsdecode(path), unlink_error
            )
        return
    raise exc


def remove_tree(path: Path | str, *, dir_fd: int | None = None) -> None:
    """Delete *path* and everything beneath it, unlinking links rather than
    descending through them.

    With *dir_fd*, *path* is resolved against that open directory instead of
    the working directory, so the tree removed is the one beneath the
    directory the caller holds whatever has since been done to its name.
    """
    shutil.rmtree(
        path, onexc=partial(_unlink_link_or_reraise, dir_fd=dir_fd), dir_fd=dir_fd
    )
