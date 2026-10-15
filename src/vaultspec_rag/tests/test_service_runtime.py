"""The managed environment a start runs the daemon from when its launcher cannot.

The selection, the requirement that reproduces this release, the uv the build
runs through, and the staging-and-rename publication are each exercised here.

Nothing is replaced. The filesystem, the lock, the staging directory, the
rename, the completion record and the judgement are the real ones under a
redirected status directory. What a build does is run by the real code in a
fresh interpreter of a separate installation of this package - one installed
from an index, or from a wheel of this checkout - with the real uv. What a
runtime can do is what its own interpreter says when it is asked, and a
refusal is reached the way an operator reaches it: an environment with no uv
on its path, an index that does not serve the release, a device hidden from
the build, or a build lock another process holds. The tests that build the GPU
stack need the network or a warm uv cache, several gigabytes of disk, and the
accelerator the judgement verifies, which is why they carry the markers they do.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

from .._operator_commands import server_start_command
from ..config._types import EnvVar
from ..operator_state._installation import (
    DRIVER_CHECK_COMMAND,
    ComputeCapability,
)
from ..operator_state._provisioning import CU130_INDEX_STRATEGY, HOST_PYTHON
from ..operator_state._service_environment import ServiceEnvironment
from ..service_runtime import (
    ERROR_RUNTIME_FAILED,
    ERROR_RUNTIME_NO_GPU,
    ERROR_RUNTIME_UNSUPPORTED,
    INDEX_SOURCE,
    RUNTIME_RECORD_NAME,
    RuntimeRequirement,
    ServiceInterpreterSource,
    ServiceRuntimeError,
    _record,
    install_arguments,
    installed_release,
    launching_source,
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
from ._real_environments import (
    invoke_the_cli,
    publish_runtime,
    reported,
    runtime_record_requirement,
)
from ._separate_installation import SeparateInstallation, build_installation
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Hides every device from CUDA, so the judgement of a runtime built beside it
#: finds torch and no device to run it on.
_NO_VISIBLE_DEVICE: dict[str, str | None] = {"CUDA_VISIBLE_DEVICES": "-1"}


@pytest.fixture
def no_package_index(tmp_path: Path) -> dict[str, str | None]:
    """Name an empty directory as the index uv resolves packages from.

    An install that asks for this release then has nowhere to find it, and
    fails the way a real one does for a version no index serves. It is the one
    way to make a real install fail that does not depend on what any index
    happens to publish, and the one uv honours from its environment: the flag
    that turns indexes off has no variable.
    """
    index = tmp_path / "empty-index"
    index.mkdir()
    return {"UV_DEFAULT_INDEX": index.as_uri()}


def _interpreter_in(root: Path) -> str:
    """An interpreter inside an environment rooted at *root*, on disk."""
    interpreter = runtime_interpreter(root)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.touch()
    return str(interpreter)


def _launching(interpreter: str, capability: ComputeCapability) -> ServiceEnvironment:
    """The judgement a start has made of the environment that launched it."""
    return ServiceEnvironment(interpreter, capability)


def _publish_runtime(release: str | None = None, *, source: str | None = None) -> Path:
    """A complete runtime for *release* under the redirected status directory.

    The record is written by the writer a build uses. *source* names the origin
    it carries, and defaults to the origin this process's own distribution came
    from, which is the launcher every reading here is made from. The
    interpreter is a file and nothing more: what the selection reads of it is
    that it exists.
    """
    wanted = installed_release() if release is None else release
    directory = runtime_root() / wanted
    interpreter = _interpreter_in(directory)
    _record(
        directory,
        wanted,
        runtime_record_requirement(wanted, source),
        ServiceEnvironment(interpreter, ComputeCapability.READY),
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


#: Reports the uv a build would run through, in the environment it is given.
_FIND_UV = """
import json

from vaultspec_rag.service_runtime import uv_executable

print(json.dumps({"uv": uv_executable()}))
"""

#: Builds this release's service runtime, or reports the refusal, with what an
#: operator would read of it. A path given as the argument is written just before
#: the start asks for the runtime, so a caller can tell the program is running.
_ENSURE_THE_RUNTIME = """
import json
import pathlib
import sys

from vaultspec_rag.service_runtime import ServiceRuntimeError, ensure_service_runtime

for announced in json.loads(sys.argv[1]):
    pathlib.Path(announced).write_text("asking", encoding="utf-8")
try:
    runtime = ensure_service_runtime()
except ServiceRuntimeError as refusal:
    outcome = {
        "refused": {
            "code": refusal.code,
            "cause": refusal.cause,
            "command": refusal.command,
        }
    }
else:
    outcome = {
        "runtime": {
            "created": runtime.created,
            "directory": str(runtime.directory),
            "interpreter": runtime.interpreter,
            "source": runtime.source,
            "capability": str(runtime.environment.capability),
            "can_run_service": runtime.environment.can_run_service,
        }
    }
print(json.dumps(outcome))
"""


@pytest.fixture(scope="module")
def from_an_index(tmp_path_factory: pytest.TempPathFactory) -> SeparateInstallation:
    """An installation of this release as ``pip`` or ``uvx`` leaves one.

    Its distribution record names no archive, which is an install from a
    package index and the one an index requirement reproduces.
    """
    return build_installation(
        tmp_path_factory.mktemp("from-an-index"),
        version=installed_release(),
        direct_url=None,
    )


def _ran_in(
    installation: SeparateInstallation,
    program: str,
    environment: dict[str, str | None],
    *,
    timeout: float = 120.0,
) -> dict[str, object]:
    """Run *program* in *installation* with *environment* applied to it."""
    with managed_env(**environment):
        return installation.run(program, timeout=timeout)


def _await_the_file(path: Path, running: threading.Thread) -> None:
    """Block until *path* exists, or fail when *running* ends without writing it."""
    deadline = time.monotonic() + 60.0
    while not path.exists():
        assert running.is_alive(), f"the program ended without writing {path}"
        assert time.monotonic() < deadline, f"{path} was never written"
        time.sleep(0.05)


def _without_uv(directory: Path) -> dict[str, str | None]:
    """An environment in which no uv is named and none is on the search path."""
    directory.mkdir(parents=True, exist_ok=True)
    return {EnvVar.UV.value: None, EnvVar.PATH.value: str(directory)}


#: A wheel of this release that is not the one any launcher here was installed
#: from: the locally rebuilt archive an operator produces beside an index
#: install, carrying the same version and different bytes.
_A_REBUILT_WHEEL = "file:///rebuilt/vaultspec_rag-0.0.0-py3-none-any.whl"

#: Reports which interpreter a start would serve from, for a launcher whose
#: own judgement says it cannot serve, in the environment it is given.
_PLAN_THE_INTERPRETER = """
import json
import sys

from vaultspec_rag.operator_state._installation import ComputeCapability
from vaultspec_rag.operator_state._service_environment import ServiceEnvironment
from vaultspec_rag.service_runtime import launching_source, planned_service_interpreter

plan = planned_service_interpreter(
    ServiceEnvironment(sys.executable, ComputeCapability.CPU_ONLY_BUILD)
)
print(json.dumps({
    "source": str(plan.source),
    "interpreter": plan.interpreter,
    "origin": launching_source(),
}))
"""


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestWhoseRuntimeItIs:
    """A runtime serves the installation whose origin its record names.

    One version can be installed from two origins on one machine - an index
    wheel, and then a wheel rebuilt locally from the same version - and the
    two hold different package bytes. The release they report is identical, so
    it cannot tell them apart; the recorded origin is what can.
    """

    def test_a_same_release_runtime_from_another_origin_is_not_reused(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: a release does not identify an install.

        The record names this release and an archive this launcher was not
        installed from, so the environment it describes holds other package
        bytes under the same version, and serving a daemon from it would run a
        release the launcher never installed. Mutation check: comparing the
        release alone - dropping the source comparison from the completeness
        check - returns ``runtime`` here and fails on the source.
        """
        published = _publish_runtime(source=_A_REBUILT_WHEEL)
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED
        assert plan.interpreter is None
        # Nothing was removed: the next start rebuilds the directory in place.
        assert (published / RUNTIME_RECORD_NAME).is_file()

    def test_a_record_that_names_no_origin_is_not_reused(self, tmp_path: Path) -> None:
        """Guard assertion: an absent field is not a match.

        A record written before the origin was recorded at all names none, and
        a reuse check that reads a missing field as agreement is the defect
        itself. Mutation check: treating an absent source as this launcher's
        returns ``runtime`` here and fails on the source.
        """
        directory = _publish_runtime()
        record = json.loads(
            (directory / RUNTIME_RECORD_NAME).read_text(encoding="utf-8")
        )
        del record["source"]
        (directory / RUNTIME_RECORD_NAME).write_text(
            json.dumps(record), encoding="utf-8"
        )
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        plan = planned_service_interpreter(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert plan.source is ServiceInterpreterSource.RUNTIME_REQUIRED

    def test_an_index_install_is_not_served_a_rebuilt_wheels_runtime(
        self, from_an_index: SeparateInstallation
    ) -> None:
        """The two origins are both real distribution records, same version.

        The launcher is an installation of this release whose record names no
        archive, which is what an index install leaves, and it reads the
        runtime for itself in a fresh interpreter of its own. The runtime was
        built from a rebuilt wheel of the same version. Mutation check:
        comparing the release alone reports ``runtime`` here and fails on the
        source.
        """
        _publish_runtime(source=_A_REBUILT_WHEEL)

        plan = _ran_in(from_an_index, _PLAN_THE_INTERPRETER, {})

        assert plan["origin"] == INDEX_SOURCE
        assert plan["source"] == ServiceInterpreterSource.RUNTIME_REQUIRED.value

    def test_an_index_install_is_served_an_index_runtime(
        self, from_an_index: SeparateInstallation
    ) -> None:
        """The same runtime directory, recorded for the origin that reads it."""
        directory = _publish_runtime(source=INDEX_SOURCE)

        plan = _ran_in(from_an_index, _PLAN_THE_INTERPRETER, {})

        assert plan["origin"] == INDEX_SOURCE
        assert plan["source"] == ServiceInterpreterSource.RUNTIME.value
        assert plan["interpreter"] == str(runtime_interpreter(directory))

    def test_the_rebuilt_wheel_is_not_where_this_process_came_from(self) -> None:
        """The premise the in-process refusal rests on, from real metadata.

        The origin is read from this installation's own distribution record.
        Were it to read as the rebuilt wheel, the refusal above would hold for
        the wrong reason.
        """
        assert launching_source() != _A_REBUILT_WHEEL


@pytest.mark.unit
class TestTheUvTheBuildRunsThrough:
    """uv names itself to its children; otherwise it is found on PATH."""

    def test_the_uv_running_this_command_is_the_one_used(
        self, from_an_index: SeparateInstallation, tmp_path: Path
    ) -> None:
        named = tmp_path / "uv-from-uv"
        named.touch()

        found = _ran_in(from_an_index, _FIND_UV, {EnvVar.UV.value: str(named)})

        assert found["uv"] == str(named)

    def test_a_name_that_is_not_a_file_is_not_believed(
        self, from_an_index: SeparateInstallation, tmp_path: Path
    ) -> None:
        """Guard assertion: an exported name may point at nothing.

        Mutation check: returning the value unchecked yields the absent path
        here, and the start would then fail on a missing executable instead
        of on the environment it can describe.
        """
        found = _ran_in(
            from_an_index,
            _FIND_UV,
            {
                EnvVar.UV.value: str(tmp_path / "absent-uv"),
                EnvVar.PATH.value: str(tmp_path / "empty"),
            },
        )

        assert found["uv"] is None

    def test_an_absolute_uv_on_the_search_path_is_found(
        self, from_an_index: SeparateInstallation, tmp_path: Path
    ) -> None:
        directory = tmp_path / "bin"
        directory.mkdir()
        name = "uv.exe" if sys.platform == "win32" else "uv"
        executable = directory / name
        executable.write_text("", encoding="utf-8")
        executable.chmod(0o755)

        found = _ran_in(
            from_an_index,
            _FIND_UV,
            {EnvVar.UV.value: None, EnvVar.PATH.value: str(directory)},
        )

        assert isinstance(found["uv"], str)
        assert Path(found["uv"]).is_absolute()
        assert Path(found["uv"]).samefile(executable)

    def test_the_install_one_liner_is_the_one_for_this_platform(self) -> None:
        assert "astral.sh/uv/install.ps1" in uv_install_command("win32")
        assert "astral.sh/uv/install.sh" in uv_install_command("linux")
        assert "astral.sh/uv/install.sh" in uv_install_command("darwin")

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_without_uv_the_start_is_refused_with_that_one_command(
        self, from_an_index: SeparateInstallation, tmp_path: Path
    ) -> None:
        """Guard assertion: no uv is a refusal that names how to get one.

        The origin is an index, so the refusal cannot be the checkout's, which
        has a code of its own and a different command. Mutation check:
        dropping the command from the refusal fails the command assertion.
        """
        outcome = _ran_in(
            from_an_index, _ENSURE_THE_RUNTIME, _without_uv(tmp_path / "empty")
        )

        refused = reported(outcome, "refused")
        assert refused["code"] == ERROR_RUNTIME_UNSUPPORTED
        assert refused["command"] == uv_install_command()


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


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestBuildingAndPublishingTheRuntime:
    """Built in staging, judged, recorded, then published by one rename."""

    def test_a_failed_install_leaves_nothing_behind(
        self,
        from_an_index: SeparateInstallation,
        no_package_index: dict[str, str | None],
    ) -> None:
        """An incomplete build is deleted, so the next start begins afresh.

        uv creates the environment, then finds nothing that serves this
        release, and its own last line is what the refusal reports.
        """
        outcome = _ran_in(from_an_index, _ENSURE_THE_RUNTIME, no_package_index)

        refused = reported(outcome, "refused")
        assert refused["code"] == ERROR_RUNTIME_FAILED
        assert "uv failed to install the GPU stack" in str(refused["cause"])
        assert list(runtime_root().iterdir()) == [runtime_root() / ".runtime.lock"]

    def test_a_build_already_running_is_not_run_a_second_time(
        self,
        from_an_index: SeparateInstallation,
        no_package_index: dict[str, str | None],
    ) -> None:
        """Guard assertion: two builds would download the stack twice.

        The lock is held here by another process's own handle, and the start
        waits the full time the build allows for it before it says so. No
        index serves the release, so a start that went on to build would end in
        uv's refusal and not in this one. Mutation check: building outside the
        lock reaches uv, whose refusal fails the cause assertion.
        """
        from .._store_locks import FileLock

        runtime_root().mkdir(parents=True, exist_ok=True)
        holder = FileLock(runtime_root() / ".runtime.lock")
        assert holder.acquire()
        try:
            outcome = _ran_in(from_an_index, _ENSURE_THE_RUNTIME, no_package_index)
        finally:
            holder.release()

        refused = reported(outcome, "refused")
        assert refused["code"] == ERROR_RUNTIME_FAILED
        assert "already creating the service runtime" in str(refused["cause"])
        assert list(runtime_root().iterdir()) == [runtime_root() / ".runtime.lock"]

    @pytest.mark.torch
    def test_the_runtime_published_while_waiting_is_the_one_used(
        self,
        from_an_index: SeparateInstallation,
        no_package_index: dict[str, str | None],
        tmp_path: Path,
    ) -> None:
        """Two starts racing end with one runtime, not two.

        One start holds the build lock while another waits for it. The first
        publishes, which takes longer than the second needs to ask and find
        nothing, and lets go, and the second finds the runtime when it takes the
        lock. No index serves the release, so a start that built anyway would
        end in uv's refusal. Mutation check: skipping the look for a published
        runtime once the lock is held builds, and fails on the outcome.
        """
        from .._store_locks import FileLock

        runtime_root().mkdir(parents=True, exist_ok=True)
        holder = FileLock(runtime_root() / ".runtime.lock")
        assert holder.acquire()
        asking = tmp_path / "asking"
        waiting: list[dict[str, object]] = []
        with managed_env(**no_package_index):
            second = threading.Thread(
                target=lambda: waiting.append(
                    from_an_index.run(_ENSURE_THE_RUNTIME, str(asking))
                )
            )
            second.start()
            try:
                _await_the_file(asking, second)
                # The start waiting for the lock is an installation from an
                # index, and reuses a runtime built from one.
                published = publish_runtime(source=INDEX_SOURCE)
            finally:
                holder.release()
            second.join(timeout=120)

        (outcome,) = waiting
        runtime = reported(outcome, "runtime")
        assert runtime["created"] is False
        assert runtime["directory"] == str(published)


class _Built(NamedTuple):
    """What building the GPU stack for this release produced, or refused."""

    status_dir: Path
    wheel: Path
    first: dict[str, object]
    again: dict[str, object]


@pytest.fixture(scope="module")
def wheel_of_this_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A wheel built from this checkout, the archive a runtime is built from."""
    uv = uv_executable()
    if uv is None:
        pytest.fail("uv is required to build a wheel of this checkout")
    checkout = Path(__file__).resolve().parents[3]
    wheels = tmp_path_factory.mktemp("wheels")
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
    return next(iter(sorted(wheels.glob("*.whl"))))


def _built_by(
    tmp_path_factory: pytest.TempPathFactory,
    wheel: Path,
    environment: dict[str, str | None],
) -> _Built:
    """Build the runtime from *wheel*, then ask for it again with no uv at all.

    The installation's record names the wheel as where this release came from,
    so the requirement is that archive with the GPU extra and uv creates the
    environment and installs the stack in it for real. The second ask is the one
    an everyday start makes, in an environment where no uv can be found, so a
    runtime that was present could not have cost one.
    """
    status_dir = tmp_path_factory.mktemp("status")
    installation = build_installation(
        tmp_path_factory.mktemp("from-a-wheel"),
        version=installed_release(),
        direct_url=json.dumps({"url": wheel.as_uri(), "archive_info": {}}),
    )
    redirected: dict[str, str | None] = {
        EnvVar.STATUS_DIR.value: str(status_dir),
        EnvVar.QDRANT_STORAGE_DIR.value: str(status_dir / "qdrant"),
    }
    first = _ran_in(
        installation, _ENSURE_THE_RUNTIME, redirected | environment, timeout=3600
    )
    again = _ran_in(
        installation,
        _ENSURE_THE_RUNTIME,
        redirected | environment | _without_uv(status_dir / "no-uv"),
    )
    return _Built(status_dir, wheel, first, again)


@pytest.fixture(scope="module")
def built_runtime(
    tmp_path_factory: pytest.TempPathFactory, wheel_of_this_checkout: Path
) -> _Built:
    """This release's runtime, built from a wheel of this checkout."""
    return _built_by(tmp_path_factory, wheel_of_this_checkout, {})


@pytest.fixture(scope="module")
def refused_runtime(
    tmp_path_factory: pytest.TempPathFactory, wheel_of_this_checkout: Path
) -> _Built:
    """The same build, with every device hidden from the runtime's torch."""
    return _built_by(tmp_path_factory, wheel_of_this_checkout, _NO_VISIBLE_DEVICE)


@pytest.mark.integration
@pytest.mark.cuda
class TestARuntimeBuiltForReal:
    """The whole creation path, with the real uv and the real judgement.

    uv creates the environment and installs this checkout's own wheel with the
    GPU stack from the CUDA index, and the published runtime is judged by a
    child of its own interpreter, which imports torch there. The status
    directory is redirected, so nothing here reaches the service directory of
    the operator's own installation.
    """

    def test_a_built_runtime_is_published_with_its_completion_record(
        self, built_runtime: _Built
    ) -> None:
        runtime = reported(built_runtime.first, "runtime")

        directory = Path(str(runtime["directory"]))
        record = json.loads(
            (directory / RUNTIME_RECORD_NAME).read_text(encoding="utf-8")
        )
        assert runtime["created"] is True
        assert directory == built_runtime.status_dir / "runtime" / installed_release()
        assert runtime["source"] == built_runtime.wheel.as_uri()
        assert Path(str(runtime["interpreter"])).is_file()
        assert runtime["can_run_service"] is True
        assert record["release"] == installed_release()
        assert record["source"] == built_runtime.wheel.as_uri()
        assert record["capability"] == str(ComputeCapability.READY)

    def test_nothing_staged_survives_a_published_build(
        self, built_runtime: _Built
    ) -> None:
        root = built_runtime.status_dir / "runtime"

        assert [entry.name for entry in root.iterdir() if entry.is_dir()] == [
            installed_release()
        ]

    def test_a_present_runtime_costs_no_uv_call(self, built_runtime: _Built) -> None:
        """Guard assertion: a complete runtime must cost no network.

        The second ask runs where no uv can be found, so a build would be
        refused for want of one. Mutation check: building unconditionally
        reaches the missing uv and fails on the outcome.
        """
        built = reported(built_runtime.first, "runtime")
        again = reported(built_runtime.again, "runtime")

        assert again["created"] is False
        assert again["directory"] == built["directory"]

    def test_a_runtime_that_cannot_serve_is_never_published(
        self, refused_runtime: _Built
    ) -> None:
        """Guard assertion: no CPU runtime is ever accepted.

        Mutation check: accepting a runtime the judgement refused publishes it
        and returns a runtime where the refusal is expected, which fails the
        first assertion; every later start would then run a daemon that cannot
        load a model.
        """
        refused = reported(refused_runtime.first, "refused")

        assert refused["code"] == ERROR_RUNTIME_NO_GPU
        root = refused_runtime.status_dir / "runtime"
        assert not (root / installed_release()).exists()
        assert [entry.name for entry in root.iterdir()] == [".runtime.lock"]
        assert ComputeCapability.NO_DEVICE.label in str(refused["cause"])

    def test_a_runtime_that_cannot_serve_never_offers_the_start_again(
        self, refused_runtime: _Built
    ) -> None:
        """Guard assertion: the refusal offered the command that produced it.

        The capability's own remediation is written for an environment the
        operator installed, and it ends by saying to start again - which built
        this runtime and would build the same one again, so the operator
        loops. A runtime whose device is missing therefore states its cause
        and offers the one bare command that can change the answer.

        Mutation check: reusing ``capability.remediation`` here puts a sentence
        in place of the command and fails the first assertion.
        """
        refused = reported(refused_runtime.first, "refused")

        assert refused["command"] == DRIVER_CHECK_COMMAND
        # The premise: the remediation that used to be reused here is the one
        # that sends the operator back to the start that built this runtime.
        assert "start the service again" in str(ComputeCapability.NO_DEVICE.remediation)
        assert server_start_command() not in str(refused["command"])


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


#: Judges the launcher the way a start does and, when it cannot serve, asks the
#: runtime creation for the refusal, reporting every document it wrote.
_REFUSE_THE_RUNTIME = """
import contextlib
import io
import json
import sys

import typer

from vaultspec_rag.cli._core import _build_console
from vaultspec_rag.cli._progress import StartupStatusReporter
from vaultspec_rag.cli._service_start import (
    _created_service_runtime,
    _planned_start_environment,
)

planned = _planned_start_environment(sys.executable)
reporter = StartupStatusReporter(
    json_mode=True,
    console=_build_console(interactive=False, file=io.StringIO()),
    interactive=False,
)
written = io.StringIO()
exit_code = None
with contextlib.redirect_stdout(written):
    try:
        with reporter as progress:
            _created_service_runtime(json_mode=True, progress=progress)
    except typer.Exit as stop:
        exit_code = stop.exit_code
print(json.dumps({
    "planned_a_runtime": planned is None,
    "exit_code": exit_code,
    "stdout": written.getvalue(),
}))
"""


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_status_dir")
class TestTheStartEnvelope:
    """A refused runtime is one envelope on the start's one exit path."""

    def test_a_json_start_emits_exactly_one_envelope_for_the_refusal(
        self, from_an_index: SeparateInstallation, tmp_path: Path
    ) -> None:
        """The plan sends this launcher to a runtime, and creating it is refused.

        The launcher is the interpreter of an installation with its device
        hidden, so it cannot serve whatever it holds, and it has no uv to build
        a runtime with. The plan is what sends it to the runtime; the refusal
        comes from creating it, which a start only reaches once its guards
        have passed.
        """
        ran = _ran_in(
            from_an_index,
            _REFUSE_THE_RUNTIME,
            _without_uv(tmp_path / "empty") | _NO_VISIBLE_DEVICE,
        )

        assert ran["planned_a_runtime"] is True
        assert ran["exit_code"] != 0
        documents = [
            json.loads(line)
            for line in str(ran["stdout"]).splitlines()
            if line.strip().startswith("{")
        ]
        assert len(documents) == 1, f"expected one envelope, got {documents}"
        assert documents[0]["error"] == ERROR_RUNTIME_UNSUPPORTED
        # One command, and only that one: the envelope carries what the
        # operator would have read.
        assert documents[0]["data"]["next_actions"] == [uv_install_command()]

    def test_every_next_action_a_refusal_offers_is_a_bare_command(self) -> None:
        """Guard assertion: a next action is run, not read.

        A start reports the refusal's command as a next action, which a
        broker runs outright and a person pastes into a shell, so a sentence
        there is not a remedy but a command that fails. Every capability a
        runtime can be refused for either offers nothing or offers one bare
        command; the explanation is the cause sentence.

        Mutation check: returning ``capability.remediation`` for any
        capability puts a sentence in the table and fails on the backtick or
        the full stop it carries.
        """
        from ..operator_state._installation import DRIVER_CHECK_COMMAND
        from ..service_runtime import _runtime_refusal_command

        offered = {
            capability: _runtime_refusal_command(capability)
            for capability in ComputeCapability
        }

        assert offered[ComputeCapability.CPU_ONLY_BUILD] is None
        assert offered[ComputeCapability.TORCH_MISSING] is None
        assert offered[ComputeCapability.NOT_APPLICABLE] is None
        assert offered[ComputeCapability.NO_DEVICE] == DRIVER_CHECK_COMMAND
        for command in offered.values():
            if command is None:
                continue
            assert "`" not in command
            assert not command.endswith(".")


@pytest.fixture
def a_taken_port() -> Iterator[int]:
    """A loopback port something is listening on, released afterwards."""
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    try:
        yield held.getsockname()[1]
    finally:
        held.close()


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
class TestWhenTheRuntimeIsBuilt:
    """Nothing is downloaded for a start that something can still refuse."""

    def test_a_start_the_port_guard_refuses_builds_no_runtime(
        self,
        from_an_index: SeparateInstallation,
        no_package_index: dict[str, str | None],
        a_taken_port: int,
        tmp_path: Path,
    ) -> None:
        """Guard assertion: a refusal that followed a multi-gigabyte download.

        The runtime was created while the environment was being resolved,
        which ran before the port and machine guards, so a start refused for
        a taken port had already fetched the whole GPU stack. Creation now
        runs after every guard that can refuse the start.

        The start is the real command, run from an installation with its
        device hidden, so the managed runtime is what would serve it. No
        index serves the release, so a build would end in uv's refusal rather
        than a download. Creating the runtime is what makes its directory, so
        the directory not existing is the proof that creation was never
        reached.

        Mutation check: creating the runtime during selection again reaches
        the build before the port guard, which reports the runtime's own
        refusal instead of the taken port and creates its directory - failing
        the error assertion and the directory assertion.
        """
        with managed_env(**_NO_VISIBLE_DEVICE, **no_package_index):
            (result,) = invoke_the_cli(
                from_an_index,
                [
                    "--target",
                    str(tmp_path),
                    "server",
                    "start",
                    "--json",
                    "--port",
                    str(a_taken_port),
                ],
                cwd=tmp_path,
            )

        assert json.loads(result["stdout"])["error"] == "port_in_use"
        assert not runtime_root().exists()
