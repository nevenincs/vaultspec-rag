"""POSIX containment backends for preprocess hooks (Linux / macOS).

Two backends, both wrapping the hook argv in an OS sandbox launcher and
returning a plain :class:`subprocess.Popen` - which satisfies the
:class:`~._hook_sandbox.SandboxHandle` protocol structurally (``stdout`` /
``stderr`` / ``pid`` / ``returncode`` / ``wait`` / ``kill``), so the runner's
drain-and-timeout logic is unchanged from the bare-``Popen`` path.

Linux uses **bubblewrap** (``bwrap``): the child runs in fresh user, mount, and
network namespaces, sees only read-only binds of the interpreter/project trees
plus a read-write bind of the staged scratch dir, and has no network
(``--unshare-net``). This is the supported Linux backend. A Landlock+seccomp
fallback (for hosts without bubblewrap) is a documented gap: ``probe`` returns
``None`` when ``bwrap`` is absent, so server mode fail-closes and refuses hooks
rather than running them unconfined - the safe degradation. Implementing
Landlock via ``ctypes`` is deferred.

macOS uses **sandbox-exec** with a deny-default Seatbelt profile that allows
process fork/exec, read of the granted paths, read+write of the scratch dir, and
denies all network. ``sandbox-exec`` is deprecated by Apple but remains the only
dependency-free, unelevated per-process sandbox on macOS.

The module is stdlib-only (``shutil`` / ``subprocess``) so it stays importable
from the CPU-only spawn chunk worker without loading torch
(``index-workers-stay-cpu-only``).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from ._hook_sandbox import HookSandbox, SandboxHandle

logger = logging.getLogger(__name__)


def _existing_realpaths(paths: Sequence[pathlib.Path]) -> list[str]:
    """Return the deduplicated, existing real paths from ``paths``.

    Sandbox launchers reject a bind/grant of a non-existent source, and binding
    the same tree twice is wasteful (bwrap) or an error risk; canonicalising via
    ``realpath`` also collapses ``sys.prefix``/``sys.base_prefix`` when a
    non-venv interpreter makes them equal.
    """
    seen: dict[str, None] = {}
    for path in paths:
        real = os.path.realpath(path)
        if os.path.exists(real):
            seen.setdefault(real, None)
    return list(seen)


class _PopenBackend:
    """Shared no-op ``cleanup`` for backends whose handle is a plain ``Popen``.

    A ``Popen`` owns its own OS handles and is reaped by the runner's
    ``wait``/``kill``; there are no per-launch container profiles or job objects
    to release (unlike the Windows AppContainer backend), so cleanup is a no-op.
    """

    def cleanup(self, handle: SandboxHandle) -> None:
        del handle


class BubblewrapSandbox(_PopenBackend):
    """Linux bubblewrap containment backend (see module docstring)."""

    name = "linux-bubblewrap"

    def __init__(self, bwrap: str) -> None:
        self._bwrap = bwrap

    def launch(
        self,
        argv: Sequence[str],
        *,
        scratch_dir: pathlib.Path,
        env: dict[str, str],
        read_paths: Sequence[pathlib.Path],
    ) -> SandboxHandle:
        scratch = os.path.realpath(scratch_dir)
        wrapped: list[str] = [
            self._bwrap,
            "--unshare-net",
            "--die-with-parent",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
        ]
        for real in _existing_realpaths(read_paths):
            if real == scratch:
                continue
            wrapped += ["--ro-bind", real, real]
        wrapped += [
            "--bind",
            scratch,
            scratch,
            "--chdir",
            scratch,
            "--",
            *argv,
        ]
        return subprocess.Popen(
            wrapped,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )


class SeatbeltSandbox(_PopenBackend):
    """macOS sandbox-exec containment backend (see module docstring)."""

    name = "macos-seatbelt"

    def __init__(self, sandbox_exec: str) -> None:
        self._sandbox_exec = sandbox_exec

    @staticmethod
    def _quote(path: str) -> str:
        """Escape a path for a seatbelt ``(subpath "...")`` string literal.

        Backslashes and double quotes are the only characters special inside a
        seatbelt string, so escaping them prevents a path containing ``"`` or
        ``)`` from breaking out of the literal and injecting profile clauses.
        """
        return path.replace("\\", "\\\\").replace('"', '\\"')

    def _profile(
        self, scratch: str, read_paths: Sequence[pathlib.Path]
    ) -> str:
        clauses = [
            "(version 1)",
            "(deny default)",
            "(allow process-fork)",
            "(allow process-exec)",
            f'(allow file-read* file-write* (subpath "{self._quote(scratch)}"))',
        ]
        for real in _existing_realpaths(read_paths):
            if real == scratch:
                continue
            clauses.append(f'(allow file-read* (subpath "{self._quote(real)}"))')
        clauses.append("(deny network*)")
        return "".join(clauses)

    def launch(
        self,
        argv: Sequence[str],
        *,
        scratch_dir: pathlib.Path,
        env: dict[str, str],
        read_paths: Sequence[pathlib.Path],
    ) -> SandboxHandle:
        scratch = os.path.realpath(scratch_dir)
        profile = self._profile(scratch, read_paths)
        wrapped = [self._sandbox_exec, "-p", profile, *argv]
        return subprocess.Popen(
            wrapped,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=scratch,
            env=env,
        )


def probe_posix_sandbox() -> HookSandbox | None:
    """Return the working POSIX sandbox backend for this host, or ``None``.

    Linux: a :class:`BubblewrapSandbox` when ``bwrap`` is on ``PATH``, else
    ``None`` (the Landlock fallback is a documented gap; server mode then
    fail-closes). macOS: a :class:`SeatbeltSandbox` when ``sandbox-exec`` is on
    ``PATH``, else ``None``. Any other platform returns ``None``.
    """
    if sys.platform.startswith("linux"):
        bwrap = shutil.which("bwrap") or shutil.which("bubblewrap")
        if bwrap is not None:
            return BubblewrapSandbox(bwrap)
        logger.warning(
            "bubblewrap (bwrap) is not on PATH; no Linux hook-sandbox backend "
            "available (Landlock fallback is not implemented)."
        )
        return None
    if sys.platform == "darwin":
        sandbox_exec = shutil.which("sandbox-exec")
        if sandbox_exec is not None:
            return SeatbeltSandbox(sandbox_exec)
        logger.warning("sandbox-exec is not on PATH; no macOS hook-sandbox backend.")
        return None
    return None
