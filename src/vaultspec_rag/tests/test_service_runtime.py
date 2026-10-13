"""The managed environment a start runs the daemon from when its launcher cannot.

The selection, the requirement that reproduces this release, the uv the build
runs through, and the staging-and-rename publication are each exercised here.

What is staged and what is real: the filesystem is real throughout - every
runtime directory, completion record, staging directory and lock is a real one
under a redirected status directory. The two things a unit test cannot afford
are replaced where they are produced, never where they are decided: the uv
subprocess, which would download the GPU stack, and the child interpreter that
imports torch, whose answer is a fact about the machine. The last test in this
module runs both for real, against a wheel built from this checkout.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer

from .. import service_runtime
from ..cli._core import _build_console
from ..cli._progress import StartupStatusReporter
from ..cli._service_start import _select_service_environment
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability, InstallRole
from ..operator_state._provisioning import CU130_INDEX_STRATEGY, HOST_PYTHON
from ..operator_state._service_environment import ServiceEnvironment
from ..service_runtime import (
    ERROR_RUNTIME_FAILED,
    ERROR_RUNTIME_NO_GPU,
    ERROR_RUNTIME_UNSUPPORTED,
    RUNTIME_RECORD_NAME,
    RuntimeRequirement,
    ServiceInterpreterSource,
    ServiceRuntimeError,
    ensure_service_runtime,
    install_arguments,
    installed_release,
    planned_service_interpreter,
    remove_superseded_runtimes,
    runtime_interpreter,
    runtime_requirement,
    runtime_root,
    uv_executable,
    uv_install_command,
    venv_arguments,
)
from ..torch_config._index import CU130_INDEX_URL
from .conftest import managed_env, pin_daemon_capability, pin_install_role


def _interpreter_in(root: Path) -> str:
    """An interpreter inside an environment rooted at *root*, on disk."""
    interpreter = runtime_interpreter(root)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.touch()
    return str(interpreter)


def _launching(interpreter: str, capability: ComputeCapability) -> ServiceEnvironment:
    """The judgement a start has made of the environment that launched it."""
    return ServiceEnvironment(interpreter, capability)


def _publish_runtime(release: str | None = None) -> Path:
    """A complete runtime for *release* under the redirected status directory."""
    wanted = installed_release() if release is None else release
    directory = runtime_root() / wanted
    _interpreter_in(directory)
    (directory / RUNTIME_RECORD_NAME).write_text(
        json.dumps({"release": wanted, "source": "index", "capability": "ready"}),
        encoding="utf-8",
    )
    return directory


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestWhichEnvironmentWouldServe:
    """The plan reads the launcher's judgement and the runtime directory only."""

    def test_an_environment_that_can_serve_serves(self, tmp_path: Path) -> None:
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.READY)
        )

        assert plan.source is ServiceInterpreterSource.LAUNCHING
        assert plan.interpreter == interpreter

    def test_a_uvx_cache_environment_never_serves(self, tmp_path: Path) -> None:
        """Guard assertion: uv replaces such an environment under the daemon.

        It is refused even though its own judgement says it could serve, so
        the condition under test is the environment kind alone. Mutation
        check: dropping the kind from the selection returns ``launching``
        here and fails on the source.
        """
        interpreter = _interpreter_in(tmp_path / "cache" / "archive-v0" / "aB3dEf")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.READY)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED
        assert plan.interpreter is None

    @pytest.mark.parametrize(
        "capability",
        [
            ComputeCapability.NOT_APPLICABLE,
            ComputeCapability.CPU_ONLY_BUILD,
            ComputeCapability.TORCH_MISSING,
            ComputeCapability.NO_DEVICE,
        ],
    )
    def test_a_launcher_that_cannot_serve_needs_the_runtime(
        self, tmp_path: Path, capability: ComputeCapability
    ) -> None:
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(_launching(interpreter, capability))

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED
        assert plan.runtime_dir == runtime_root() / installed_release()

    def test_a_check_that_did_not_finish_still_serves(self, tmp_path: Path) -> None:
        """An inconclusive probe is not a refusal, here as on every start."""
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.UNKNOWN)
        )

        assert plan.source is ServiceInterpreterSource.LAUNCHING

    def test_a_published_runtime_is_what_would_serve(self, tmp_path: Path) -> None:
        directory = _publish_runtime()
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME
        assert plan.interpreter == str(runtime_interpreter(directory))
        assert plan.runtime_dir == directory

    def test_a_build_that_did_not_finish_is_not_a_runtime(self, tmp_path: Path) -> None:
        """Guard assertion: a record is what completion means.

        An interrupted build leaves the environment without its record, and
        running a daemon from a half-installed environment is the outcome the
        record exists to prevent. Mutation check: accepting a directory whose
        record is absent returns ``runtime`` here and fails on the source.
        """
        _interpreter_in(runtime_root() / installed_release())
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED

    def test_another_releases_runtime_is_not_this_releases(
        self, tmp_path: Path
    ) -> None:
        """A client refuses a service from another release, so this must too."""
        _publish_runtime("0.0.1-not-this-release")
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED


@pytest.mark.unit
class TestWhatTheRuntimeHolds:
    """The requirement reproduces the launching release from its own origin."""

    def test_an_index_install_is_named_by_its_version(self) -> None:
        requirement = runtime_requirement("0.6.0", None)

        assert requirement.requirement == "vaultspec-rag[gpu]==0.6.0"
        assert requirement.source == "index"

    @pytest.mark.parametrize(
        "url",
        [
            "file:///tmp/wheels/vaultspec_rag-0.6.0-py3-none-any.whl",
            "https://example.test/vaultspec_rag-0.6.0-py3-none-any.whl",
        ],
    )
    def test_an_archive_install_is_named_by_that_archive(self, url: str) -> None:
        """The operator's own build, not whatever the index publishes for it."""
        requirement = runtime_requirement("0.6.0", {"url": url, "archive_info": {}})

        assert requirement.requirement == f"vaultspec-rag[gpu] @ {url}"
        assert requirement.source == url

    @pytest.mark.parametrize(
        "origin",
        [
            {"url": "file:///src/vaultspec-rag", "dir_info": {"editable": True}},
            {"url": "file:///src/vaultspec-rag", "dir_info": {}},
            {"url": "https://example.test/repo.git", "vcs_info": {"vcs": "git"}},
        ],
    )
    def test_a_checkout_is_refused_with_one_command(
        self, origin: dict[str, object]
    ) -> None:
        """Guard assertion: no requirement reproduces a working tree.

        Mutation check: treating a ``dir_info`` origin as an archive builds a
        runtime from a path that is not a release, and this raises nothing.
        """
        with pytest.raises(ServiceRuntimeError) as refusal:
            runtime_requirement("0.6.0", origin)

        assert refusal.value.code == ERROR_RUNTIME_UNSUPPORTED
        assert refusal.value.command is not None
        assert refusal.value.command.startswith("uv tool install")
        assert refusal.value.cause.count(".") == 1


@pytest.mark.unit
class TestTheUvTheBuildRunsThrough:
    """uv names itself to its children; otherwise it is found on PATH."""

    def test_the_uv_running_this_command_is_the_one_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        named = tmp_path / "uv-from-uv"
        named.touch()
        monkeypatch.setenv(EnvVar.UV.value, str(named))

        assert uv_executable() == str(named)

    def test_a_name_that_is_not_a_file_is_not_believed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: an exported name may point at nothing.

        Mutation check: returning the value unchecked yields the absent path
        here, and the start would then fail on a missing executable instead
        of on the environment it can describe.
        """
        monkeypatch.setenv(EnvVar.UV.value, str(tmp_path / "absent-uv"))
        monkeypatch.setenv(EnvVar.PATH.value, "")

        assert uv_executable() is None

    def test_an_absolute_uv_on_the_search_path_is_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "bin"
        directory.mkdir()
        name = "uv.exe" if sys.platform == "win32" else "uv"
        executable = directory / name
        executable.write_text("", encoding="utf-8")
        executable.chmod(0o755)
        monkeypatch.delenv(EnvVar.UV.value, raising=False)
        monkeypatch.setenv(EnvVar.PATH.value, str(directory))

        found = uv_executable()

        assert found is not None
        assert os.path.isabs(found)
        assert os.path.samefile(found, executable)

    def test_the_install_one_liner_is_the_one_for_this_platform(self) -> None:
        assert "astral.sh/uv/install.ps1" in uv_install_command("win32")
        assert "astral.sh/uv/install.sh" in uv_install_command("linux")
        assert "astral.sh/uv/install.sh" in uv_install_command("darwin")

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_without_uv_the_start_is_refused_with_that_one_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _without_uv(monkeypatch)
        _staged_origin(monkeypatch)

        with pytest.raises(ServiceRuntimeError) as refusal:
            ensure_service_runtime()

        assert refusal.value.code == ERROR_RUNTIME_UNSUPPORTED
        assert refusal.value.command == uv_install_command()


@pytest.mark.unit
class TestHowUvIsAsked:
    """Both calls are built from the constants the host install already uses."""

    def test_the_environment_is_created_at_the_host_interpreter(
        self, tmp_path: Path
    ) -> None:
        arguments = venv_arguments("uv", tmp_path / "staging")

        assert arguments == (
            "uv",
            "venv",
            "--python",
            HOST_PYTHON,
            str(tmp_path / "staging"),
        )

    def test_the_install_targets_the_new_environments_own_interpreter(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: never the environment that launched the start.

        The whole point of the runtime is that the launching environment is
        not touched, and ``--python`` is what decides which one uv writes to.
        """
        interpreter = runtime_interpreter(tmp_path / "staging")
        requirement = RuntimeRequirement("vaultspec-rag[gpu]==0.6.0", "index")

        arguments = install_arguments("uv", interpreter, requirement, "linux")

        assert arguments[:6] == (
            "uv",
            "pip",
            "install",
            "--python",
            str(interpreter),
            requirement.requirement,
        )

    @pytest.mark.parametrize("platform_name", ["win32", "linux"])
    def test_torch_comes_from_the_cuda_index_where_one_is_published(
        self, tmp_path: Path, platform_name: str
    ) -> None:
        arguments = install_arguments(
            "uv",
            runtime_interpreter(tmp_path),
            RuntimeRequirement("vaultspec-rag[gpu]==0.6.0", "index"),
            platform_name,
        )

        assert arguments[-4:] == (
            "--index",
            CU130_INDEX_URL,
            "--index-strategy",
            CU130_INDEX_STRATEGY,
        )

    def test_apple_silicon_takes_the_wheel_that_carries_metal(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the CUDA index publishes nothing for macOS."""
        arguments = install_arguments(
            "uv",
            runtime_interpreter(tmp_path),
            RuntimeRequirement("vaultspec-rag[gpu]==0.6.0", "index"),
            "darwin",
        )

        assert CU130_INDEX_URL not in arguments
        assert "--index" not in arguments


def _staged_origin(
    monkeypatch: pytest.MonkeyPatch, origin: dict[str, object] | None = None
) -> None:
    """Stage where the launching distribution came from.

    This checkout is installed from a working tree, which the runtime refuses
    to reproduce, so every test about what happens AFTER the origin is read
    has to name one. ``None`` is the common case: an install from the index.
    """
    monkeypatch.setattr(service_runtime, "distribution_origin", lambda: origin)


def _without_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage a machine with no uv, which this one cannot be made into."""
    monkeypatch.setattr(service_runtime, "uv_executable", lambda: None)


def _staged_uv(
    monkeypatch: pytest.MonkeyPatch, *, fails: str | None = None
) -> list[tuple[str, ...]]:
    """Replace the uv subprocess with one that writes what uv would write.

    Returns the list every call is recorded in, so a test can assert that a
    present runtime cost no uv call at all. The environment uv would create is
    created here instead: that is the one thing the steps after it read.
    """
    calls: list[tuple[str, ...]] = []

    def run(arguments: tuple[str, ...], activity: str, timeout: float) -> None:
        del timeout
        calls.append(arguments)
        if fails == activity:
            raise ServiceRuntimeError(ERROR_RUNTIME_FAILED, f"uv failed to {activity}.")
        if arguments[1] == "venv":
            _interpreter_in(Path(arguments[-1]))

    monkeypatch.setattr(service_runtime, "_run_uv", run)
    return calls


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestBuildingAndPublishingTheRuntime:
    """Built in staging, judged, recorded, then published by one rename."""

    def test_a_built_runtime_is_published_with_its_completion_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        _staged_origin(monkeypatch)

        runtime = ensure_service_runtime()

        assert runtime.created
        assert runtime.directory == runtime_root() / installed_release()
        assert runtime.interpreter == str(runtime_interpreter(runtime.directory))
        record = json.loads(
            (runtime.directory / RUNTIME_RECORD_NAME).read_text(encoding="utf-8")
        )
        assert record["release"] == installed_release()
        assert record["source"] == "index"
        assert record["capability"] == str(ComputeCapability.READY)

    def test_nothing_staged_survives_a_published_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        _staged_origin(monkeypatch)

        ensure_service_runtime()

        assert [entry.name for entry in runtime_root().iterdir() if entry.is_dir()] == [
            installed_release()
        ]

    def test_a_present_runtime_costs_no_uv_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: a complete runtime must cost no network.

        Mutation check: building unconditionally records a uv call here and
        fails on the empty list.
        """
        _publish_runtime()
        calls = _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        # Staged so the mutation lands on the uv call and not on this
        # checkout's own origin, which is a working tree.
        _staged_origin(monkeypatch)

        runtime = ensure_service_runtime()

        assert calls == []
        assert not runtime.created

    def test_a_failed_install_leaves_nothing_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An incomplete build is deleted, so the next start begins afresh."""
        _staged_uv(monkeypatch, fails="install the GPU stack")
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        _staged_origin(monkeypatch)

        with pytest.raises(ServiceRuntimeError) as refusal:
            ensure_service_runtime()

        assert refusal.value.code == ERROR_RUNTIME_FAILED
        assert list(runtime_root().iterdir()) == [runtime_root() / ".runtime.lock"]

    def test_a_runtime_that_cannot_serve_is_never_published(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: no CPU runtime is ever accepted.

        Mutation check: publishing before the judgement leaves the directory
        in place and fails the second assertion, after which every later start
        would run a daemon that cannot load a model.
        """
        _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)
        _staged_origin(monkeypatch)

        with pytest.raises(ServiceRuntimeError) as refusal:
            ensure_service_runtime()

        assert refusal.value.code == ERROR_RUNTIME_NO_GPU
        assert not (runtime_root() / installed_release()).exists()
        assert ComputeCapability.CPU_ONLY_BUILD.label in refusal.value.cause

    def test_a_build_already_running_is_not_run_a_second_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: two builds would download the stack twice.

        The lock is taken here by a second real handle, which the OS refuses
        exactly as it refuses a foreign process's. Mutation check: building
        outside the lock records a uv call here and fails on the empty list.
        """
        from .._store_locks import FileLock

        monkeypatch.setattr(service_runtime, "_LOCK_WAIT_SECONDS", 0.0)
        calls = _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        _staged_origin(monkeypatch)
        runtime_root().mkdir(parents=True, exist_ok=True)
        holder = FileLock(runtime_root() / ".runtime.lock")
        assert holder.acquire()
        try:
            with pytest.raises(ServiceRuntimeError) as refusal:
                ensure_service_runtime()
        finally:
            holder.release()

        assert refusal.value.code == ERROR_RUNTIME_FAILED
        assert calls == []

    def test_the_runtime_published_while_waiting_is_the_one_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two starts racing end with one runtime, not two."""
        _staged_uv(monkeypatch)
        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        _staged_origin(monkeypatch)

        first = ensure_service_runtime()
        second = ensure_service_runtime()

        assert second.directory == first.directory
        assert not second.created


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestReclaimingSupersededRuntimes:
    """This release's runtime stays; everything else under the root goes."""

    def test_older_releases_and_abandoned_staging_are_removed(self) -> None:
        keep = _publish_runtime()
        superseded = _publish_runtime("0.0.1-older")
        abandoned = runtime_root() / ".staging-1234-abcdef"
        _interpreter_in(abandoned)

        removed = remove_superseded_runtimes()

        assert keep.exists()
        assert not superseded.exists()
        assert not abandoned.exists()
        assert set(removed) == {superseded, abandoned}

    def test_a_root_that_does_not_exist_is_not_an_error(self) -> None:
        assert remove_superseded_runtimes() == ()


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestTheStartEnvelope:
    """A refused runtime is one envelope on the start's one exit path."""

    def test_a_json_start_emits_exactly_one_envelope_for_the_refusal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _without_uv(monkeypatch)
        _staged_origin(monkeypatch)
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)
        reporter = StartupStatusReporter(
            json_mode=True,
            console=_build_console(interactive=False, file=io.StringIO()),
            interactive=False,
        )

        with reporter as progress, pytest.raises(typer.Exit) as exit_info:
            _select_service_environment(interpreter, json_mode=True, progress=progress)

        assert exit_info.value.exit_code != 0
        documents = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.strip().startswith("{")
        ]
        assert len(documents) == 1, f"expected one envelope, got {documents}"
        assert documents[0]["error"] == ERROR_RUNTIME_UNSUPPORTED
        # One command, and only that one: the envelope carries what the
        # operator would have read.
        assert documents[0]["data"]["next_actions"] == [uv_install_command()]


@pytest.mark.integration
@pytest.mark.cuda
def test_a_runtime_is_really_built_from_a_wheel_of_this_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole creation path, with the real uv and the real judgement.

    Everything the unit tests stage is real here: uv creates the environment
    and installs this checkout's own wheel with the GPU stack from the CUDA
    index, and the published runtime is judged by a child of its own
    interpreter, which imports torch there. Needs the network, several
    gigabytes of disk, and the accelerator the judgement verifies, which is
    why it carries both markers.

    The status directory is redirected, so nothing here reaches the service
    directory of the operator's own installation.
    """
    uv = uv_executable()
    if uv is None:
        pytest.skip("uv is not installed on this machine")
    checkout = Path(__file__).resolve().parents[3]
    wheels = tmp_path / "wheels"
    built = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(wheels), str(checkout)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheel = next(iter(sorted(wheels.glob("*.whl"))))
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    _staged_origin(monkeypatch, {"url": wheel.as_uri(), "archive_info": {}})
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(status_dir),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant"),
        }
    ):
        runtime = ensure_service_runtime()

        assert runtime.created
        assert runtime.source == wheel.as_uri()
        assert runtime.directory == status_dir / "runtime" / installed_release()
        assert Path(runtime.interpreter).is_file()
        assert runtime.environment.can_run_service
        # The second call is the one an everyday start makes, and it must
        # neither download nor rebuild anything.
        again = ensure_service_runtime()
        assert not again.created
        assert again.directory == runtime.directory
