"""Shared subprocess service helpers for integration tests.

Underscore prefix keeps pytest from collecting this as a test module.
Extracted from ``test_service_lifecycle.py`` so the eviction and
log-rotation tests in ``test_service_eviction.py`` can reuse the
subprocess environment setup without a sibling-import hack.
"""

from __future__ import annotations

import os
import shutil
import socket
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config,
)

from ...cli import _health_probe, _is_pid_alive
from ...config import reset_config as reset_rag_config

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

__all__ = [
    "_get_ephemeral_port",
    "_mirror_managed_qdrant_binary",
    "_poll_health",
    "_resolve_host_provisioned_qdrant",
    "_service_env",
    "_wait_for_exit",
]


def _resolve_host_provisioned_qdrant() -> tuple[Path, Path] | None:
    """Resolve the host's provisioned qdrant binary and manifest, if any.

    Read against the host's real config (call this BEFORE any status-dir
    override), so the source is the genuine managed install under
    ``~/.vaultspec-rag/bin/qdrant/{version}/``. Returns ``(binary, manifest)`` or
    ``None`` when no provisioned (pinned, manifest-backed) install exists.
    """
    from ...qdrant_runtime._constants import MANIFEST_FILENAME, QDRANT_SERVER_VERSION
    from ...qdrant_runtime._resolve import resolve_binary

    resolved = resolve_binary(QDRANT_SERVER_VERSION)
    if resolved is None or resolved.source != "provisioned":
        # Only a provisioned (pinned, manifest-backed) binary is mirrorable with
        # its verification intact; an env/PATH binary carries no manifest.
        return None
    manifest = resolved.path.parent / MANIFEST_FILENAME
    if not manifest.is_file():
        return None
    return resolved.path, manifest


def _mirror_managed_qdrant_binary(status_dir: Path, source: tuple[Path, Path]) -> None:
    """Copy a real provisioned qdrant binary into the isolated *status_dir*.

    The managed binary resolves under ``{status_dir}/bin/qdrant/{version}/``, so
    an isolated test status dir has none and a server-mode daemon fast-fails on
    the binary guard before the attach/lock path it means to exercise. Mirror the
    host's real provisioned install (binary plus its manifest, supplied by
    :func:`_resolve_host_provisioned_qdrant`) into the isolated dir.

    The pinned-digest contract is preserved: the manifest is copied verbatim, so
    the supervisor's pre-execution SHA256 re-hash still runs against the real
    committed digest - the verification boundary is never weakened.
    """
    from ...qdrant_runtime._constants import MANIFEST_FILENAME, QDRANT_SERVER_VERSION
    from ...qdrant_runtime._resolve import binary_filename

    binary_src, manifest_src = source
    dest_dir = status_dir / "bin" / "qdrant" / QDRANT_SERVER_VERSION
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary_src, dest_dir / binary_filename())
    shutil.copy2(manifest_src, dest_dir / MANIFEST_FILENAME)


def _get_ephemeral_port() -> int:
    """Bind to port 0 to get an OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_ephemeral_qdrant_port() -> int:
    """Return a free port whose grpc sibling (port-1) is also free.

    The supervisor derives the qdrant grpc port as ``http_port - 1``, so an
    isolated qdrant needs both ports free. Probe an OS-assigned port and confirm
    its predecessor binds too; retry a bounded number of times before falling
    back to whatever the OS assigned.
    """
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            http_port = int(s.getsockname()[1])
        if http_port <= 1:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as grpc:
                grpc.bind(("127.0.0.1", http_port - 1))
        except OSError:
            continue
        return http_port
    return _get_ephemeral_port()


def _poll_health(port: int, timeout: float = 90.0) -> dict[str, Any]:
    """Poll ``_health_probe`` with exponential backoff until ready."""
    delay = 0.5
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = _health_probe(port)
        if health is not None and health.get("status") == "ready":
            return health
        time.sleep(delay)
        delay = min(delay * 2, 5.0)
    msg = f"Service on port {port} not ready after {timeout:.0f}s"
    raise TimeoutError(msg)


def _wait_for_exit(pid: int, timeout: float = 15.0) -> bool:
    """Wait for a process to exit.  Returns True if exited within timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.3)
    return False


@contextmanager
def _service_env(
    tmp_path: Path,
    env_overrides: Mapping[str, str] | None = None,
) -> Generator[None]:
    """Isolate service state files to *tmp_path*.

    Sets ``VAULTSPEC_RAG_STATUS_DIR`` (and any additional
    *env_overrides* the caller provides) so the spawned subprocess
    and all CLI helpers write to the temp directory.  Resets config
    singletons on entry and exit and restores the previous
    environment on teardown.

    If the host has a provisioned managed qdrant binary, it is mirrored (with
    its manifest) into the isolated status dir so a server-mode daemon resolves
    a binary - the pinned-digest verification still runs against the real
    committed digest. Without a host install the mirror is skipped and the
    daemon falls back to its normal local-only path.
    """
    # Resolve the host's provisioned binary BEFORE the status-dir override, so
    # the source is the real managed install, not the (empty) isolated dir.
    host_qdrant = _resolve_host_provisioned_qdrant()

    env_key = "VAULTSPEC_RAG_STATUS_DIR"
    saved: dict[str, str | None] = {env_key: os.environ.get(env_key)}
    os.environ[env_key] = str(tmp_path)

    # Isolate the machine-global Qdrant storage too: the machine-scoped service
    # lock is co-located with it, so without this a test daemon would acquire
    # the real machine lock and collide with a real service or a sibling test.
    storage_key = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
    if storage_key not in (env_overrides or {}):
        saved[storage_key] = os.environ.get(storage_key)
        os.environ[storage_key] = str(tmp_path / "qdrant-storage")

    # Isolate the Qdrant port off the shared machine default (8765): once the
    # binary is mirrored, a server-mode test daemon spawns a real Qdrant child,
    # and the default port would collide with the host's real Qdrant or a
    # sibling test's. An ephemeral http port (with grpc one below it) keeps each
    # test's Qdrant on its own loopback ports.
    qdrant_port_key = "VAULTSPEC_RAG_QDRANT_PORT"
    if qdrant_port_key not in (env_overrides or {}):
        saved[qdrant_port_key] = os.environ.get(qdrant_port_key)
        os.environ[qdrant_port_key] = str(_get_ephemeral_qdrant_port())

    if env_overrides:
        for k, v in env_overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v

    # Mirror the host's provisioned binary into the isolated status dir so the
    # managed-binary guard resolves it and a server-mode daemon exercises the
    # live attach/lock path instead of fast-failing on a missing binary.
    if host_qdrant is not None:
        _mirror_managed_qdrant_binary(tmp_path, host_qdrant)

    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()
    try:
        yield
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        reset_config()  # pyright: ignore[reportMissingTypeStubs]
        reset_rag_config()
