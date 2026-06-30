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

#: Discovery-file schema discriminator (#190). A consumer pins on
#: ``(SERVICE_DISCOVERY_SCHEMA, SERVICE_DISCOVERY_VERSION)``; bump the version on
#: any breaking shape change and update the schema document at
#: ``docs/service-discovery.md``.
SERVICE_DISCOVERY_SCHEMA = "vaultspec.rag.service"
SERVICE_DISCOVERY_VERSION = 1

#: Fallback staleness window when a discovery payload omits ``stale_after_s``
#: (a pre-upgrade pointer). Mirrors ``server._HEARTBEAT_STALENESS_SECONDS``; the
#: payload's own ``stale_after_s`` is preferred when present so the threshold
#: tracks the writing daemon, not this consumer.
_HEARTBEAT_STALENESS_FALLBACK_SECONDS = 60

__all__ = [
    "SERVICE_DISCOVERY_SCHEMA",
    "SERVICE_DISCOVERY_VERSION",
    "_default_service_port",
    "_discovery_timestamp",
    "_machine_service_resolution",
    "_read_service_status",
    "_status_dir",
    "_status_file",
]


def _discovery_timestamp() -> str:
    """Return the one declared discovery-file timestamp format (#190).

    ISO-8601 with offset at second precision. Both writers - the CLI-parent
    initial write (``started_at``) and the daemon heartbeat (``last_heartbeat``) -
    use this single helper so the two fields never diverge in format or precision
    (the divergence that broke a consumer parsing the file).
    """
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


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


def _coerce_port(port: Any) -> int | None:
    """Coerce a discovery-payload ``port`` field to ``int`` or ``None``."""
    if isinstance(port, bool):
        return None
    if isinstance(port, int):
        return port
    try:
        return int(port) if port is not None else None
    except (TypeError, ValueError) as exc:
        logger.debug("discovery port %r not coercible: %s", port, exc)
        return None


def _discovery_is_stale(payload: dict[str, Any]) -> bool:
    """Return whether *payload*'s heartbeat is past its staleness window.

    The window is the payload's own ``stale_after_s`` (so it tracks the writing
    daemon), falling back to ``_HEARTBEAT_STALENESS_FALLBACK_SECONDS``. A missing
    or unparseable ``last_heartbeat`` is treated as *not* stale here: liveness is
    already gated by the OS lock in :func:`_machine_service_resolution`, and a
    pre-upgrade pointer without the field must not be rejected on staleness alone.
    """
    from datetime import UTC, datetime

    raw = payload.get("last_heartbeat")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.debug("discovery last_heartbeat %r unparseable: %s", raw, exc)
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - ts).total_seconds()
    threshold = payload.get("stale_after_s")
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        threshold = _HEARTBEAT_STALENESS_FALLBACK_SECONDS
    return age > float(threshold)


def _machine_service_resolution() -> dict[str, Any] | None:
    """Resolve the one live machine service via the machine-global pointer.

    Status-directory independent and re-read per call: the resident service is a
    machine singleton, so a consumer locates it through machine-global state it
    shares regardless of its own ``VAULTSPEC_RAG_STATUS_DIR``. The OS advisory
    lock is the liveness authority (a dead daemon's lock is released by the OS),
    and the machine-global pointer carries the address. The payload is accepted
    only when a live lock holder exists *and* the pointer is fresh within its
    staleness window - so an orphaned pointer left by a crashed daemon (a dead
    pid, a days-old heartbeat) is treated as absence, not as a live service.

    Returns the validated discovery payload (carrying ``port`` and, when written,
    ``service_token``), or ``None`` when no live machine service resolves.
    """
    from .._machine_lock import machine_lock_live_holder, read_machine_discovery

    try:
        if machine_lock_live_holder() <= 0:
            return None
        payload = read_machine_discovery()
    except Exception as exc:
        # Broad except: discovery must never block the command path; any
        # failure degrades to "no machine resolution" and the status-dir hint.
        logger.debug("machine discovery probe raised: %s", exc, exc_info=True)
        return None
    if not payload or _coerce_port(payload.get("port")) is None:
        return None
    if _discovery_is_stale(payload):
        logger.debug("machine discovery pointer is stale; treating as absent")
        return None
    return payload


def _default_service_port() -> int | None:
    """Return the port of the currently running service, or ``None``.

    Resolution is authoritative on machine-global state: the machine-singleton
    pointer, gated by the OS-lock live holder and heartbeat staleness, wins when
    it resolves - so a stale or foreign per-status-directory ``service.json`` can
    no longer mislead a long-lived consumer (the MCP) frozen onto the wrong
    status directory. The per-status-directory ``service.json`` is consulted only
    as a compatibility fallback when no live machine service resolves (older
    daemons, or a deployment that does not write the pointer). ``None`` means no
    live service, and callers emit the exit-3 "service down" path.
    """
    resolution = _machine_service_resolution()
    if resolution is not None:
        port = _coerce_port(resolution.get("port"))
        if port is not None:
            return port
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
    return _coerce_port(data.get("port"))
