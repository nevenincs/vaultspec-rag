"""Execution containment for project-supplied preprocess hooks.

The RAG server runs hooks for clients that never see an interactive prompt, so
consent cannot be the security boundary - containment is. This module defines
the backend-agnostic contract every server-side hook launch flows through: the
source is staged into a per-run scratch directory, the child runs with a
curated environment (no inherited secrets) and that scratch dir as its only
writable cwd, and an OS-level backend confines what the child can read, write,
and reach on the network. The backends live in the platform modules
(``_hook_sandbox_windows`` / ``_hook_sandbox_posix``); this module owns the
staging, the env curation, the capability probe, and the fail-closed policy.

Fail-closed is the load-bearing rule: in server mode, if no working sandbox
backend resolves, hooks are REFUSED, never run unconfined - a warning-and-run
fallback would silently reopen the untrusted-repo RCE on exactly the hosts that
cannot be contained. Local / in-process CLI mode is the caller's own machine and
runs sandboxed-if-available, else with a warning.

The module is stdlib-only so it stays importable from the CPU-only spawn chunk
worker without loading torch (``index-workers-stay-cpu-only``).
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import IO, TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "HookSandbox",
    "SandboxHandle",
    "SandboxUnavailableError",
    "curated_child_env",
    "resolve_hook_sandbox",
    "stage_source",
]

#: The child gets a minimal, secret-free environment built from an ALLOW-list:
#: only the names below are forwarded, so no credential, token, or
#: ``VAULTSPEC_RAG_*`` knob can reach an attacker-authored hook regardless of
#: what the daemon's environment holds.
#:
#: The minimal variables a child interpreter legitimately needs to start.
#: Windows AppContainer initialization and the CRT resolve several of these path
#: variables during startup (a missing one fails CreateProcessW with
#: ERROR_ENVVAR_NOT_FOUND, 203); they carry paths, not credentials, and the
#: sandbox still denies the child actual read access to what they point at, so
#: forwarding the strings leaks nothing exploitable. Everything else - every
#: token and every ``VAULTSPEC_RAG_*`` knob - is dropped. Matched
#: case-insensitively.
_ENV_ALLOW_NAMES: frozenset[str] = frozenset(
    name.upper()
    for name in {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "TEMP",
        "TMP",
        "PATHEXT",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)


class SandboxUnavailableError(RuntimeError):
    """Raised when server mode requires a sandbox but none is available.

    The runner maps this onto a hard refusal to run the hook (per-file skip
    with a loud, actionable reason), never a silent unconfined run.
    """


@runtime_checkable
class SandboxHandle(Protocol):
    """A launched, contained hook child - the subset of ``Popen`` the runner uses.

    A backend returns one of these from :meth:`HookSandbox.launch`. The runner
    drains ``stdout``/``stderr`` on threads, then ``wait``s with a timeout and
    ``kill``s on expiry, exactly as it did for a bare ``Popen`` - so a backend
    that simply wraps ``subprocess.Popen`` satisfies this by construction.
    """

    stdout: IO[bytes] | None
    stderr: IO[bytes] | None
    pid: int
    returncode: int | None

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class HookSandbox(Protocol):
    """A containment backend that launches one hook child.

    ``launch`` receives the fully-built argv, the staged scratch directory (the
    child's only writable location and the location of the staged source), the
    curated environment, and the read-only paths the child legitimately needs
    (the staged dir always; system library dirs when ``needs_system_libs``).
    The backend confines the child accordingly and returns a
    :class:`SandboxHandle`. ``cleanup`` releases any per-launch OS resources
    (job handles, container profiles) and is always called after the child is
    reaped.
    """

    name: str

    def launch(
        self,
        argv: Sequence[str],
        *,
        scratch_dir: pathlib.Path,
        env: dict[str, str],
        read_paths: Sequence[pathlib.Path],
    ) -> SandboxHandle: ...

    def cleanup(self, handle: SandboxHandle) -> None: ...


def curated_child_env() -> dict[str, str]:
    """Return a minimal, secret-free environment for a hook child.

    Drops every credential-bearing and ``VAULTSPEC_RAG_*`` variable (so the
    child cannot read the daemon's tokens or be redirected at managed state) and
    keeps only the small allow-list a child interpreter needs to start. This is
    mandatory hardening under every backend, including the unsandboxed escape
    hatch, and it is what closes the env-inheritance secret-exfiltration threat.
    """
    curated: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if upper in _ENV_ALLOW_NAMES:
            curated[name] = value
    return curated


def stage_source(source_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Copy the source into a fresh scratch dir; return ``(scratch_dir, staged)``.

    Staging collapses the child's filesystem needs to a single directory: it
    reads the copy, writes nothing outside, and the OS backend grants read of
    only this dir. The caller owns ``scratch_dir`` and must remove it (the runner
    does so in a ``finally`` after the hook completes).
    """
    scratch_dir = pathlib.Path(tempfile.mkdtemp(prefix="vsrag-hook-"))
    staged = scratch_dir / source_path.name
    shutil.copyfile(source_path, staged)
    return scratch_dir, staged


def resolve_hook_sandbox(
    *, server_mode: bool, unsandboxed: bool
) -> HookSandbox | None:
    """Resolve the containment backend for this host, or apply the fail policy.

    Returns a working :class:`HookSandbox`, or ``None`` when the caller should
    run the child directly (unsandboxed). The policy:

    - ``unsandboxed`` (the operator set ``VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED``):
      return ``None`` and let the runner spawn directly - but still under the
      curated env and staging. Loudly logged; the operator opted in.
    - server mode, sandbox available: return it.
    - server mode, no backend: raise :class:`SandboxUnavailableError` - hooks
      are refused, never run unconfined.
    - local / in-process mode, no backend: return ``None`` with a warning; the
      caller's own machine is the caller's prerogative.

    Args:
        server_mode: True when the resident service is executing the hook.
        unsandboxed: True when the operator opted out of sandboxing.

    Raises:
        SandboxUnavailableError: server mode with no available backend.
    """
    if unsandboxed:
        logger.warning(
            "VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED is set: preprocess hooks run "
            "WITHOUT OS containment. Any project command runs with this "
            "process's privileges. Use only on hosts whose repositories you "
            "fully trust."
        )
        return None

    backend = _probe_backend()
    if backend is not None:
        return backend

    if server_mode:
        message = (
            "No preprocess-hook sandbox backend is available on this host, so "
            "the service refuses to run project hooks (fail-closed). Install a "
            "supported sandbox (Windows 8+/AppContainer, bubblewrap or a "
            "Landlock kernel on Linux, macOS sandbox-exec) or set "
            "VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1 to run hooks unconfined at "
            "your own risk."
        )
        raise SandboxUnavailableError(message)

    logger.warning(
        "No preprocess-hook sandbox backend available; running hooks unconfined "
        "in local mode. Server mode would refuse these."
    )
    return None


def _probe_backend() -> HookSandbox | None:
    """Return the first working sandbox backend for this platform, or None.

    Imports are function-local and platform-guarded so the platform modules
    (which touch ``ctypes.windll`` / POSIX-only APIs) are never imported on the
    wrong OS and the probe itself stays cheap and torch-free.
    """
    try:
        if sys.platform == "win32":
            from ._hook_sandbox_windows import probe_appcontainer

            return probe_appcontainer()
        from ._hook_sandbox_posix import probe_posix_sandbox

        return probe_posix_sandbox()
    except Exception:
        logger.warning(
            "preprocess-hook sandbox probe raised; treating as unavailable",
            exc_info=True,
        )
        return None


def default_popen_handle(
    argv: Sequence[str],
    *,
    cwd: pathlib.Path,
    env: dict[str, str],
    creationflags: int = 0,
) -> subprocess.Popen[bytes]:
    """Launch an uncontained child with curated env and scratch cwd.

    Shared by the unsandboxed path and by backends that layer a Job Object over
    an otherwise-normal ``Popen``. Pipes are captured; the caller drains them.
    """
    return subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        creationflags=creationflags,
    )
