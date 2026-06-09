"""Service status-file and log-file I/O for the background daemon.

Owns the ``~/.vaultspec-rag`` status directory, the ``service.json``
status file (atomic write + tolerant read), the rotating log file, and
the Windows-only lifecycle shutdown mirror line. The shutdown helper
resolves ``_log_file`` through the package namespace so tests that
swap ``vaultspec_rag.cli._log_file`` observe the substitution.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import vaultspec_rag.cli as _cli

from ._core import logger


def _status_dir() -> Path:
    """Return the global service status directory, creating it if needed.

    Resolved via ``cfg.status_dir`` (which checks CLI override, then
    ``VAULTSPEC_RAG_STATUS_DIR`` env var, then default
    ``~/.vaultspec-rag/``).

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


def _log_file() -> Path:
    """Return the path to the service log file.

    Resolved via ``cfg.log_file`` relative to the status directory.

    Returns:
        Path to ``{status_dir}/{log_file}``.
    """
    from ..config import get_config

    cfg = get_config()
    return _status_dir() / cfg.log_file


def _append_lifecycle_shutdown_log(reason: str, **kv: object) -> None:
    """Append a ``service.lifecycle``-style shutdown line to the rotating log.

    Used on Windows only - the daemon's atexit handler does not fire
    under ``TerminateProcess``, so the CLI parent emits a mirror line
    itself after a successful stop. Matches the daemon-side
    :func:`server._lifecycle_log` format so grep queries cover
    both code paths (daemon-emitted ``service.lifecycle`` and
    CLI-emitted ``cli.lifecycle``).

    Never raises: the shutdown path must complete even if the log
    file is missing or unwritable. Failures are logged at DEBUG so
    the suppression is observable.

    Args:
        reason: Short identifier (e.g. ``"cli_terminate"``).
        **kv: Extra key=value pairs (e.g. ``pid=...``,
            ``platform=...``) rendered space-separated.
    """
    path = _cli._log_file()
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    parts = ["event=shutdown", f"reason={reason}"]
    parts.extend(f"{k}={v}" for k, v in kv.items())
    line = f"{ts} WARNING  cli.lifecycle {' '.join(parts)}\n"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        # The shutdown path must complete even if the log file is
        # missing or unwritable. Per the no-swallow rule, the
        # exception is debug-logged so the suppression stays
        # observable.
        logger.debug("lifecycle log append failed: %s", exc, exc_info=True)


def _write_service_status(pid: int, port: int) -> None:
    """Write service status to the global status file.

    Args:
        pid: Process ID of the running service.
        port: TCP port the service is listening on.

    """
    data = {
        "pid": pid,
        "port": port,
        "started_at": datetime.now(UTC).isoformat(),
    }
    path = _status_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _update_service_token(token: str) -> None:
    """Persist *token* into the ``service_token`` field of ``service.json``.

    Reads the current status file, merges the new token, and atomically
    rewrites the file. A no-op (with a debug log) when the file is absent,
    unreadable, or already carries the same token. Never raises so the
    caller's normal flow is not interrupted.

    Args:
        token: ``service_token`` value from the ``/health`` response.

    """
    sf = _status_file()
    if not sf.exists():
        logger.debug("_update_service_token: service.json absent, skipping")
        return
    try:
        data: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("_update_service_token: read failed: %s", exc, exc_info=True)
        return
    if data.get("service_token") == token:
        return
    data["service_token"] = token
    tmp = sf.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(sf))
    except OSError as exc:
        logger.debug("_update_service_token: write failed: %s", exc, exc_info=True)


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
        data = json.loads(sf.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "pid" not in data or "port" not in data:
            return None
        return data
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
        data = _cli._read_service_status()
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
