"""Shared subprocess service helpers for integration tests.

Underscore prefix keeps pytest from collecting this as a test module.
Extracted from ``test_service_lifecycle.py`` so the eviction and
log-rotation tests in ``test_service_eviction.py`` can reuse the
subprocess environment setup without a sibling-import hack.
"""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from vaultspec_core.config import reset_config

from vaultspec_rag.cli import _health_probe, _is_pid_alive
from vaultspec_rag.config import reset_config as reset_rag_config

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = [
    "_get_ephemeral_port",
    "_poll_health",
    "_service_env",
    "_wait_for_exit",
]


def _get_ephemeral_port() -> int:
    """Bind to port 0 to get an OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
) -> Iterator[None]:
    """Isolate service state files to *tmp_path*.

    Sets ``VAULTSPEC_RAG_STATUS_DIR`` (and any additional
    *env_overrides* the caller provides) so the spawned subprocess
    and all CLI helpers write to the temp directory.  Resets config
    singletons on entry and exit and restores the previous
    environment on teardown.
    """
    env_key = "VAULTSPEC_RAG_STATUS_DIR"
    saved: dict[str, str | None] = {env_key: os.environ.get(env_key)}
    os.environ[env_key] = str(tmp_path)

    if env_overrides:
        for k, v in env_overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v

    reset_config()
    reset_rag_config()
    try:
        yield
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        reset_config()
        reset_rag_config()
