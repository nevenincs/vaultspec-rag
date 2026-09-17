"""The model cache survives a release; the package caches do not.

``contain-writes`` derives every cache directory from a key. Package caches
must change with the lockfile, because what they hold depends on it. The
model cache must not: every release rewrites ``uv.lock`` and
``pyproject.toml``, so a model cache keyed on them starts empty on every
release and downloads gigabytes of weights again. The trust tier stays in the
model key, so a pull request never writes a cache a release reads.

This runs the action's own pinning script for this host's shell - bash on
POSIX, pwsh on Windows - inside a scratch directory, so the answer is what
the runner would compute, not a reading of the script's text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest
import yaml

from dev.guards import _workflows as workflows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.repo]

ACTION = ".github/actions/contain-writes/action.yml"

#: Variables the host may already set; removed so every path lands in scratch.
_HOST_CACHE_VARIABLES = (
    "HF_HOME",
    "XDG_CACHE_HOME",
    "UV_CACHE_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "CARGO_HOME",
    "RUSTUP_HOME",
)


def _pinning_script() -> tuple[list[str], str, str]:
    """Return ``(shell argv, script, runner os)`` for this host's step."""
    path = workflows.repository_root() / ACTION
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    runs = cast("dict[str, object]", cast("dict[str, object]", loaded)["runs"])
    steps = cast("list[dict[str, object]]", runs["steps"])
    windows = sys.platform == "win32"
    wanted = "Contain writes (Windows)" if windows else "Contain writes (POSIX)"
    step = next(step for step in steps if step.get("name") == wanted)
    shell = "pwsh" if windows else "bash"
    executable = shutil.which(shell)
    assert executable is not None, f"{shell} is required to run {wanted}"
    argv = (
        [executable, "-NoProfile", "-NonInteractive", "-Command"]
        if windows
        else [executable, "-e", "-c"]
    )
    return argv, str(step["run"]), "Windows" if windows else "Linux"


def _pinned(
    root: Path,
    *,
    lock: str,
    python: str,
    event: str,
    workflow: str,
) -> dict[str, str]:
    """Run the pinning script in *root* and return what it exported."""
    argv, script, runner_os = _pinning_script()
    root.mkdir(parents=True, exist_ok=True)
    (root / "uv.lock").write_text(lock, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    exported = root / "github-env"
    exported.write_text("", encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _HOST_CACHE_VARIABLES
    }
    environment.update(
        {
            "RUNNER_TEMP": str(root / "temp"),
            "RUNNER_TOOL_CACHE": str(root / "tools"),
            "RUNNER_OS": runner_os,
            "RUNNER_ARCH": "X64",
            "GITHUB_ENV": str(exported),
            "GITHUB_EVENT_NAME": event,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW": workflow,
            "UV_PYTHON": python,
            "CI_CACHE_MODE": "normal",
        }
    )
    (root / "temp").mkdir(exist_ok=True)
    subprocess.run(
        [*argv, script],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    values: dict[str, str] = {}
    for line in exported.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()
    return values


def _relative(values: dict[str, str], name: str, root: Path) -> str:
    """Return *name*'s exported path relative to *root*, with ``/`` separators."""
    value = values[name].replace("\\", "/")
    prefix = str(root).replace("\\", "/").rstrip("/") + "/"
    assert value.startswith(prefix), f"{name}={value} escaped the scratch root"
    return value[len(prefix) :]


def test_a_release_keeps_the_model_cache_and_rotates_package_caches(
    tmp_path: Path,
) -> None:
    """A lockfile or interpreter change moves package caches, not models.

    Mutation proof: passing ``$compat`` instead of ``$model_compat`` for
    ``HF_HOME`` makes this fail on the model-cache equality; restoring
    ``$model_compat`` makes this pass.
    """
    release = {"event": "workflow_dispatch", "workflow": "Publish"}
    before = _pinned(tmp_path / "a", lock="version = 1\n", python="3.13", **release)
    bumped = _pinned(tmp_path / "b", lock="version = 2\n", python="3.13", **release)
    other = _pinned(tmp_path / "c", lock="version = 1\n", python="3.14", **release)

    models = {
        _relative(values, "HF_HOME", tmp_path / name)
        for name, values in (("a", before), ("b", bumped), ("c", other))
    }
    assert len(models) == 1, (
        f"the model cache moved with the lockfile or interpreter: {sorted(models)}"
    )
    packages = {
        _relative(values, "UV_CACHE_DIR", tmp_path / name)
        for name, values in (("a", before), ("b", bumped), ("c", other))
    }
    assert len(packages) == 3, (
        f"the package cache ignored the lockfile or interpreter: {sorted(packages)}"
    )


def test_a_pull_request_never_shares_the_release_model_cache(tmp_path: Path) -> None:
    """The trust tier stays in the model cache key.

    Mutation proof: dropping the trust key from ``model_compat`` makes this
    fail on the inequality; restoring it makes this pass.
    """
    lock = "version = 1\n"
    release = _pinned(
        tmp_path / "r",
        lock=lock,
        python="3.13",
        event="workflow_dispatch",
        workflow="Publish",
    )
    pull = _pinned(
        tmp_path / "p",
        lock=lock,
        python="3.13",
        event="pull_request",
        workflow="Merge Gate",
    )
    assert _relative(release, "HF_HOME", tmp_path / "r") != _relative(
        pull, "HF_HOME", tmp_path / "p"
    ), "a pull request and a release share one model cache"
