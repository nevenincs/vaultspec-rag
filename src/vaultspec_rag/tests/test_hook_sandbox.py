"""Direct-launch tests for the preprocess-hook helpers (no GPU).

The OS containment layer was removed (preprocess-sandbox-removal ADR): a root's
``.vaultragpreprocess.toml`` is repo-authored code that runs directly with the
operator's privileges. What survives is the cheap, load-bearing hygiene proven
here with *real* child processes and no mocks: ``curated_child_env`` builds a
secret-free allow-list environment (no daemon tokens, no ``VAULTSPEC_RAG_*``
knobs) and ``default_popen_handle`` launches a child against a given cwd and env
with both pipes captured.
"""

from __future__ import annotations

import json
import sys
import textwrap
import threading
from pathlib import Path
from typing import IO, TYPE_CHECKING

import pytest

from ..indexer._hook_sandbox import curated_child_env, default_popen_handle

if TYPE_CHECKING:
    import subprocess

pytestmark = [pytest.mark.unit]


def _drain(
    handle: subprocess.Popen[bytes], timeout: float = 30.0
) -> tuple[int, bytes, bytes]:
    """Drain both pipes on threads, then wait; return (rc, stdout, stderr)."""
    captured: dict[str, bytes] = {"out": b"", "err": b""}

    def _read(pipe: IO[bytes] | None, key: str) -> None:
        assert pipe is not None
        captured[key] = pipe.read()

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
    """Every credential-bearing and VAULTSPEC_RAG_* knob is dropped; the small
    path/locale allow-list is kept."""
    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_API_KEY", "super-secret")
    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", "C:/managed")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("QDRANT_API_KEY", "q-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")

    env = curated_child_env()

    assert "PATH" in env
    assert not any(name.upper().startswith("VAULTSPEC_RAG_") for name in env)
    assert "HF_TOKEN" not in env
    assert "QDRANT_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # The allow-list only re-admits path-bearing startup vars, never secrets.
    assert "super-secret" not in env.values()
    assert "hf-secret" not in env.values()


def test_curated_child_env_is_a_strict_allow_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An arbitrary non-allow-listed name never reaches the child, even when it
    looks innocuous."""
    monkeypatch.setenv("SOME_RANDOM_APP_KNOB", "value")
    env = curated_child_env()
    assert "SOME_RANDOM_APP_KNOB" not in env


def test_curated_env_seen_by_a_real_child(tmp_path: Path) -> None:
    """A launched child observes exactly the curated env: the daemon secret is
    absent and PATH is present."""

    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            import json, os, sys
            json.dump(
                {
                    "has_secret": "VAULTSPEC_RAG_QDRANT_API_KEY" in os.environ,
                    "has_path": "PATH" in os.environ,
                },
                sys.stdout,
            )
            """
        ),
        encoding="utf-8",
    )
    handle = default_popen_handle(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=curated_child_env(),
    )
    rc, out, err = _drain(handle)
    detail = f"rc={rc} err={err.decode(errors='replace')}"
    assert rc == 0, detail
    verdict = json.loads(out.decode())
    assert verdict["has_secret"] is False, detail
    assert verdict["has_path"] is True, detail


def test_default_popen_handle_runs_in_given_cwd(tmp_path: Path) -> None:
    """The child runs with the provided directory as its cwd."""

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    probe = tmp_path / "cwd_probe.py"
    probe.write_text(
        "import os, sys; sys.stdout.write(os.getcwd())",
        encoding="utf-8",
    )
    handle = default_popen_handle(
        [sys.executable, str(probe)],
        cwd=scratch,
        env=curated_child_env(),
    )
    rc, out, err = _drain(handle)
    detail = f"rc={rc} err={err.decode(errors='replace')}"
    assert rc == 0, detail
    assert Path(out.decode()).resolve() == scratch.resolve(), detail


def test_default_popen_handle_captures_both_pipes(tmp_path: Path) -> None:
    """stdout and stderr are both piped and independently drainable."""

    probe = tmp_path / "pipes_probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            import sys
            sys.stdout.write("OUT")
            sys.stderr.write("ERR")
            """
        ),
        encoding="utf-8",
    )
    handle = default_popen_handle(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=curated_child_env(),
    )
    rc, out, err = _drain(handle)
    assert rc == 0
    assert out.decode() == "OUT"
    assert err.decode() == "ERR"


def test_default_popen_handle_env_reaches_child(tmp_path: Path) -> None:
    """A caller-supplied env value is visible to the launched child."""

    probe = tmp_path / "env_probe.py"
    probe.write_text(
        "import os, sys; sys.stdout.write(os.environ.get('PYTHONPATH', ''))",
        encoding="utf-8",
    )
    env = curated_child_env()
    env["PYTHONPATH"] = str(tmp_path)
    handle = default_popen_handle(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=env,
    )
    rc, out, err = _drain(handle)
    detail = f"rc={rc} err={err.decode(errors='replace')}"
    assert rc == 0, detail
    assert out.decode() == str(tmp_path), detail
