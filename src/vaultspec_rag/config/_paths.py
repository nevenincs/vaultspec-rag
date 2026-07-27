"""Managed configuration persistence paths."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .._atomic_write import write_json_atomically
from ._types import STATUS_DIR_DEFAULT, EnvVar

logger = logging.getLogger(__name__)
# Name of the persisted local-only marker inside the managed service
# (``status_dir``) directory. ``install --local-only`` writes this so the
# resident service honours the local backend on a later ``server start``
# without the operator re-passing the flag. It lives under ``status_dir``
# (``~/.vaultspec-rag`` by default, overridable via
# ``VAULTSPEC_RAG_STATUS_DIR``) because that is the per-host, gitignored,
# test-isolatable home for runtime selections - never the project tree, so
# the pure-Python wheel and the repository stay untouched.
_LOCAL_ONLY_MARKER_FILENAME = "local-only.json"

#: Name of the service discovery file, in the managed status directory and
#: beside the machine lock. It is one fact with several readers - the client
#: resolves it, the daemon cleans it up, the machine pointer publishes it, and
#: the indexer treats it as SENSITIVE because it carries the service token.
#: Spelled once so a rename cannot quietly leave that last reader behind,
#: indexing a credential nobody remembered was in this file.
SERVICE_STATUS_FILENAME = "service.json"


def _status_dir_path() -> Path:
    """Resolve the managed service directory, honouring the env override.

    Read straight from the resolution chain (env override -> default) so
    the persisted local-only marker lands in the same directory the
    daemon and CLI already use for ``service.json`` and the log. Reading
    the env directly (rather than via the cached config) keeps the
    persistence layer free of the config singleton it feeds.
    """
    raw = os.environ.get(EnvVar.STATUS_DIR.value) or STATUS_DIR_DEFAULT
    return Path(raw).expanduser()


def _local_only_marker_path() -> Path:
    """Return the path of the persisted local-only marker file."""
    return _status_dir_path() / _LOCAL_ONLY_MARKER_FILENAME


def persist_local_only(value: bool) -> Path:
    """Persist the local-only backend selection to the managed service dir.

    ``install --local-only`` calls this so a later ``server start`` (in a
    fresh process, with no flag and no env) still selects the on-disk
    store. The marker is a small JSON document (``{"local_only": bool}``)
    written atomically through a ``.tmp`` sibling and ``os.replace`` so a
    concurrent reader never observes a half-written file. Writing
    ``False`` records an explicit server-mode selection, overwriting any
    prior local-only marker rather than deleting it, so the persisted
    choice is always unambiguous.

    Args:
        value: ``True`` to persist the local backend selection, ``False``
            to persist an explicit server-mode selection.

    Returns:
        The path the marker was written to.
    """
    path = _local_only_marker_path()
    write_json_atomically(path, {"local_only": bool(value)})
    logger.debug("persisted local_only=%s to %s", value, path)
    return path


def read_persisted_local_only() -> bool | None:
    """Read the persisted local-only selection, if any.

    Returns ``None`` when no marker has been written (the common case on a
    fresh host), so the resolver falls through to the module default. A
    malformed or unreadable marker is treated as absent and logged at
    debug rather than raised, because a corrupt runtime hint must never
    crash startup - the default backend remains the safe fallback.

    Returns:
        The persisted boolean, or ``None`` when no usable marker exists.
    """
    path = _local_only_marker_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.debug("local-only marker unreadable at %s: %s", path, exc)
        return None
    try:
        value = json.loads(raw).get("local_only")
    except (ValueError, AttributeError) as exc:
        logger.debug("local-only marker malformed at %s: %s", path, exc)
        return None
    return bool(value) if isinstance(value, bool) else None
