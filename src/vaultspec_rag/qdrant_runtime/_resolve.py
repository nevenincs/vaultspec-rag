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
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
    "pid_alive",
    "pid_image_is_qdrant",
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
            version = str(payload.get("version", ""))
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
    """

    storage_path: str
    version: str
    owner_pid: int
    http_port: int
    qdrant_pid: int = 0


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
    try:
        return QdrantIdentity(
            storage_path=str(data["storage_path"]),
            version=str(data["version"]),
            owner_pid=int(data["owner_pid"]),
            http_port=int(data["http_port"]),
            qdrant_pid=int(data.get("qdrant_pid", 0)),
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


def reap_qdrant_orphan(pid: int, *, wait_seconds: float = 5.0) -> bool:
    """Terminate an orphaned managed-Qdrant process by pid; report success.

    Used only after the orphan has been positively classified (the recorded
    owner is dead but the child still holds the port). Terminates gracefully,
    escalating to a hard kill, then verifies the pid is gone. A non-positive or
    already-dead pid is a no-op that reports success.

    Returns:
        ``True`` when the pid is no longer alive after the attempt.
    """
    import time as _time

    if pid <= 0:
        return False
    if not pid_alive(pid):
        return True
    if sys.platform == "win32":
        import subprocess

        subprocess.run(  # fixed argv, no shell, trusted pid
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        deadline = _time.monotonic() + wait_seconds
        while _time.monotonic() < deadline and pid_alive(pid):
            _time.sleep(0.1)
        if pid_alive(pid):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    deadline = _time.monotonic() + wait_seconds
    while _time.monotonic() < deadline and pid_alive(pid):
        _time.sleep(0.1)
    return not pid_alive(pid)


def pid_image_is_qdrant(pid: int) -> bool:
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

        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "qdrant" in result.stdout.lower()
    for proc_file in ("comm", "cmdline"):
        try:
            text = Path(f"/proc/{pid}/{proc_file}").read_text(encoding="utf-8")
        except OSError:
            continue
        if "qdrant" in text.lower():
            return True
    return False


def write_qdrant_identity(
    *,
    storage_path: str,
    version: str,
    owner_pid: int,
    http_port: int,
    qdrant_pid: int = 0,
) -> Path:
    """Atomically write the managed-Qdrant identity sidecar.

    Called by the supervisor once the managed server is confirmed ready, so a
    later start can verify ownership and learn the owner pid. Written via a
    ``.tmp`` sibling and ``os.replace`` so a concurrent reader never sees a
    half-written record.

    Returns:
        The path the sidecar was written to.
    """
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
    expected_version: str,
    expected_storage: str,
) -> tuple[bool, str]:
    """Decide whether a running Qdrant is safe to attach to, with a reason.

    Attach only when every gate passes: the server is *healthy* (``/readyz``
    ready), it is *owned* (a managed identity sidecar exists), and it is
    *capable* - the live version matches the managed version and it is serving
    the expected storage path. Any failure returns ``(False, reason)`` so the
    caller refuses fast with a named cause rather than attaching blindly or
    spawning a competitor.

    Returns:
        ``(attachable, reason)``.
    """
    if not probe.ready:
        return False, "qdrant on the port is not ready (/readyz did not return 200)"
    if identity is None:
        return False, "no managed identity sidecar; the port holder is not ours"
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
    return True, "attachable"


def classify_qdrant_state(
    probe: QdrantEndpointProbe,
    identity: QdrantIdentity | None,
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
    - ``"foreign"``: listening but no/again-mismatched managed identity - an
      unrelated process owns the port; never spawn a competitor, never attach.
    """
    owner_alive = identity is not None and pid_alive(identity.owner_pid)
    if not probe.listening:
        if identity is not None and not owner_alive:
            return "stale_identity"
        return "absent"
    if identity is None:
        return "foreign"
    if owner_alive:
        return "managed_running"
    return "managed_orphan"


def decide_qdrant_action(
    probe: QdrantEndpointProbe,
    identity: QdrantIdentity | None,
    *,
    expected_version: str,
    expected_storage: str,
) -> tuple[str, str]:
    """Decide what to do about the Qdrant port, with a reason.

    Pure policy over the classified state and the attach gate. Returns one of:

    - ``("attach", reason)``: a healthy, owned, capable managed server is up -
      reuse it, do not spawn.
    - ``("refuse", reason)``: the port is held by a foreign process, or by a
      managed server that fails the attach gate (unhealthy / wrong version /
      wrong storage) - never spawn a competitor on the shared single-writer
      storage; fail fast with the reason.
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
