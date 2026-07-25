"""Service status-file and log-file I/O for the background daemon.

Owns the ``~/.vaultspec-rag`` status directory, the ``service.json``
status file (atomic write + tolerant read), the rotating log file, and
the Windows-only lifecycle shutdown mirror line. The shutdown helper
resolves ``_log_file`` through the package namespace so tests that
swap ``vaultspec_rag.cli._log_file`` observe the substitution.

The read-only discovery surface (``_status_dir``, ``_status_file``,
``_read_service_status``, ``_default_service_port``) was factored into the
import-light ``vaultspec_rag.serviceclient`` package so the CLI and the MCP
share one client. Those names are re-exported here unchanged so the CLI's
existing imports keep working; the status *writer* helpers below stay owned
by this module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import vaultspec_rag.cli as _cli

from ..serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    SERVICE_PHASE_RUNNING,
    SERVICE_PHASE_WARMING,
    _default_service_port,
    _delete_service_status,
    _discovery_timestamp,
    _merge_service_status,
    _read_service_status,
    _status_dir,
    _status_file,
)
from ._core import logger

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "SERVICE_PHASE_RUNNING",
    "SERVICE_PHASE_WARMING",
    "_append_lifecycle_shutdown_log",
    "_default_service_port",
    "_delete_service_status",
    "_log_file",
    "_read_service_status",
    "_service_phase",
    "_status_dir",
    "_status_file",
    "_update_service_metadata",
    "_update_service_token",
    "_write_service_status",
]


def _service_phase(status: dict[str, Any] | None) -> str | None:
    """Return the daemon-stamped lifecycle phase from a status dict, if any."""
    if not isinstance(status, dict):
        return None
    phase = status.get("phase")
    return phase if isinstance(phase, str) and phase else None


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


def _write_service_status(pid: int, port: int, *, timeout: float = 1.0) -> None:
    """Write service status to the global status file.

    Args:
        pid: Process ID of the running service.
        port: TCP port the service is listening on.

    """
    from ..serviceclient._release import RELEASE_FIELD, local_release

    data = {
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        "pid": pid,
        "port": port,
        "started_at": _discovery_timestamp(),
        # The spawning launcher's release. The daemon overwrites this with its
        # own on the first heartbeat; until then it is the only release the
        # file can honestly report, and publishing it keeps the field present
        # from the moment the file exists rather than only after warm-up.
        RELEASE_FIELD: local_release(),
    }
    _merge_service_status(
        data,
        timeout=timeout,
        preserve_authoritative_identity=True,
    )


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
    current = _read_service_status()
    if current is not None and current.get("service_token") == token:
        # Already current: skip the write so an unchanged token never churns
        # the file's mtime, which discovery consumers read as recency.
        logger.debug("_update_service_token: token already current, skipping")
        return
    try:
        _merge_service_status(
            {"service_token": token},
            path=sf,
            require_existing=True,
        )
    except (OSError, RuntimeError, TimeoutError) as exc:
        logger.debug("_update_service_token: write failed: %s", exc, exc_info=True)


def _update_service_metadata(fields: dict[str, object]) -> None:
    """Merge daemon-reported metadata into ``service.json`` atomically."""
    sf = _status_file()
    if not sf.exists():
        logger.debug("_update_service_metadata: service.json absent, skipping")
        return
    retained = {key: value for key, value in fields.items() if value is not None}
    if not retained:
        return
    try:
        _merge_service_status(retained, path=sf, require_existing=True)
    except (OSError, RuntimeError, TimeoutError) as exc:
        logger.debug("_update_service_metadata: write failed: %s", exc, exc_info=True)
