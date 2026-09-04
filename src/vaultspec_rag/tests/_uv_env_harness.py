"""Stage hostile uv provisioning conditions without touching a live install.

Everything here is real: a real uv binary, real environments under ``tmp_path``,
real wheels served over a real loopback socket, real holder processes, and the
receipt uv itself writes. What makes it safe is redirection rather than
simulation - ``UV_TOOL_DIR``, ``UV_TOOL_BIN_DIR`` and ``UV_CACHE_DIR`` all point
inside the test's own temporary tree, so no operator installation, shim
directory or shared cache is reachable from a test using this harness.

Two details are load-bearing and easy to get wrong:

- **Wheels are served over loopback HTTP, never ``file://``.** uv records a
  ``file://`` requirement in the tool receipt under a ``path`` key and an
  ``http(s)`` one under ``url``. Production reads ``url``, so a ``file://``
  stand-in would let every receipt-verification test pass without ever
  entering the branch that runs in production.
- **A tool package must expose a console script.** ``uv tool install`` refuses
  a distribution with no entry point, so the stand-in built here declares one.

A receipt always contains a ``path`` key, because every recorded entry point
carries an ``install-path``. A test asserting on how a requirement was recorded
must therefore match the requirement's own line rather than the presence of
``path`` anywhere in the file.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

__all__ = [
    "UvSandbox",
    "WheelTags",
    "build_wheel",
    "hold_environment",
    "index_arguments",
    "installed_distributions",
    "receipt_text",
    "sandbox_from",
    "serve_wheels",
    "wheel_filename",
]


@dataclass(frozen=True, slots=True)
class UvSandbox:
    """A uv installation whose every mutable directory is inside a temp tree."""

    tool_dir: Path
    bin_dir: Path
    cache_dir: Path

    @property
    def env(self) -> dict[str, str]:
        """The environment that redirects uv away from the real installation."""
        return os.environ | {
            "UV_TOOL_DIR": str(self.tool_dir),
            "UV_TOOL_BIN_DIR": str(self.bin_dir),
            "UV_CACHE_DIR": str(self.cache_dir),
        }

    def run(
        self, *args: str, timeout: float = 300.0
    ) -> subprocess.CompletedProcess[str]:
        """Run uv inside the sandbox and return its completed process."""
        return subprocess.run(
            ["uv", *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def tool_root(self, name: str) -> Path:
        """The environment directory uv builds for tool *name*."""
        return self.tool_dir / name

    def receipt(self, name: str) -> Path:
        """The receipt uv writes for tool *name*."""
        return self.tool_root(name) / "uv-receipt.toml"

    def site_packages(self, name: str) -> Path:
        """The installed-distribution directory for tool *name*."""
        root = self.tool_root(name)
        windows = root / "Lib" / "site-packages"
        if windows.exists():
            return windows
        matches = sorted((root / "lib").glob("python*/site-packages"))
        return matches[0] if matches else windows


@dataclass(frozen=True, slots=True)
class WheelTags:
    """A wheel's compatibility tags.

    Defaults describe a pure-Python wheel that installs under any interpreter.
    Naming tags an interpreter cannot satisfy is how the ABI-mismatch condition
    is staged, so the three travel together rather than as loose arguments.
    """

    python: str = "py3"
    abi: str = "none"
    platform: str = "any"

    @property
    def suffix(self) -> str:
        """The tag triple as it appears in a wheel filename."""
        return f"{self.python}-{self.abi}-{self.platform}"


def wheel_filename(name: str, version: str, tags: WheelTags | None = None) -> str:
    """Render a wheel filename, including a deliberately wrong tag when asked."""
    return f"{name}-{version}-{(tags or WheelTags()).suffix}.whl"


def _record_line(archive_name: str, payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
    stripped = digest.rstrip(b"=").decode("ascii")
    return f"{archive_name},sha256={stripped},{len(payload)}"


def build_wheel(
    destination: Path,
    *,
    name: str,
    version: str,
    console_script: bool = True,
    tags: WheelTags | None = None,
) -> Path:
    """Build a minimal but real wheel into *destination* and return its path.

    The module body is trivial on purpose: these distributions stand in for
    torch and for the tool being installed, and nothing about the proofs
    depends on what they do once imported - only on uv resolving, fetching,
    installing and recording them the way it does the real ones.
    """
    resolved_tags = tags or WheelTags()
    destination.mkdir(parents=True, exist_ok=True)
    module = name.replace("-", "_")
    dist_info = f"{module}-{version}.dist-info"
    path = destination / wheel_filename(module, version, resolved_tags)

    members: dict[str, bytes] = {
        f"{module}/__init__.py": f'__version__ = "{version}"\n'.encode(),
        f"{module}/__main__.py": b"def main() -> int:\n    return 0\n",
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
            "Summary: provisioning test stand-in\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: vaultspec-rag-test-harness\n"
            "Root-Is-Purelib: true\n"
            f"Tag: {resolved_tags.suffix}\n"
        ).encode(),
    }
    if console_script:
        members[f"{dist_info}/entry_points.txt"] = (
            f"[console_scripts]\n{module} = {module}.__main__:main\n"
        ).encode()

    record = "\n".join(
        _record_line(archive_name, payload) for archive_name, payload in members.items()
    )
    record += f"\n{dist_info}/RECORD,,\n"
    members[f"{dist_info}/RECORD"] = record.encode()

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for archive_name, payload in members.items():
            archive.writestr(archive_name, payload)
    return path


@contextlib.contextmanager
def serve_wheels(directory: Path) -> Iterator[str]:
    """Serve *directory* over loopback HTTP, yielding its base URL.

    Loopback rather than ``file://`` because the receipt records the two
    differently and only this form matches what production reads back.
    """
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="vaultspec-wheel-index"
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


# Idles long enough to outlive a test's assertions, short enough that an
# abandoned holder cannot keep a temporary tree locked for long.
_IDLE = "import time; time.sleep(90)"


@contextlib.contextmanager
def hold_environment(
    root: Path, *, by_image: bool = True, timeout: float = 20.0
) -> Iterator[subprocess.Popen[bytes]]:
    """Hold *root* with a real process, and release it on the way out.

    ``by_image`` runs the environment's own interpreter; otherwise a foreign
    interpreter is parked with its working directory inside the tree. Both
    block a Windows directory removal, and a caller proving the destructive
    failure needs to choose which relation it is demonstrating.
    """
    if by_image:
        interpreter = root / "Scripts" / "python.exe"
        if not interpreter.exists():
            interpreter = root / "bin" / "python"
        command: Sequence[str] = [str(interpreter), "-c", _IDLE]
        cwd: str | None = None
    else:
        command = [sys.executable, "-c", _IDLE]
        cwd = str(root)

    process = subprocess.Popen(command, cwd=cwd)
    try:
        _await_hold(root, process.pid, timeout=timeout)
        yield process
    finally:
        process.terminate()
        process.wait(timeout=30)


def _await_hold(root: Path, pid: int, *, timeout: float) -> None:
    """Block until the holder is visible, so no caller races a starting child."""
    from .._process_probe import environment_holders

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(holder.pid == pid for holder in environment_holders(root).holders):
            return
        time.sleep(0.1)
    raise TimeoutError(f"holder pid {pid} never took hold of {root}")


def sandbox_from(tmp_path: Path) -> UvSandbox:
    """Build a sandbox rooted under *tmp_path*."""
    sandbox = UvSandbox(
        tool_dir=tmp_path / "uv-tools",
        bin_dir=tmp_path / "uv-bin",
        cache_dir=tmp_path / "uv-cache",
    )
    for directory in (sandbox.tool_dir, sandbox.bin_dir, sandbox.cache_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return sandbox


def installed_distributions(sandbox: UvSandbox, name: str) -> set[str]:
    """The distribution names installed in tool *name*'s environment."""
    site = sandbox.site_packages(name)
    if not site.exists():
        return set()
    return {entry.name.split("-", 1)[0] for entry in site.glob("*.dist-info")}


def receipt_text(sandbox: UvSandbox, name: str) -> str:
    """The raw receipt for tool *name*, or an empty string when absent."""
    receipt = sandbox.receipt(name)
    return receipt.read_text(encoding="utf-8") if receipt.exists() else ""


def index_arguments(base_url: str) -> tuple[str, ...]:
    """The uv arguments pointing resolution at the loopback wheel index."""
    return ("--find-links", base_url, "--no-index")
