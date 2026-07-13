"""Containment tests for the preprocess-hook sandbox (no GPU).

The load-bearing test launches a *real* child through the platform's real
containment backend and asserts, from inside that child, that it can read only
the staged scratch dir, cannot read a secret file staged outside it, cannot open
a TCP socket, and never sees the daemon's Qdrant API key in its environment.
There are no mocks of the backend itself - the AppContainer / bubblewrap launch
is genuine - so a regression that widened the sandbox would fail here.

The platform-specific containment test is gated with ``skipif`` on
``sys.platform``: that is capability gating (the Windows AppContainer test cannot
run on Linux and vice versa), not a test-quality skip. The env-curation and
resolve-policy tests are cross-platform.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import textwrap
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ..indexer import _hook_sandbox
from ..indexer._hook_sandbox import (
    SandboxUnavailableError,
    curated_child_env,
    resolve_hook_sandbox,
)

if TYPE_CHECKING:
    from ..indexer._hook_sandbox import SandboxHandle

pytestmark = [pytest.mark.unit]


# A child that probes its own containment and reports a JSON verdict on stdout.
# argv: [staged_path, secret_path]. It reads the staged file (must succeed),
# tries to read a secret outside the grant (must be denied), tries to open a TCP
# socket (must be denied), and checks the daemon secret is absent from its env.
_PROBE = textwrap.dedent(
    """
    import json, os, socket, sys

    staged, secret = sys.argv[1], sys.argv[2]
    verdict = {}

    try:
        with open(staged, encoding="utf-8") as handle:
            handle.read()
        verdict["staged_read"] = "ok"
    except OSError as exc:
        verdict["staged_read"] = "FAIL:" + type(exc).__name__

    try:
        with open(secret, encoding="utf-8") as handle:
            handle.read()
        verdict["secret_read"] = "LEAK"
    except OSError as exc:
        verdict["secret_read"] = "denied:" + type(exc).__name__

    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(5)
        conn.connect(("1.1.1.1", 80))
        conn.close()
        verdict["network"] = "LEAK"
    except OSError as exc:
        verdict["network"] = "denied:" + type(exc).__name__

    verdict["api_key_present"] = (
        os.environ.get("VAULTSPEC_RAG_QDRANT_API_KEY") is not None
    )

    sys.stdout.write(json.dumps(verdict))
    sys.stdout.flush()
    """
)


def _drain(handle: SandboxHandle, timeout: float = 90.0) -> tuple[int, bytes, bytes]:
    """Drain both pipes on threads, then wait; return (rc, stdout, stderr)."""
    captured: dict[str, bytes] = {"out": b"", "err": b""}

    def _read(pipe: object, key: str) -> None:
        assert pipe is not None
        captured[key] = pipe.read()  # type: ignore[attr-defined]

    t_out = threading.Thread(target=_read, args=(handle.stdout, "out"))
    t_err = threading.Thread(target=_read, args=(handle.stderr, "err"))
    t_out.start()
    t_err.start()
    rc = handle.wait(timeout=timeout)
    t_out.join(timeout=10)
    t_err.join(timeout=10)
    return rc, captured["out"], captured["err"]


def test_curated_child_env_strips_secrets_keeps_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_API_KEY", "super-secret")
    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", "C:/managed")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("QDRANT_API_KEY", "q-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")

    env = curated_child_env()

    assert "PATH" in env
    assert not any(name.upper().startswith("VAULTSPEC_RAG_") for name in env)
    assert "HF_TOKEN" not in env
    assert "QDRANT_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    # The allow-list only re-admits path-bearing startup vars, never secrets.
    assert "super-secret" not in env.values()


def test_resolve_server_mode_without_backend_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_hook_sandbox, "_probe_backend", lambda: None)
    with pytest.raises(SandboxUnavailableError):
        resolve_hook_sandbox(server_mode=True, unsandboxed=False)


def test_resolve_unsandboxed_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # The unsandboxed opt-in short-circuits before any probe: even with a
    # backend present it returns None so the runner takes the bare-Popen path.
    monkeypatch.setattr(
        _hook_sandbox, "_probe_backend", lambda: pytest.fail("probe should not run")
    )
    assert resolve_hook_sandbox(server_mode=True, unsandboxed=True) is None


def test_resolve_local_mode_without_backend_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_hook_sandbox, "_probe_backend", lambda: None)
    assert resolve_hook_sandbox(server_mode=False, unsandboxed=False) is None


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_appcontainer_contains_real_child(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ..indexer._hook_sandbox_windows import probe_appcontainer

    backend = probe_appcontainer()
    if backend is None:
        pytest.skip("AppContainer unavailable on this host (OS build / group policy)")

    # A secret the daemon would carry must not leak into the contained child.
    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_API_KEY", "super-secret-value")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged = scratch / "input.txt"
    staged.write_text("staged file body", encoding="utf-8")
    probe = scratch / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")

    # A secret file staged OUTSIDE the granted scratch dir; the child must be
    # denied read access to it.
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")

    # Launch the base interpreter with only the base prefix granted (the venv's
    # site-packages need not be readable for a stdlib-only probe), so the real
    # AppContainer grant stays scoped and fast.
    base_exe = getattr(sys, "_base_executable", sys.executable)
    base_prefix = pathlib.Path(sys.base_prefix)
    argv = [str(base_exe), str(probe), str(staged), str(secret)]

    handle = backend.launch(
        argv,
        scratch_dir=scratch,
        env=curated_child_env(),
        read_paths=[scratch, base_prefix],
    )
    try:
        rc, out, err = _drain(handle)
    finally:
        backend.cleanup(handle)

    detail = (
        f"rc={rc} out={out.decode(errors='replace')} "
        f"err={err.decode(errors='replace')}"
    )
    assert rc == 0, detail
    verdict = json.loads(out.decode())
    assert verdict["staged_read"] == "ok", detail
    assert verdict["secret_read"].startswith("denied"), detail
    assert verdict["network"].startswith("denied"), detail
    assert verdict["api_key_present"] is False, detail


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object is Windows-only")
def test_appcontainer_job_reaps_grandchild_on_cleanup(
    tmp_path: pathlib.Path,
) -> None:
    # H1 regression: cleanup() closes the job handle, and KILL_ON_JOB_CLOSE then
    # tears down the WHOLE tree - including a detached grandchild the hook
    # spawned. Without the job handle held-and-closed, the grandchild would
    # survive and write its sentinel.
    from ..indexer._hook_sandbox_windows import probe_appcontainer

    backend = probe_appcontainer()
    if backend is None:
        pytest.skip("AppContainer unavailable on this host (OS build / group policy)")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sentinel = scratch / "grandchild_ran.txt"
    spawner = scratch / "spawner.py"
    # The hook spawns a detached grandchild that sleeps, then writes the
    # sentinel, and exits immediately itself. If the job tears the tree down on
    # cleanup, the sleeping grandchild is killed before it can write.
    spawner.write_text(
        textwrap.dedent(f"""
            import subprocess, sys
            child = (
                "import time, pathlib; time.sleep(30); "
                "pathlib.Path(r'{sentinel}').write_text('leaked')"
            )
            subprocess.Popen([sys.executable, "-c", child])
            print("spawned")
        """),
        encoding="utf-8",
    )
    base_exe = getattr(sys, "_base_executable", sys.executable)
    handle = backend.launch(
        [str(base_exe), str(spawner)],
        scratch_dir=scratch,
        env=curated_child_env(),
        read_paths=[scratch, pathlib.Path(sys.base_prefix)],
    )
    try:
        _drain(handle)
    finally:
        backend.cleanup(handle)  # closes the job handle -> KILL_ON_JOB_CLOSE

    # The grandchild would need 30s to write; give the reap a generous margin.
    time.sleep(3)
    assert not sentinel.exists(), (
        "grandchild survived job teardown - KILL_ON_JOB_CLOSE did not fire"
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="bubblewrap is Linux")
def test_bubblewrap_contains_real_child(tmp_path: pathlib.Path) -> None:
    if shutil.which("bwrap") is None and shutil.which("bubblewrap") is None:
        pytest.skip("bubblewrap not installed on this host")
    from ..indexer._hook_sandbox_posix import probe_posix_sandbox

    backend = probe_posix_sandbox()
    assert backend is not None

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged = scratch / "input.txt"
    staged.write_text("staged file body", encoding="utf-8")
    probe = scratch / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")

    base_prefix = pathlib.Path(sys.base_prefix)
    prefix = pathlib.Path(sys.prefix)
    argv = [sys.executable, str(probe), str(staged), str(secret)]

    handle = backend.launch(
        argv,
        scratch_dir=scratch,
        env=curated_child_env(),
        read_paths=[scratch, base_prefix, prefix],
    )
    try:
        rc, out, err = _drain(handle)
    finally:
        backend.cleanup(handle)

    detail = (
        f"rc={rc} out={out.decode(errors='replace')} "
        f"err={err.decode(errors='replace')}"
    )
    assert rc == 0, detail
    verdict = json.loads(out.decode())
    assert verdict["staged_read"] == "ok", detail
    assert verdict["secret_read"].startswith("denied"), detail
    assert verdict["network"].startswith("denied"), detail
    assert verdict["api_key_present"] is False, detail
