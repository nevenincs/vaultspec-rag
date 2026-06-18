"""Import-light service discovery: read ``service.json`` and resolve the port.

These read-only helpers let any client (CLI or MCP) locate the running daemon
without loading Torch, the models, or the store. The status directory honors
``VAULTSPEC_RAG_STATUS_DIR`` through ``config.get_config`` (a lightweight
import). The status *writer* helpers (token/metadata update, status write,
lifecycle log) deliberately stay in ``cli._service_status``; only the
read/discovery surface lives here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

__all__ = [
    "_default_service_port",
    "_read_service_status",
    "_status_dir",
    "_status_file",
]


def _status_dir() -> Path:
    """Return the global service status directory, creating it if needed.

    Resolved via ``cfg.status_dir`` (which checks CLI override, then
    ``VAULTSPEC_RAG_STATUS_DIR`` env var, then default ``~/.vaultspec-rag/``).

    Returns:
        Path to the service status directory.
    """
    from ..config import get_config

    cfg = get_config()
    d = Path(cfg.status_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_file() -> Path:
    """Return the path to the service status JSON file.

    Returns:
        Path to ``{status_dir}/service.json``.
    """
    return _status_dir() / "service.json"


def _read_service_status() -> dict[str, Any] | None:
    """Read and parse the service status file.

    Returns:
        Parsed status dict, or None if the file is missing,
        unreadable, or lacks ``pid``/``port`` keys.

    """
    sf = _status_file()
    if not sf.exists():
        return None
    try:
        raw: object = json.loads(sf.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "pid" not in raw or "port" not in raw:
            return None
        return cast("dict[str, Any]", raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("service status file %s unreadable: %s", sf, exc, exc_info=True)
        return None


def _default_service_port() -> int | None:
    """Return the port of the currently running service, or ``None``.

    Reads ``service.json`` in the status directory; if absent or
    unparsable, returns ``None`` so callers emit the exit-3
    "service down" code path.
    """
    try:
        data = _read_service_status()
    except Exception as exc:
        # Broad except: status-file reads must never block the
        # command path; failures fall through to the exit-3
        # "service down" envelope. Debug-log so the swallow stays
        # observable.
        logger.debug("status read raised: %s", exc, exc_info=True)
        return None
    if not data:
        return None
    port = data.get("port")
    if isinstance(port, int):
        return port
    try:
        return int(port) if port is not None else None
    except (TypeError, ValueError) as exc:
        logger.debug("status port %r not coercible: %s", port, exc)
        return None
