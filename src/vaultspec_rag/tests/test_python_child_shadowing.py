"""A project checkout cannot hand its own code to a child this package starts.

These commands are run from inside project checkouts. A checkout that ships a
directory under this package's name, or a module under the name of something a
child imports, must not have that code run as the operator merely because a
command was typed there.

Every test here starts the real child through the production code that starts
it, from a directory that plants both, and asserts on what executed: a planted
module leaves a file behind when it is imported. Each has a control that starts
the same child the way it used to be started and requires the planted code to
run, so a plant that could never have been imported cannot make a test pass.

The resident service is never started: its launch command is run to its usage
text and no further.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import cast

import pytest

from ..cli._process import _resolve_daemon_interpreter, _service_launch_command
from ..indexer import _pool_guard
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import PreprocessRule
from ..indexer._preprocess_runner import run_preprocessor
from ..operator_state._compute import ProbeDepth
from ..operator_state._environment_probe import _PROBE_SCRIPT, probe_interpreter
from ..operator_state._installation import ComputeCapability
from ._ports import free_loopback_port

pytestmark = [pytest.mark.unit]

_PACKAGE = "vaultspec_rag"
_CHILD_TIMEOUT_SECONDS = 180.0


def _plant_module(checkout: Path, name: str) -> Path:
    """Ship a module called *name* in *checkout*; return the file it leaves."""
    ran = checkout / f"{name}.ran"
    (checkout / f"{name}.py").write_text(_plant_source(ran), encoding="utf-8")
    return ran


def _plant_package(checkout: Path, name: str = _PACKAGE) -> Path:
    """Ship a package called *name* in *checkout*; return the file it leaves."""
    ran = checkout / f"{name}.ran"
    package = checkout / name
    package.mkdir()
    (package / "__init__.py").write_text(_plant_source(ran), encoding="utf-8")
    return ran


def _plant_source(ran: Path) -> str:
    return (
        "import pathlib\n"
        f"pathlib.Path({str(ran)!r}).write_text('ran', encoding='utf-8')\n"
    )


def _checkout(tmp_path: Path, name: str) -> Path:
    checkout = tmp_path / name
    checkout.mkdir()
    return checkout


def _child_environment(**extra: str) -> dict[str, str]:
    """This process's environment, without an inherited safe-path switch.

    With the switch inherited, every child would be safe whatever the code
    under test did, and the controls would fail for a reason that has nothing
    to do with it.
    """
    environment = {
        name: value for name, value in os.environ.items() if name != "PYTHONSAFEPATH"
    }
    environment.update(extra)
    return environment


def _run_in(
    checkout: Path, command: list[str], **extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=checkout,
        env=_child_environment(**extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
    )


@pytest.fixture
def unswitched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Children of this process inherit no safe-path switch from it."""
    monkeypatch.delenv("PYTHONSAFEPATH", raising=False)


# --- the environment probe -------------------------------------------------


def test_the_environment_probe_does_not_import_from_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unswitched: None
) -> None:
    """The probe answers for the installed package, from any directory.

    Shown to fail by building the probe's command by hand without the
    safe-path flag: the planted package runs and the first assertion fires.
    Passes with the builder call restored.
    """
    del unswitched
    checkout = _checkout(tmp_path, "checkout")
    package_ran = _plant_package(checkout)
    dependency_ran = _plant_module(checkout, "pydantic")
    monkeypatch.chdir(checkout)

    facts = probe_interpreter(sys.executable, ProbeDepth.METADATA)

    assert not package_ran.exists(), "the checkout's package ran in the probe"
    assert not dependency_ran.exists(), "the checkout's module ran in the probe"
    assert facts.compute.capability is not ComputeCapability.UNKNOWN, (
        facts.compute.detail
    )


def test_the_probe_started_the_old_way_runs_the_checkout(tmp_path: Path) -> None:
    """Control: both plants are live for the probe's own program."""
    command = [sys.executable, "-c", _PROBE_SCRIPT, ProbeDepth.METADATA.value]
    both = _checkout(tmp_path, "both")
    package_ran = _plant_package(both)
    only_dependency = _checkout(tmp_path, "dependency")
    dependency_ran = _plant_module(only_dependency, "pydantic")

    _run_in(both, command)
    _run_in(only_dependency, command)

    assert package_ran.exists()
    assert dependency_ran.exists()


# --- the resident service launch -------------------------------------------


def _isolated_service_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "VAULTSPEC_RAG_STATUS_DIR": str(tmp_path / "status"),
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(tmp_path / "storage"),
    }


def test_the_service_launch_command_does_not_import_from_the_checkout(
    tmp_path: Path,
) -> None:
    """The command that starts the service runs the installed service.

    The command is the one the spawn builds, run to its usage text so that no
    service starts. Shown to fail by building the launch command by hand
    without the safe-path flag: the planted package runs in place of the
    server and the first assertion fires. Passes with the builder restored.
    """
    checkout = _checkout(tmp_path, "checkout")
    package_ran = _plant_package(checkout)
    dependency_ran = _plant_module(checkout, "starlette")
    command = _service_launch_command(
        _resolve_daemon_interpreter(), free_loopback_port(), "launch-token"
    )

    proc = _run_in(
        checkout, [*command, "--help"], **_isolated_service_environment(tmp_path)
    )

    assert not package_ran.exists(), "the checkout's package ran as the service"
    assert not dependency_ran.exists(), "the checkout's module ran in the service"
    assert proc.returncode == 0, proc.stderr
    assert "--port" in proc.stdout


def test_the_service_started_the_old_way_runs_the_checkout(tmp_path: Path) -> None:
    """Control: both plants are live for the server module."""
    command = [
        _resolve_daemon_interpreter(),
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(free_loopback_port()),
        "--help",
    ]
    both = _checkout(tmp_path, "both")
    package_ran = _plant_package(both)
    only_dependency = _checkout(tmp_path, "dependency")
    dependency_ran = _plant_module(only_dependency, "starlette")
    isolated = _isolated_service_environment(tmp_path)

    _run_in(both, command, **isolated)
    _run_in(only_dependency, command, **isolated)

    assert package_ran.exists()
    assert dependency_ran.exists()


# --- the preprocess entry runner -------------------------------------------

_HOOK = """
    from hooks.wording import describe

    def extract(source_path):
        return {
            "schema_version": 1,
            "preprocessor_id": "planted-project-hook",
            "preprocessor_version": "1.0",
            "source_path": source_path,
            "text": describe(),
        }
"""

_HOOK_SIBLING = """
    def describe():
        return "text from the hook's own sibling module"
"""


def _project_with_a_hook(tmp_path: Path) -> tuple[Path, Path, PreprocessRule]:
    """A project whose entry-point hook imports a module of its own."""
    project = _checkout(tmp_path, "project")
    hooks = project / "hooks"
    hooks.mkdir()
    (hooks / "__init__.py").write_text("", encoding="utf-8")
    (hooks / "extract.py").write_text(textwrap.dedent(_HOOK), encoding="utf-8")
    (hooks / "wording.py").write_text(textwrap.dedent(_HOOK_SIBLING), encoding="utf-8")
    source = project / "document.bin"
    source.write_bytes(b"\x00binary")
    rule = PreprocessRule(
        pattern="*.bin",
        command=None,
        entry_point="hooks.extract:extract",
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
        on_error="skip",
        timeout_s=120.0,
        options={},
        order=0,
    )
    return project, source, rule


def test_a_project_cannot_replace_the_entry_runner_that_runs_its_hook(
    tmp_path: Path, unswitched: None
) -> None:
    """A project's hook runs under this package's runner, not the project's.

    The hook child exists to run project code, so the project root stays on
    its import path and the hook imports its own sibling module as before.
    What the project does not get to supply is the runner. Shown to fail by
    starting the runner by its module path again: the project's directory
    under this package's name is imported in its place, and the first
    assertion fires. Passes with the runner named by file restored.
    """
    del unswitched
    project, source, rule = _project_with_a_hook(tmp_path)
    package_ran = _plant_package(project)

    result = run_preprocessor(
        source, rule, max_emitted_bytes=1024 * 1024, project_root=project
    )

    assert not package_ran.exists(), "the project's package replaced the runner"
    assert result.status == "ok", result.reason
    assert result.output is not None
    assert result.output.text == "text from the hook's own sibling module"


def test_the_entry_runner_started_the_old_way_is_replaced_by_the_project(
    tmp_path: Path,
) -> None:
    """Control: the planted package is live for the runner's module path."""
    project, source, rule = _project_with_a_hook(tmp_path)
    package_ran = _plant_package(project)
    assert rule.entry_point is not None

    _run_in(
        project,
        [
            sys.executable,
            "-m",
            "vaultspec_rag.indexer._preprocess_entry",
            rule.entry_point,
            str(source),
        ],
        PYTHONPATH=str(project),
    )

    assert package_ran.exists()


# --- pool workers ----------------------------------------------------------

# Run as a script, which is how the command line itself is started: the
# script's directory is on the import path and the working directory is not,
# so the parent is not what imports the plant. Absolute imports because a
# script has no package to resolve a relative one against.
_POOL_DRIVER = """\
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from vaultspec_rag.indexer._pool_guard import spawn_pool  # absolute-import-ok

VARIABLE = "PYTHONSAFEPATH"


def observed():
    return os.environ.get(VARIABLE)


def main():
    guarded = sys.argv[1] == "guarded"
    context = multiprocessing.get_context("spawn")
    report = {"before": observed()}
    try:
        if guarded:
            with spawn_pool(max_workers=1, mp_context=context) as outer:
                report["worker"] = outer.submit(os.getpid).result(timeout=120)
                with spawn_pool(max_workers=1, mp_context=context) as inner:
                    report["inner_worker"] = inner.submit(os.getpid).result(timeout=120)
                    report["during_both"] = observed()
                report["during_outer_only"] = observed()
        else:
            with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
                report["worker"] = pool.submit(os.getpid).result(timeout=120)
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    report["after"] = observed()
    report["parent"] = os.getpid()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
"""


def _run_pool_driver(
    tmp_path: Path,
    mode: str,
    *,
    initial: str | None = None,
    interpreter_flags: tuple[str, ...] = (),
) -> tuple[dict[str, object], Path]:
    """Run the driver from a checkout that plants ``multiprocessing``."""
    driver = tmp_path / "installed" / "pool_driver.py"
    driver.parent.mkdir(exist_ok=True)
    driver.write_text(_POOL_DRIVER, encoding="utf-8")
    checkout = _checkout(tmp_path, f"checkout-{mode}")
    ran = _plant_module(checkout, "multiprocessing")
    source_root = Path(_pool_guard.__file__).resolve().parents[2]
    extra = {"PYTHONPATH": str(source_root)}
    if initial is not None:
        extra["PYTHONSAFEPATH"] = initial

    proc = _run_in(
        checkout, [sys.executable, *interpreter_flags, str(driver), mode], **extra
    )

    assert proc.returncode == 0, proc.stderr
    report: object = json.loads(proc.stdout.strip().splitlines()[-1])
    assert isinstance(report, dict)
    return cast("dict[str, object]", report), ran


@pytest.mark.parametrize("initial", [None, ""])
def test_a_pool_worker_does_not_import_from_the_working_directory(
    tmp_path: Path, initial: str | None
) -> None:
    """A worker of a parent that is not in safe-path mode still starts safe.

    The standard library starts a worker on an inline program, so the working
    directory leads its import path while it imports the bootstrap. The
    checkout plants a module under the bootstrap's own name. Shown to fail by
    making the pool constructor leave the environment alone: the planted
    module runs in the worker, the pool breaks, and the first assertion
    fires. Passes with the guard restored.

    The switch is the process's own environment, so it is also held to going
    back exactly as it was - absent when it was absent, empty when it was
    empty - and to staying set while any pool is still open.
    """
    report, ran = _run_pool_driver(tmp_path, "guarded", initial=initial)

    assert not ran.exists(), "the checkout's module ran in a pool worker"
    assert "error" not in report, report
    assert report["worker"] != report["parent"]
    assert report["before"] == initial
    assert report["during_both"] == "1"
    assert report["during_outer_only"] == "1", "closing one pool unset it for another"
    assert report["after"] == initial, "the switch was not put back as it was"


def test_a_pool_built_without_the_guard_runs_the_working_directory(
    tmp_path: Path,
) -> None:
    """Control: the plant is live for a worker of a bare process pool."""
    report, ran = _run_pool_driver(tmp_path, "bare")

    assert ran.exists()
    assert "BrokenProcessPool" in str(report.get("error"))


def test_a_parent_that_ignores_its_environment_is_refused_a_pool(
    tmp_path: Path,
) -> None:
    """A worker that would never read the switch is not started at all.

    A parent started to ignore its environment passes that on to its workers,
    so the switch cannot reach them. Shown to fail by removing the refusal:
    the pool then opens, the planted module runs, and the first assertion
    fires.
    """
    report, ran = _run_pool_driver(tmp_path, "guarded", interpreter_flags=("-E",))

    assert not ran.exists(), "the checkout's module ran in a pool worker"
    assert "cannot be started safely" in str(report.get("error"))
