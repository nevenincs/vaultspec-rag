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
from dataclasses import dataclass
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

#: The heartbeat contract, defined once for every process that participates in
#: it. The daemon writes ``last_heartbeat`` into the discovery file four times a
#: minute; a reader calls the file stale once its age exceeds this window, which
#: tolerates three missed beats before the verdict flips to "crashed".
#:
#: It lives in this package because it is the only one all three participants
#: can already import: the daemon writes the beat, the CLI judges it, and this
#: client falls back to it. The CLI must not import ``server`` (that would pull
#: the whole service stack into CLI startup) and ``server`` must not import
#: ``cli``, so before this the value existed as three hand-synchronised copies -
#: one of which carried a comment instructing the next reader to "bump both in
#: lockstep". A threshold that must be edited in three places to stay correct
#: will eventually be edited in one, and the symptom is a status surface that
#: calls a live daemon dead.
HEARTBEAT_STALENESS_SECONDS = 60

#: Fallback staleness window when a discovery payload omits ``stale_after_s``
#: (a pre-upgrade pointer). The payload's own ``stale_after_s`` is preferred when
#: present so the threshold tracks the writing daemon, not this consumer.
_HEARTBEAT_STALENESS_FALLBACK_SECONDS = HEARTBEAT_STALENESS_SECONDS

#: Resolution outcomes. ``ready`` carries a usable address; ``absent`` means no
#: machine singleton is held, so nothing is running; ``degraded`` means a live
#: holder owns the singleton but its published pointer cannot be trusted. The
#: three are exhaustive and mutually exclusive, and ``degraded`` is deliberately
#: distinct from ``absent`` so an operator surface never renders a live-but-
#: unpublished daemon as stopped.
DISCOVERY_STATE_READY = "ready"
DISCOVERY_STATE_ABSENT = "absent"
DISCOVERY_STATE_DEGRADED = "degraded"

#: Why a live holder's pointer was refused. Each reason names the specific
#: disagreement so a caller can report evidence instead of a bare failure.
DISCOVERY_REASON_POINTER_MISSING = "pointer_missing"
DISCOVERY_REASON_POINTER_INVALID = "pointer_invalid"
DISCOVERY_REASON_POINTER_STALE = "pointer_stale"
DISCOVERY_REASON_POINTER_FOREIGN = "pointer_foreign"
DISCOVERY_REASON_PROBE_FAILED = "probe_failed"

#: Which view supplied the resolved address.
DISCOVERY_SOURCE_MACHINE_POINTER = "machine_pointer"
DISCOVERY_SOURCE_STATUS_FILE = "status_file"
DISCOVERY_SOURCE_NONE = "none"

__all__ = [
    "DISCOVERY_REASON_POINTER_FOREIGN",
    "DISCOVERY_REASON_POINTER_INVALID",
    "DISCOVERY_REASON_POINTER_MISSING",
    "DISCOVERY_REASON_POINTER_STALE",
    "DISCOVERY_REASON_PROBE_FAILED",
    "DISCOVERY_SOURCE_MACHINE_POINTER",
    "DISCOVERY_SOURCE_NONE",
    "DISCOVERY_SOURCE_STATUS_FILE",
    "DISCOVERY_STATE_ABSENT",
    "DISCOVERY_STATE_DEGRADED",
    "DISCOVERY_STATE_READY",
    "SERVICE_DISCOVERY_SCHEMA",
    "SERVICE_DISCOVERY_VERSION",
    "SERVICE_PHASE_RUNNING",
    "SERVICE_PHASE_WARMING",
    "MachineResolution",
    "_default_service_port",
    "_delete_service_status",
    "_discovery_timestamp",
    "_machine_service_resolution",
    "_merge_service_status",
    "_read_service_status",
    "_replace_service_status",
    "_status_dir",
    "_status_file",
    "resolve_machine_service",
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


def _heartbeat_age_seconds(payload: dict[str, Any]) -> float | None:
    """Return the payload heartbeat's age in seconds, or ``None`` when absent."""
    from datetime import UTC, datetime

    raw = payload.get("last_heartbeat")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.debug("discovery last_heartbeat %r unparseable: %s", raw, exc)
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ts).total_seconds()


def _staleness_window_seconds(payload: dict[str, Any]) -> float:
    """Return the payload's own staleness window, or the fallback."""
    threshold = payload.get("stale_after_s")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        return float(_HEARTBEAT_STALENESS_FALLBACK_SECONDS)
    return (
        float(threshold)
        if threshold > 0
        else float(_HEARTBEAT_STALENESS_FALLBACK_SECONDS)
    )


@dataclass(frozen=True, slots=True)
class MachineResolution:
    """One resolution of the machine singleton, with the evidence behind it.

    The OS advisory lock is the liveness authority and the machine-global
    pointer carries the address, so the two can disagree.  Preserving both
    identities plus the freshness evidence is what lets a caller distinguish
    "nothing is running" from "something is running but has not published a
    trustworthy address", and report which of the two it saw.
    """

    state: str
    source: str
    holder_pid: int = 0
    pointer_pid: int | None = None
    port: int | None = None
    service_token: str | None = None
    heartbeat_age_s: float | None = None
    stale_after_s: float | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def is_ready(self) -> bool:
        """Whether this resolution carries a usable service address."""
        return self.state == DISCOVERY_STATE_READY and self.port is not None

    @property
    def is_degraded(self) -> bool:
        """Whether a live holder exists whose published pointer was refused."""
        return self.state == DISCOVERY_STATE_DEGRADED

    def evidence(self) -> str:
        """Render a one-line operator-facing account of this resolution."""
        if self.state == DISCOVERY_STATE_READY:
            return (
                f"service on port {self.port} "
                f"(holder pid {self.holder_pid}, source {self.source})"
            )
        if self.state == DISCOVERY_STATE_ABSENT:
            return "no machine singleton is held"
        parts = [f"live holder pid {self.holder_pid}"]
        if self.pointer_pid is not None:
            parts.append(f"pointer pid {self.pointer_pid}")
        if self.heartbeat_age_s is not None:
            parts.append(f"heartbeat age {self.heartbeat_age_s:.1f}s")
        if self.stale_after_s is not None:
            parts.append(f"stale after {self.stale_after_s:.0f}s")
        return f"{self.reason}: " + ", ".join(parts)


def resolve_machine_service() -> MachineResolution:
    """Resolve the machine singleton into one typed, evidence-carrying verdict.

    A live OS-lock holder with an untrustworthy pointer resolves ``degraded``,
    never ``absent`` and never through the status-file fallback: something owns
    the singleton, so reporting it as stopped would invite a caller to start a
    second daemon that must then lose the race, and accepting a status-file
    address would point that caller at an address the owner never published.
    The status file is consulted only when no holder exists at all, which is the
    pre-pointer compatibility case.
    """
    from .._machine_lock import machine_lock_live_holder, read_machine_discovery

    try:
        holder = machine_lock_live_holder()
    except Exception as exc:
        # Broad except: discovery must never block the command path. A probe
        # that cannot run is reported as such rather than silently becoming
        # absence, which would read as "nothing is running".
        logger.debug("machine lock holder probe raised: %s", exc, exc_info=True)
        return MachineResolution(
            state=DISCOVERY_STATE_DEGRADED,
            source=DISCOVERY_SOURCE_NONE,
            reason=DISCOVERY_REASON_PROBE_FAILED,
        )

    if holder <= 0:
        return _status_file_resolution()

    try:
        payload = read_machine_discovery()
    except Exception as exc:
        logger.debug("machine discovery read raised: %s", exc, exc_info=True)
        return MachineResolution(
            state=DISCOVERY_STATE_DEGRADED,
            source=DISCOVERY_SOURCE_MACHINE_POINTER,
            holder_pid=holder,
            reason=DISCOVERY_REASON_PROBE_FAILED,
        )

    if payload is None:
        return MachineResolution(
            state=DISCOVERY_STATE_DEGRADED,
            source=DISCOVERY_SOURCE_MACHINE_POINTER,
            holder_pid=holder,
            reason=DISCOVERY_REASON_POINTER_MISSING,
        )

    port = _coerce_port(payload.get("port"))
    raw_pid = payload.get("pid")
    pointer_pid = (
        raw_pid if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) else None
    )
    token = payload.get("service_token")
    age = _heartbeat_age_seconds(payload)
    window = _staleness_window_seconds(payload)

    def degraded(reason: str) -> MachineResolution:
        return MachineResolution(
            state=DISCOVERY_STATE_DEGRADED,
            source=DISCOVERY_SOURCE_MACHINE_POINTER,
            holder_pid=holder,
            pointer_pid=pointer_pid,
            port=port,
            service_token=token if isinstance(token, str) else None,
            heartbeat_age_s=age,
            stale_after_s=window,
            reason=reason,
            payload=payload,
        )

    if port is None:
        return degraded(DISCOVERY_REASON_POINTER_INVALID)
    # The publisher refuses to write a payload whose pid is not the lease
    # owner's, so a pointer naming anyone but the live holder is a leftover
    # from a previous incarnation rather than this owner's publication.
    if pointer_pid is not None and pointer_pid != holder:
        return degraded(DISCOVERY_REASON_POINTER_FOREIGN)
    if age is not None and age > window:
        return degraded(DISCOVERY_REASON_POINTER_STALE)

    return MachineResolution(
        state=DISCOVERY_STATE_READY,
        source=DISCOVERY_SOURCE_MACHINE_POINTER,
        holder_pid=holder,
        pointer_pid=pointer_pid,
        port=port,
        service_token=token if isinstance(token, str) else None,
        heartbeat_age_s=age,
        stale_after_s=window,
        payload=payload,
    )


def _status_file_resolution() -> MachineResolution:
    """Resolve through the per-status-directory file (no singleton is held).

    Reached only when the OS lock reports no holder, so this cannot mask a live
    owner's degraded publication.
    """
    try:
        data = _read_service_status()
    except Exception as exc:
        # Broad except: status reads must never block the command path.
        logger.debug("status read raised: %s", exc, exc_info=True)
        return MachineResolution(
            state=DISCOVERY_STATE_ABSENT,
            source=DISCOVERY_SOURCE_NONE,
        )
    port = _coerce_port(data.get("port")) if data else None
    if not data or port is None:
        return MachineResolution(
            state=DISCOVERY_STATE_ABSENT,
            source=DISCOVERY_SOURCE_NONE,
        )
    raw_pid = data.get("pid")
    token = data.get("service_token")
    return MachineResolution(
        state=DISCOVERY_STATE_READY,
        source=DISCOVERY_SOURCE_STATUS_FILE,
        pointer_pid=(
            raw_pid
            if isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
            else None
        ),
        port=port,
        service_token=token if isinstance(token, str) else None,
        payload=data,
    )


def _machine_service_resolution() -> dict[str, Any] | None:
    """Return the live machine pointer payload, or ``None``.

    Thin compatibility view over :func:`resolve_machine_service` for callers
    that only need the payload of a trustworthy machine publication. A degraded
    resolution (a live holder whose pointer is missing, invalid, foreign, or
    stale) collapses to ``None`` here; callers that must distinguish degraded
    from absent use the typed resolution directly.
    """
    resolution = resolve_machine_service()
    if resolution.is_ready and resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER:
        return resolution.payload
    return None


def _default_service_port() -> int | None:
    """Return the port of the currently running service, or ``None``.

    Resolution is authoritative on machine-global state: a live singleton
    holder's own publication wins, so a stale or foreign per-status-directory
    ``service.json`` can no longer mislead a long-lived consumer (the MCP)
    frozen onto the wrong status directory. When a holder is live but its
    pointer cannot be trusted, this returns ``None`` rather than falling back to
    the status file - that fallback would hand out an address the owner never
    published. The status file is consulted only when no singleton is held at
    all (older daemons, or a deployment that does not write the pointer).
    ``None`` means no usable address, and callers emit the exit-3 path.
    """
    resolution = resolve_machine_service()
    return resolution.port if resolution.is_ready else None
