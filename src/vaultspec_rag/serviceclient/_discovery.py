"""Import-light service discovery and atomic ``service.json`` publication.

The read helpers let any client (CLI or MCP) locate the running daemon
without loading Torch, the models, or the store. The status directory honors
``VAULTSPEC_RAG_STATUS_DIR`` through ``config.get_config`` (a lightweight
import). The shared merge writer serializes the CLI parent and daemon startup
publications so neither process can erase authoritative fields from the other.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

logger = logging.getLogger(__name__)

#: Discovery-file schema discriminator (#190). A consumer pins on
#: ``(SERVICE_DISCOVERY_SCHEMA, SERVICE_DISCOVERY_VERSION)``; bump the version on
#: any breaking shape change and update the schema document at
#: ``docs/service-discovery.md``.
SERVICE_DISCOVERY_SCHEMA = "vaultspec.rag.service"
SERVICE_DISCOVERY_VERSION = 1

#: Daemon-stamped lifecycle phase vocabulary for the optional ``phase`` field
#: of ``service.json``. The daemon (and only the daemon) stamps ``warming``
#: after it acquires the machine lock and ``running`` when it starts serving;
#: the CLI parent's spawn-time write carries no phase. An absent field keeps
#: pre-phase semantics (older daemons, or the stamp racing ahead of the
#: parent's write), so readers treat ``None`` as "unknown", never as warming.
#: Lives here (not in ``cli._service_status``) because the writing daemon must
#: stay free of ``vaultspec_rag.cli`` imports.
SERVICE_PHASE_WARMING = "warming"
SERVICE_PHASE_RUNNING = "running"

#: Fallback staleness window when a discovery payload omits ``stale_after_s``
#: (a pre-upgrade pointer). Mirrors ``server._HEARTBEAT_STALENESS_SECONDS``; the
#: payload's own ``stale_after_s`` is preferred when present so the threshold
#: tracks the writing daemon, not this consumer.
_HEARTBEAT_STALENESS_FALLBACK_SECONDS = 60

__all__ = [
    "SERVICE_DISCOVERY_SCHEMA",
    "SERVICE_DISCOVERY_VERSION",
    "SERVICE_PHASE_RUNNING",
    "SERVICE_PHASE_WARMING",
    "_default_service_port",
    "_delete_service_status",
    "_discovery_timestamp",
    "_machine_service_resolution",
    "_merge_service_status",
    "_read_service_status",
    "_replace_service_status",
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
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="create the managed service status directory",
        targets=(d,),
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_file() -> Path:
    """Return the path to the service status JSON file.

    Returns:
        Path to ``{status_dir}/service.json``.
    """
    return _status_dir() / "service.json"


def _try_lock_fd(fd: int) -> bool:
    """Take the OS advisory lock on *fd*; True when held, False when unavailable.

    A platform with no advisory-lock primitive (only reachable when the
    platform string is simulated; every real posix host ships ``fcntl``)
    reports success unlocked rather than failing the status write.
    """
    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            logger.debug("no msvcrt; status write proceeds unlocked")
            return True
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    try:
        import fcntl
    except ImportError:
        logger.debug("no fcntl; status write proceeds unlocked")
        return True
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True


def _unlock_fd(fd: int) -> None:
    """Release the OS advisory lock taken by :func:`_try_lock_fd`."""
    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            return
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    try:
        import fcntl
    except ImportError:
        return
    fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _status_write_lock(path: Path, *, timeout: float = 1.0) -> Generator[None]:
    """Serialize cross-process status merges with one bounded OS file lock."""
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="acquire the managed service status write lock",
        targets=(path,),
    )
    lock_path = path.with_name("service.json.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        while not acquired:
            try:
                acquired = _try_lock_fd(fd)
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"service status write lock exceeded {timeout:.3f}s"
                    ) from exc
                time.sleep(min(0.01, remaining))
        yield
    finally:
        if acquired:
            try:
                _unlock_fd(fd)
            except OSError as exc:
                logger.warning("service status write lock release failed: %s", exc)
        os.close(fd)


def _apply_status_merge_policy(
    data: dict[str, object],
    fields: Mapping[str, object],
    *,
    preserve_authoritative_identity: bool,
) -> dict[str, object]:
    """Decide the merged status document; pure, no I/O.

    A racing authoritative writer (a daemon that already published a phase on
    the same port) keeps its pid and first timestamp; a record describing a
    different pid or port is discarded rather than blended, so two services
    never fuse into one bogus entry.
    """
    merge_fields = dict(fields)
    incoming_port = merge_fields.get("port")
    same_port = (
        incoming_port is not None
        and data.get("port") is not None
        and data.get("port") == incoming_port
    )
    authoritative_existing = (
        preserve_authoritative_identity
        and same_port
        and data.get("phase") in {SERVICE_PHASE_WARMING, SERVICE_PHASE_RUNNING}
        and data.get("pid") is not None
    )
    if authoritative_existing:
        merge_fields.pop("pid", None)
        merge_fields.pop("started_at", None)
    # A different port means a genuinely different service instance, so the
    # stored record is dropped rather than blended. A differing pid is NOT
    # sufficient: the spawning launcher and the daemon it starts legitimately
    # publish different pids for the same port (a venv launcher on Windows),
    # and wiping there would destroy the port and discovery fields the
    # launcher had already written.
    if (
        data
        and incoming_port is not None
        and data.get("port") is not None
        and data.get("port") != incoming_port
    ):
        data = {}
    first_started_at = data.get("started_at")
    data.update(merge_fields)
    if first_started_at is not None:
        data["started_at"] = first_started_at
    return data


def _merge_service_status(
    fields: Mapping[str, object],
    *,
    timeout: float = 1.0,
    preserve_authoritative_identity: bool = False,
    require_existing: bool = False,
    path: Path | None = None,
) -> dict[str, object]:
    """Atomically merge fields without losing a racing authoritative writer.

    ``preserve_authoritative_identity`` is used by the spawning CLI parent. On
    Windows its returned process may be a venv launcher whose pid differs from
    the actual daemon. If that daemon has already published a lifecycle phase
    on the same port, its pid and first timestamp win over the late parent.
    """
    path = path or _status_file()
    with _status_write_lock(path, timeout=timeout):
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if require_existing:
                raise
            data: dict[str, object] = {}
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"service status read failed at {path}: {exc}") from exc
        else:
            data = cast("dict[str, object]", raw) if isinstance(raw, dict) else {}

        data = _apply_status_merge_policy(
            data,
            fields,
            preserve_authoritative_identity=preserve_authoritative_identity,
        )
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(str(tmp), str(path))
        finally:
            tmp.unlink(missing_ok=True)
        return data


def _replace_service_status(
    fields: Mapping[str, object],
    *,
    timeout: float = 1.0,
    path: Path | None = None,
) -> dict[str, object]:
    """Atomically replace status with one daemon-owned canonical snapshot.

    Unlike the launcher/daemon merge path, heartbeat recovery must not depend
    on the existing document being present or parseable. The shared status
    lock still serializes replacement with launcher merges and deletion, while
    the complete snapshot makes missing and corrupt operator views repairable.
    """
    path = path or _status_file()
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="replace the managed service status snapshot",
        targets=(path,),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(fields)
    encoded = json.dumps(data)
    with _status_write_lock(path, timeout=timeout):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    return data


def _delete_service_status(
    *,
    path: Path | None = None,
    timeout: float = 1.0,
) -> bool:
    """Serialize status deletion with all merges and heartbeat publications.

    The locked unlink is the deletion tombstone in the status operation order:
    a merge that completes first is removed, while a ``require_existing`` merge
    that runs after deletion observes the missing file and cannot recreate it.

    Returns:
        ``True`` when a file was removed, or ``False`` when it was already
        absent.
    """
    path = path or _status_file()
    if not path.parent.exists():
        return False
    with _status_write_lock(path, timeout=timeout):
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


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
