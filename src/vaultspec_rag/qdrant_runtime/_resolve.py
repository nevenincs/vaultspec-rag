"""Platform-to-asset mapping and active-binary resolution.

Resolution order for the binary the service will execute:

1. ``VAULTSPEC_RAG_QDRANT_BINARY`` - operator-supplied path (the
   air-gapped / proxy / policy escape hatch). Trusted as-is.
2. The managed bin dir (``{status_dir}/bin/qdrant/{version}/``) when a
   provisioning manifest is present and consistent with the committed
   pin.
3. ``qdrant`` on ``PATH`` - a convenience for system-managed installs;
   version is not guaranteed and a skew warning is logged downstream.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform as _platform
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from ..config import EnvVar, get_config
from ._constants import (
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
    ResolvedBinary,
)

logger = logging.getLogger(__name__)

__all__ = [
    "QdrantEndpointProbe",
    "QdrantIdentity",
    "asset_for_platform",
    "binary_filename",
    "classify_qdrant_state",
    "decide_qdrant_action",
    "has_provisioned_binary",
    "owner_pid_is_live_owner",
    "owner_pid_witness_state",
    "pid_alive",
    "pid_image_is_qdrant",
    "pid_listens_on_loopback_port",
    "pid_matches_start_time",
    "pid_start_time",
    "probe_qdrant_endpoint",
    "qdrant_bin_dir",
    "qdrant_identity_path",
    "read_manifest",
    "read_qdrant_identity",
    "reap_qdrant_orphan",
    "resolve_binary",
    "verify_attachable",
    "write_qdrant_identity",
]

# Loopback probes must never traverse an HTTP(S) proxy from the environment: a
# proxy could spoof a "ready"/version response a caller would trust when
# deciding whether to attach to an already-running Qdrant.
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_START_TIME_TOLERANCE_SECONDS = 1e-6


@dataclass(frozen=True)
class QdrantEndpointProbe:
    """The observable state of whatever is on the Qdrant port.

    Attributes:
        listening: A TCP connection was accepted on the port.
        ready: The ``/readyz`` endpoint returned HTTP 200.
        version: The server version from the root route, or ``""`` when
            unavailable (not listening, or the route did not parse).
    """

    listening: bool
    ready: bool
    version: str


def probe_qdrant_endpoint(
    http_port: int,
    *,
    timeout: float = 2.0,
) -> QdrantEndpointProbe:
    """Probe ``127.0.0.1:http_port`` for a live, ready Qdrant and its version.

    Pure observation with no side effects: distinguishes "nothing is listening"
    (connection refused) from "something is listening" and, when it is,
    whether it is ready and what version it reports. The attach decision (a
    later step) layers capability and ownership checks on top of this.

    Args:
        http_port: The loopback REST port to probe.
        timeout: Per-request connect/read timeout in seconds.

    Returns:
        A :class:`QdrantEndpointProbe` snapshot.
    """
    base = f"http://127.0.0.1:{http_port}"
    listening = False
    ready = False
    try:
        with _LOOPBACK_OPENER.open(f"{base}/readyz", timeout=timeout) as resp:
            listening = True
            ready = int(resp.status) == 200
    except urllib.error.HTTPError as exc:
        # An HTTP error response still means something is listening and
        # answering - just not ready.
        listening = True
        logger.debug("qdrant /readyz on %d returned HTTP %s", http_port, exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("qdrant /readyz probe on %d failed: %s", http_port, exc)
        return QdrantEndpointProbe(listening=False, ready=False, version="")

    version = ""
    try:
        with _LOOPBACK_OPENER.open(base, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict):
            version = str(cast("dict[str, object]", payload).get("version", ""))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("qdrant version probe on %d failed: %s", http_port, exc)

    return QdrantEndpointProbe(listening=listening, ready=ready, version=version)


_ARM_MACHINES = frozenset({"arm64", "aarch64"})
_X86_MACHINES = frozenset({"amd64", "x86_64"})


def asset_for_platform(
    platform: str | None = None,
    machine: str | None = None,
) -> str:
    """Return the release asset name for a platform/arch pair.

    Args:
        platform: ``sys.platform`` value (``win32`` / ``darwin`` /
            ``linux``). Defaults to the running platform.
        machine: ``platform.machine()`` value. Defaults to the running
            machine.

    Returns:
        The asset filename, guaranteed to be a key of
        :data:`QDRANT_ASSET_SHA256`.

    Raises:
        RuntimeError: If the platform/arch pair has no upstream
            release asset.
    """
    plat = (platform or sys.platform).lower()
    mach = (machine or _platform.machine()).lower()

    asset: str | None = None
    if plat == "win32" and mach in _X86_MACHINES:
        asset = "qdrant-x86_64-pc-windows-msvc.zip"
    elif plat == "darwin":
        if mach in _ARM_MACHINES:
            asset = "qdrant-aarch64-apple-darwin.tar.gz"
        elif mach in _X86_MACHINES:
            asset = "qdrant-x86_64-apple-darwin.tar.gz"
    elif plat.startswith("linux"):
        if mach in _X86_MACHINES:
            asset = "qdrant-x86_64-unknown-linux-gnu.tar.gz"
        elif mach in _ARM_MACHINES:
            asset = "qdrant-aarch64-unknown-linux-musl.tar.gz"

    if asset is None:
        raise RuntimeError(
            f"No Qdrant server release asset exists for platform={plat!r} "
            f"machine={mach!r}. Supply a binary via "
            f"{EnvVar.QDRANT_BINARY.value} instead."
        )
    if asset not in QDRANT_ASSET_SHA256:
        raise RuntimeError(
            f"Asset {asset!r} has no committed SHA256 digest; the pin "
            "table is incomplete."
        )
    return asset


def binary_filename(platform: str | None = None) -> str:
    """Return the qdrant executable filename for *platform*."""
    plat = (platform or sys.platform).lower()
    return "qdrant.exe" if plat == "win32" else "qdrant"


def qdrant_bin_dir(version: str = QDRANT_SERVER_VERSION) -> Path:
    """Return the managed install dir for *version*.

    Lives under the service status dir so the
    ``VAULTSPEC_RAG_STATUS_DIR`` isolation knob carries provisioning
    state along with the rest of the managed service directory.
    """
    cfg = get_config()
    return Path(str(cfg.status_dir)).expanduser() / "bin" / "qdrant" / version


def read_manifest(version_dir: Path) -> dict[str, Any] | None:
    """Read and parse the provisioning manifest in *version_dir*.

    Returns:
        The manifest dict, or ``None`` when absent or unreadable
        (logged at debug per the no-swallow rule).
    """
    path = version_dir / MANIFEST_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug("qdrant manifest unreadable at %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.debug("qdrant manifest at %s is not a dict", path)
        return None
    return cast("dict[str, Any]", data)


_IDENTITY_FILENAME = "identity.json"


@dataclass(frozen=True)
class QdrantIdentity:
    """The managed-Qdrant identity sidecar written by the supervisor on bring-up.

    A local-trust record (it lives in the machine-global managed dir, not on the
    network) letting a later start confirm a running Qdrant is the one this
    machine's service manages, and learn its owner pid to classify orphans.

    Attributes:
        storage_path: The storage directory the managed server was started on.
        version: The managed server version that was started.
        owner_pid: PID of the service process that spawned the Qdrant child.
        http_port: The REST port the managed server was started on.
        qdrant_pid: PID of the Qdrant child process itself - the reap target when
            the owner is dead but the child still holds the port. ``0`` when the
            record predates this field (treated as "unknown, cannot reap").
        qdrant_start_time: The Qdrant child's creation time (epoch seconds).
            This binds the reap target to one child-process incarnation rather
            than a reusable PID. ``0.0`` means the identity predates the witness
            and cannot authorize automated signalling.
        owner_start_time: The owner process's creation time (epoch seconds), the
            anti-pid-reuse witness. A pid alone is reusable: on a busy machine a
            dead owner's pid may be recycled by an unrelated live process, which
            a bare liveness check would misread as a live owner (``managed_running``).
            The start-time pins the identity to one process incarnation. ``0.0``
            when the record predates this field (treated as "unknown": liveness
            falls back to the pid alone).
    """

    storage_path: str
    version: str
    owner_pid: int
    http_port: int
    qdrant_pid: int = 0
    owner_start_time: float = 0.0
    qdrant_start_time: float = 0.0


def qdrant_identity_path() -> Path:
    """Path of the managed-Qdrant identity sidecar (machine-global)."""
    cfg = get_config()
    storage = Path(str(cfg.qdrant_storage_dir)).expanduser()
    return storage.parent / _IDENTITY_FILENAME


def read_qdrant_identity() -> QdrantIdentity | None:
    """Read the managed-Qdrant identity sidecar, or ``None`` when absent/invalid.

    A missing sidecar (no managed Qdrant was ever brought up here) or a
    malformed one is treated as "no record" rather than raised, so detection
    degrades to "unknown owner" rather than crashing startup.
    """
    path = qdrant_identity_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug("qdrant identity sidecar unreadable at %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    d = cast("dict[str, object]", data)
    try:
        return QdrantIdentity(
            storage_path=str(d["storage_path"]),
            version=str(d["version"]),
            owner_pid=int(cast("str | int | float", d["owner_pid"])),
            http_port=int(cast("str | int | float", d["http_port"])),
            qdrant_pid=int(cast("str | int | float", d.get("qdrant_pid", 0))),
            qdrant_start_time=float(
                cast("str | int | float", d.get("qdrant_start_time", 0.0))
            ),
            owner_start_time=float(
                cast("str | int | float", d.get("owner_start_time", 0.0))
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("qdrant identity sidecar incomplete at %s: %s", path, exc)
        return None


def pid_alive(pid: int) -> bool:
    """Return whether *pid* is a live process (cross-platform, best-effort).

    Used to tell a live storage owner from a dead one when classifying an
    orphan. A permission error means the process exists but is not ours to
    signal, which still counts as alive.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query_limited = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _bounded_call[T](
    operation: Callable[[], T],
    *,
    timeout: float | None,
    fallback: T,
    label: str,
) -> T:
    """Run a potentially blocking local inspection inside an optional budget."""
    if timeout is None:
        return operation()
    if timeout <= 0.0:
        return fallback

    import queue
    import threading

    outcomes: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            outcomes.put((True, operation()))
        except BaseException as exc:
            outcomes.put((False, exc))

    threading.Thread(target=run, daemon=True, name=f"vaultspec-{label}").start()
    try:
        succeeded, value = outcomes.get(timeout=timeout)
    except queue.Empty:
        logger.debug("%s exceeded its %.3fs inspection budget", label, timeout)
        return fallback
    if not succeeded:
        logger.debug("%s failed: %s", label, value)
        return fallback
    return cast("T", value)


def pid_start_time(pid: int, *, timeout: float | None = None) -> float:
    """Return *pid*'s process creation time (epoch seconds), or ``0.0``.

    The pid-reuse witness: two processes that share a recycled pid have
    different creation times, so comparing this against a recorded value tells a
    surviving original owner from an unrelated process that inherited its pid.
    ``0.0`` means the time could not be read (no such process, or no permission)
    and the caller must not treat it as a match.
    """
    if pid <= 0:
        return 0.0

    def inspect() -> float:
        import psutil

        try:
            return float(psutil.Process(pid).create_time())
        except Exception as exc:  # psutil raises NoSuchProcess/AccessDenied/etc.
            logger.debug("could not read start time for pid %d: %s", pid, exc)
            return 0.0

    return _bounded_call(
        inspect,
        timeout=timeout,
        fallback=0.0,
        label=f"pid-{pid}-start-time",
    )


def pid_matches_start_time(
    pid: int,
    expected_start_time: float,
    *,
    timeout: float | None = None,
) -> bool:
    """Return whether *pid* is the exact witnessed process incarnation."""
    if expected_start_time <= 0.0:
        return False
    live_start = pid_start_time(pid, timeout=timeout)
    return (
        live_start > 0.0
        and abs(live_start - expected_start_time) <= _START_TIME_TOLERANCE_SECONDS
    )


def owner_pid_is_live_owner(identity: QdrantIdentity | None) -> bool:
    """Return whether *identity*'s owner pid is the live original owner.

    Hardens the bare ``pid_alive`` check against pid reuse: a dead owner's pid
    recycled by an unrelated live process must NOT read as a live owner. The
    owner is live only when its pid is alive AND its recorded creation time
    matches the live process's creation time. A legacy record without a recorded
    start time is unverified and therefore fails closed.
    """
    return owner_pid_witness_state(identity) == "live"


def owner_pid_witness_state(
    identity: QdrantIdentity | None,
    *,
    timeout: float | None = None,
) -> str:
    """Classify the recorded owner incarnation without treating unknown as dead."""
    if identity is None or not pid_alive(identity.owner_pid):
        return "dead"
    if identity.owner_start_time <= 0.0:
        return "unknown"
    live_start = pid_start_time(identity.owner_pid, timeout=timeout)
    if live_start <= 0.0:
        return "unknown"
    if (
        abs(live_start - identity.owner_start_time)
        <= _START_TIME_TOLERANCE_SECONDS
    ):
        return "live"
    return "replaced"


def reap_qdrant_orphan(
    pid: int,
    *,
    wait_seconds: float = 5.0,
    expected_start_time: float | None = None,
) -> bool:
    """Terminate an orphaned managed-Qdrant process by pid; report success.

    Used only after the orphan has been positively classified (the recorded
    owner is dead but the child still holds the port). Terminates gracefully,
    escalating to a hard kill, then verifies the pid is gone. A non-positive or
    already-dead pid is a no-op that reports success.

    Returns:
        ``True`` when the pid is no longer alive after the attempt.
    """
    import time as _time
    deadline = _time.monotonic() + max(0.0, wait_seconds)

    def target_is_gone_or_replaced() -> bool:
        if not pid_alive(pid):
            return True
        remaining = deadline - _time.monotonic()
        if remaining <= 0.0:
            return False
        return expected_start_time is not None and not pid_matches_start_time(
            pid,
            expected_start_time,
            timeout=remaining,
        )

    if pid <= 0:
        return False
    if target_is_gone_or_replaced():
        return True
    if sys.platform == "win32":
        import subprocess

        if target_is_gone_or_replaced():
            return True
        try:
            subprocess.run(  # fixed argv, no shell, trusted pid
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=max(0.001, deadline - _time.monotonic()),
            )
        except subprocess.TimeoutExpired:
            return target_is_gone_or_replaced()
    else:
        import signal

        if target_is_gone_or_replaced():
            return True
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        while _time.monotonic() < deadline and not target_is_gone_or_replaced():
            _time.sleep(0.1)
        if not target_is_gone_or_replaced():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    while _time.monotonic() < deadline and not target_is_gone_or_replaced():
        _time.sleep(0.1)
    return target_is_gone_or_replaced()


def pid_image_is_qdrant(pid: int, *, timeout: float | None = None) -> bool:
    """Return whether *pid* is a live process whose executable is qdrant.

    A reap target's pid comes from a now-dead owner's identity record; on a busy
    machine that pid may have been recycled by an unrelated process. Reaping
    must confirm the target is actually a qdrant process (not a recycled pid)
    before issuing a hard kill, so an unrelated process is never killed.
    """
    if not pid_alive(pid):
        return False
    if sys.platform == "win32":
        import subprocess

        if timeout is not None and timeout <= 0.0:
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.debug(
                "qdrant image inspection for pid %d exceeded %.3fs",
                pid,
                timeout,
            )
            return False
        return "qdrant" in result.stdout.lower()
    for proc_file in ("comm", "cmdline"):
        try:
            text = Path(f"/proc/{pid}/{proc_file}").read_text(encoding="utf-8")
        except OSError:
            continue
        if "qdrant" in text.lower():
            return True
    return False


def pid_listens_on_loopback_port(
    pid: int,
    port: int,
    *,
    timeout: float | None = None,
) -> bool:
    """Return whether this exact process owns the loopback listening port."""
    if pid <= 0 or port <= 0:
        return False
    def inspect() -> bool:
        import psutil

        try:
            connections = psutil.Process(pid).net_connections(kind="tcp")
        except Exception as exc:
            logger.debug(
                "could not inspect TCP listener ownership for pid %d port %d: %s",
                pid,
                port,
                exc,
            )
            return False
        for connection in connections:
            if connection.status != psutil.CONN_LISTEN:
                continue
            address = connection.laddr
            host = str(address.ip)
            if int(address.port) == port and host in {"127.0.0.1", "::1"}:
                return True
        return False

    return _bounded_call(
        inspect,
        timeout=timeout,
        fallback=False,
        label=f"pid-{pid}-listener",
    )


def write_qdrant_identity(
    *,
    storage_path: str,
    version: str,
    owner_pid: int,
    http_port: int,
    qdrant_pid: int = 0,
    qdrant_start_time: float | None = None,
    owner_start_time: float | None = None,
) -> Path:
    """Atomically write the managed-Qdrant identity sidecar.

    Called by the supervisor once the managed server is confirmed ready, so a
    later start can verify ownership and learn the owner pid. Written via a
    ``.tmp`` sibling and ``os.replace`` so a concurrent reader never sees a
    half-written record.

    Args:
        owner_start_time: The owner process's creation time (epoch seconds), the
            anti-pid-reuse witness. ``None`` resolves it from the owner pid, so
            callers normally omit it; a recycled pid later reads a different
            creation time and is no longer mistaken for the live owner.
        qdrant_start_time: The child process's creation-time witness. ``None``
            resolves it from ``qdrant_pid``; an unreadable or legacy zero value
            cannot authorize later automated reaping.

    Returns:
        The path the sidecar was written to.
    """
    if owner_start_time is None:
        owner_start_time = pid_start_time(owner_pid)
    if qdrant_start_time is None:
        qdrant_start_time = pid_start_time(qdrant_pid)
    path = qdrant_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "storage_path": storage_path,
                "version": version,
                "owner_pid": owner_pid,
                "http_port": http_port,
                "qdrant_pid": qdrant_pid,
                "qdrant_start_time": qdrant_start_time,
                "owner_start_time": owner_start_time,
            }
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    logger.debug("wrote qdrant identity sidecar at %s (owner pid %d)", path, owner_pid)
    return path


def verify_attachable(
    probe: QdrantEndpointProbe,
    identity: QdrantIdentity | None,
    *,
    expected_port: int,
    expected_version: str,
    expected_storage: str,
    inspection_timeout: float = 2.0,
) -> tuple[bool, str]:
    """Decide whether a running Qdrant is safe to attach to, with a reason.

    Attach only when every gate passes: ready endpoint, complete owner and child
    process-incarnation witnesses, Qdrant image, process-owned loopback
    listener, expected port, pinned version, and expected storage. Any failure
    returns ``(False, reason)`` so callers fail closed instead of publishing an
    unverifiable attached identity.

    Returns:
        ``(attachable, reason)``.
    """
    if not probe.ready:
        return False, "qdrant on the port is not ready (/readyz did not return 200)"
    if identity is None:
        return False, "no managed identity sidecar; the port holder is not ours"
    if identity.http_port != expected_port:
        return (
            False,
            f"port mismatch: identity records {identity.http_port} != expected "
            f"{expected_port}",
        )
    if identity.version != expected_version:
        return (
            False,
            f"identity version mismatch: recorded {identity.version!r} != managed "
            f"{expected_version!r}",
        )
    if expected_version and probe.version != expected_version:
        # The capability gate is non-optional: an unreadable version (empty) is
        # a gate FAILURE, not a pass - attaching to a server whose version we
        # could not confirm defeats the version check.
        running = probe.version or "<unreadable>"
        return (
            False,
            f"version mismatch or unreadable: running {running!r} != managed "
            f"{expected_version!r}",
        )
    if os.path.normcase(os.path.normpath(identity.storage_path)) != os.path.normcase(
        os.path.normpath(expected_storage)
    ):
        return (
            False,
            f"storage mismatch: managed identity serves {identity.storage_path!r} "
            f"!= expected {expected_storage!r}",
        )
    return _verify_attach_identity_witnesses(
        identity,
        expected_port=expected_port,
        inspection_timeout=inspection_timeout,
    )


def _verify_attach_identity_witnesses(
    identity: QdrantIdentity,
    *,
    expected_port: int,
    inspection_timeout: float,
) -> tuple[bool, str]:
    """Validate the complete live owner/child witness used for attachment."""
    if identity.owner_start_time <= 0.0:
        return False, "managed identity has no owner process-start witness"
    if identity.qdrant_pid <= 0 or identity.qdrant_start_time <= 0.0:
        return False, "managed identity has no complete child process witness"
    deadline = time.monotonic() + max(0.0, inspection_timeout)

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    if not pid_matches_start_time(
        identity.owner_pid,
        identity.owner_start_time,
        timeout=remaining(),
    ):
        return False, "managed owner process incarnation does not match its witness"
    if not pid_matches_start_time(
        identity.qdrant_pid,
        identity.qdrant_start_time,
        timeout=remaining(),
    ):
        return False, "managed child process incarnation does not match its witness"
    if not pid_image_is_qdrant(identity.qdrant_pid, timeout=remaining()):
        return False, "witnessed managed child image is not Qdrant"
    if not pid_listens_on_loopback_port(
        identity.qdrant_pid,
        expected_port,
        timeout=remaining(),
    ):
        return (
            False,
            "witnessed managed child does not own the expected loopback listener",
        )
    return True, "attachable"


def classify_qdrant_state(
    probe: QdrantEndpointProbe,
    identity: QdrantIdentity | None,
    *,
    owner_timeout: float | None = None,
) -> str:
    """Classify the Qdrant port/owner state for the attach/spawn decision.

    Returns one of:

    - ``"absent"``: nothing is listening and no managed owner is recorded -
      safe to spawn.
    - ``"stale_identity"``: an identity is recorded but its owner is dead and
      nothing is listening - the sidecar is stale; safe to spawn after cleanup.
    - ``"managed_orphan"``: something is still listening but the recorded owner
      is dead - a leaked managed child holding the singleton; must be reaped,
      not competed with.
    - ``"managed_running"``: listening with a live recorded owner - the managed
      Qdrant is up; attach (subject to the capability/ownership gate).
    - ``"owner_unverified"``: the recorded owner is live but its process-start
      witness cannot be read - fail closed without attaching, reaping, or
      spawning.
    - ``"foreign"``: listening but no/again-mismatched managed identity - an
      unrelated process owns the port; never spawn a competitor, never attach.
    """
    owner_state = owner_pid_witness_state(identity, timeout=owner_timeout)
    if not probe.listening:
        if identity is not None and owner_state in {"dead", "replaced"}:
            return "stale_identity"
        if identity is not None and owner_state == "unknown":
            return "owner_unverified"
        return "absent"
    if identity is None:
        return "foreign"
    if owner_state == "live":
        return "managed_running"
    if owner_state == "unknown":
        return "owner_unverified"
    return "managed_orphan"


def decide_qdrant_action(
    probe: QdrantEndpointProbe,
    identity: QdrantIdentity | None,
    *,
    expected_port: int,
    expected_version: str,
    expected_storage: str,
) -> tuple[str, str]:
    """Decide what to do about the Qdrant port, with a reason.

    Pure policy over the classified state and the attach gate. Returns one of:

    - ``("attach", reason)``: a healthy, owned, capable managed server is up -
      reuse it, do not spawn.
    - ``("refuse", reason)``: the port is held by a foreign process, the owner
      witness cannot be verified, or a managed server fails the attach gate
      (unhealthy / wrong version / wrong storage) - never spawn a competitor on
      the shared single-writer storage; fail fast with the reason.
    - ``("reap_then_spawn", reason)``: a managed orphan (recorded owner dead) is
      holding the port - reap it, then spawn.
    - ``("spawn", reason)``: nothing usable is there (clean slate or a stale
      identity from a dead owner) - spawn a fresh child.
    """
    state = classify_qdrant_state(probe, identity)
    if state == "managed_running":
        ok, reason = verify_attachable(
            probe,
            identity,
            expected_port=expected_port,
            expected_version=expected_version,
            expected_storage=expected_storage,
        )
        return ("attach", reason) if ok else ("refuse", reason)
    if state == "foreign":
        return (
            "refuse",
            "port held by a non-managed process (listening, no managed "
            f"identity); refusing to spawn a competitor on {expected_storage!r}",
        )
    if state == "owner_unverified":
        return (
            "refuse",
            "recorded qdrant owner is live but its process-start witness could "
            "not be read; refusing to attach, reap, or spawn until ownership "
            "can be verified",
        )
    if state == "managed_orphan":
        return (
            "reap_then_spawn",
            "a managed qdrant orphan (recorded owner is dead) is holding the "
            "port; it must be reaped before spawning",
        )
    return ("spawn", state)


def _resolve_env_binary() -> ResolvedBinary | None:
    raw = get_config().qdrant_binary
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return ResolvedBinary(path=candidate, source="env")
    logger.debug(
        "%s points at %s which does not exist; ignoring",
        EnvVar.QDRANT_BINARY.value,
        candidate,
    )
    return None


def _resolve_provisioned(version: str) -> ResolvedBinary | None:
    version_dir = qdrant_bin_dir(version)
    binary = version_dir / binary_filename()
    if not binary.is_file():
        return None
    manifest = read_manifest(version_dir)
    if manifest is None:
        logger.debug(
            "provisioned qdrant binary at %s has no manifest; ignoring",
            binary,
        )
        return None
    recorded_version = str(manifest.get("version", ""))
    if recorded_version != version:
        logger.debug(
            "provisioned qdrant manifest version %s != requested %s; ignoring",
            recorded_version,
            version,
        )
        return None
    return ResolvedBinary(
        path=binary,
        source="provisioned",
        version=recorded_version,
        sha256=str(manifest.get("binary_sha256", "")),
    )


def has_provisioned_binary(version: str = QDRANT_SERVER_VERSION) -> bool:
    """Return whether a verified provisioned binary exists for *version*.

    Lets callers detect when an unpinned env/PATH binary would shadow a
    properly provisioned (pinned, digest-checked) install.
    """
    return _resolve_provisioned(version) is not None


def resolve_binary(
    version: str = QDRANT_SERVER_VERSION,
) -> ResolvedBinary | None:
    """Resolve the active qdrant binary, or ``None`` when absent.

    Resolution order: operator env var, the managed provisioned dir
    for *version*, then ``PATH``.

    Args:
        version: The provisioned version to look for in the managed
            dir (the pinned version by default).

    Returns:
        The resolved binary with its origin, or ``None`` when no
        candidate exists.
    """
    resolved = _resolve_env_binary()
    if resolved is not None:
        return resolved

    resolved = _resolve_provisioned(version)
    if resolved is not None:
        return resolved

    on_path = shutil.which("qdrant")
    if on_path:
        return ResolvedBinary(path=Path(on_path), source="path")
    return None
