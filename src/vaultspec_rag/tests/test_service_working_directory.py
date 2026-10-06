"""The resident service does not live in the directory it was started from.

``server start`` is typed inside a project checkout, and the service it
starts outlives the command by days. Left in that directory, the service
resolves bare program names and relative paths against the checkout, reads
the checkout's private settings store, and on Windows holds the directory
open so the checkout cannot be renamed or removed.

The service is started here through the production spawn, with everything it
would do after its interpreter starts replaced by a stand-in: a start-up hook
on the import path notices the service's own command line, writes down what
the process can see, and waits to be told to stop. So the command line, the
environment, the detach flags and the working directory are the real ones,
and no model, port or managed state is touched. No real service is started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from .._process_probe import wait_for_exit
from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..config._types import EnvVar
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._planted_programs import plant_marking_program
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_PLANTED = "vaultspec-rag-start-directory-probe"

# Runs in every interpreter started with the bootstrap directory on its import
# path, and acts only in the one whose command line is the service's.
_STAND_IN = """
import json, os, shutil, sys, time
from pathlib import Path
if any(sys.orig_argv[i:i + 2] == ['-m', 'vaultspec_rag.server']
       for i in range(len(sys.orig_argv) - 1)):
    root = Path(__ROOT__)
    seen = {
        'pid': os.getpid(),
        'cwd': os.getcwd(),
        'safe_path': bool(sys.flags.safe_path),
        'lookup': shutil.which(__PLANTED__),
        'settings': {name: os.environ.get(name) for name in __SETTINGS__},
        'means': {name: os.path.abspath(os.environ[name])
                  for name in __SETTINGS__ if os.environ.get(name)},
    }
    witness = root / 'service.seen.tmp'
    witness.write_text(json.dumps(seen), encoding='utf-8')
    witness.replace(root / 'service.seen')
    # Detached from the test that started it, so it must end by itself: a
    # test process killed before it writes the stop file would otherwise
    # leave this one polling for ever.
    leave_by = time.monotonic() + __LIFETIME__
    while not (root / 'stop').exists() and time.monotonic() < leave_by:
        time.sleep(.05)
    os._exit(0)
"""

#: The longest a stand-in service lives when nobody tells it to stop.
_STAND_IN_LIFETIME_SECONDS = 120

# The starting command: resolves the log and the discovery file the way the
# command line does, spawns through the production function, and leaves.
_START = """
import json, os, sys, time
from pathlib import Path
from vaultspec_rag.cli._process import _spawn_service
from vaultspec_rag.cli._service_status import _log_file
from vaultspec_rag.serviceclient._discovery import _status_file
root = Path(sys.argv[1])
log = _log_file()
log.parent.mkdir(parents=True, exist_ok=True)
launcher = _spawn_service(int(sys.argv[2]), log, timeout=60)
deadline = time.monotonic() + 60
while not (root / 'service.seen').exists():
    assert time.monotonic() < deadline, 'the stand-in service never started'
    time.sleep(.01)
print(json.dumps({'launcher': launcher,
                  'discovery': os.path.abspath(_status_file())}), flush=True)
"""

_SETTINGS = (
    EnvVar.STATUS_DIR.value,
    EnvVar.QDRANT_STORAGE_DIR.value,
    EnvVar.HF_HOME.value,
)


class _Started:
    """What the starting command and the stand-in service each reported."""

    def __init__(self, started: dict[str, object], seen: dict[str, object]) -> None:
        self.launcher = cast("int", started["launcher"])
        self.discovery = cast("str", started["discovery"])
        self.pid = cast("int", seen["pid"])
        self.cwd = cast("str", seen["cwd"])
        self.safe_path = seen["safe_path"]
        self.lookup = seen["lookup"]
        self.settings = cast("dict[str, str | None]", seen["settings"])
        self.means = cast("dict[str, str]", seen["means"])


class _StandInService:
    """Start the stand-in from a directory, and stop it however the test ends."""

    def __init__(
        self, root: Path, *, lifetime: float = _STAND_IN_LIFETIME_SECONDS
    ) -> None:
        self._root = root
        self._lifetime = lifetime
        self._pids: list[int] = []

    def start(self, start_directory: Path, **settings: str) -> _Started:
        bootstrap = self._root / "bootstrap"
        bootstrap.mkdir()
        (bootstrap / "sitecustomize.py").write_text(
            _STAND_IN.replace("__ROOT__", repr(str(self._root)))
            .replace("__PLANTED__", repr(_PLANTED))
            .replace("__SETTINGS__", repr(_SETTINGS))
            .replace("__LIFETIME__", repr(self._lifetime)),
            encoding="utf-8",
        )
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"
        }
        environment["PYTHONPATH"] = os.pathsep.join(
            (str(bootstrap), environment.get("PYTHONPATH", ""))
        )
        # A leading empty entry means the working directory to every lookup,
        # so the stand-in's own lookup below searches wherever it is running.
        environment["PATH"] = os.pathsep.join(("", environment.get("PATH", "")))
        environment.update(settings)
        result = subprocess.run(
            [sys.executable, "-c", _START, str(self._root), str(free_loopback_port())],
            cwd=start_directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        started: object = json.loads(result.stdout.strip().splitlines()[-1])
        seen: object = json.loads(
            (self._root / "service.seen").read_text(encoding="utf-8")
        )
        assert isinstance(started, dict)
        assert isinstance(seen, dict)
        report = _Started(
            cast("dict[str, object]", started), cast("dict[str, object]", seen)
        )
        self._pids += [report.pid, report.launcher]
        return report

    def stop(self) -> None:
        # The stand-in polls for this file, so one that started after a failed
        # start still leaves, whether or not its pid was ever learned.
        (self._root / "stop").touch()
        for pid in self._pids:
            assert wait_for_exit(pid, timeout=20), f"stand-in process {pid} survived"


@pytest.fixture
def stand_in(tmp_path: Path) -> Generator[_StandInService]:
    service = _StandInService(tmp_path)
    try:
        yield service
    finally:
        service.stop()


def test_a_stand_in_nobody_stops_ends_by_itself(tmp_path: Path) -> None:
    """The detached stand-in cannot outlive a test run that never stops it.

    It is started through the production spawn, which detaches it from this
    process, so nothing here would end it if the stop file were never
    written. Shown to fail by letting the stand-in wait for the stop file
    alone: it is still running when the wait gives up. Passes with its own
    deadline restored.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    service = _StandInService(tmp_path, lifetime=2.0)
    try:
        started = service.start(checkout, **_managed(tmp_path))

        assert wait_for_exit(started.pid, timeout=30), "the stand-in outlived its bound"
        assert not (tmp_path / "stop").exists()
    finally:
        service.stop()


def _managed(tmp_path: Path) -> dict[str, str]:
    """Absolute managed directories of this test's own."""
    return {
        EnvVar.STATUS_DIR.value: str(tmp_path / "status"),
        EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "storage"),
    }


def _same_directory(left: str, right: Path) -> bool:
    return os.path.samefile(left, right)


def test_the_service_runs_in_the_managed_directory_not_where_it_was_started(
    tmp_path: Path, stand_in: _StandInService
) -> None:
    """Nothing the service resolves by name comes from the start directory.

    The start directory plants a program, and the service asks the standard
    lookup for it with a search path that includes the working directory.
    Shown to fail by removing the working directory from the spawn: the
    service then runs where the start was typed, the first assertion fires,
    and the lookup returns the planted program. Passes with it restored.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    plant_marking_program(checkout, _PLANTED)

    started = stand_in.start(checkout, **_managed(tmp_path))

    assert _same_directory(started.cwd, tmp_path / "status"), started.cwd
    assert not _same_directory(started.cwd, checkout)
    assert started.lookup is None, "the service resolved a program from the checkout"
    assert started.safe_path is True


def test_a_checkout_can_be_renamed_while_the_service_started_in_it_runs(
    tmp_path: Path, stand_in: _StandInService
) -> None:
    """The service does not hold the directory it was started from.

    On Windows a process's working directory cannot be renamed or removed
    while the process lives. Shown to fail there by removing the working
    directory from the spawn: the rename is refused with a sharing violation.
    Elsewhere a rename always succeeds, and the test above is what holds the
    directory. Passes with it restored.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    started = stand_in.start(checkout, **_managed(tmp_path))
    renamed = checkout.rename(tmp_path / "checkout-renamed")

    assert renamed.is_dir()
    assert not checkout.exists()
    assert not wait_for_exit(started.pid, timeout=0.2), "the stand-in had exited"


def test_a_relative_directory_setting_means_one_place_to_both_processes(
    tmp_path: Path, stand_in: _StandInService
) -> None:
    """The starting command and the service agree on where the service lives.

    Each directory is given as a relative path, which the starting command
    takes against the directory it was typed in. The service runs elsewhere,
    so it is handed the absolute path each one names. Shown to fail by not
    rewriting the settings: the service takes the status directory against
    its own working directory, lands one level too deep, and the first
    assertion fires. Passes with the rewrite restored.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    started = stand_in.start(
        checkout,
        **{
            EnvVar.STATUS_DIR.value: "state",
            EnvVar.QDRANT_STORAGE_DIR.value: os.path.join("state", "storage"),
            EnvVar.HF_HOME.value: "hub",
        },
    )

    status = started.means[EnvVar.STATUS_DIR.value]
    assert status == os.path.dirname(started.discovery), (
        "the service and the command that started it look for the discovery "
        "file in different directories"
    )
    assert _same_directory(status, checkout / "state")
    assert _same_directory(started.cwd, checkout / "state")
    assert started.settings[EnvVar.QDRANT_STORAGE_DIR.value] == os.path.abspath(
        checkout / "state" / "storage"
    )
    assert started.settings[EnvVar.HF_HOME.value] == os.path.abspath(checkout / "hub")


@pytest.mark.parametrize(
    "variable",
    [
        EnvVar.STATUS_DIR,
        EnvVar.QDRANT_STORAGE_DIR,
        EnvVar.HF_HOME,
        EnvVar.HF_HUB_CACHE,
        EnvVar.UV_CACHE_DIR,
        EnvVar.UV_TOOL_DIR,
        EnvVar.TEMP,
        EnvVar.TMP,
        EnvVar.TMPDIR,
    ],
)
def test_only_a_relative_directory_is_rewritten(
    variable: EnvVar, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative value becomes the path it names here; nothing else moves.

    A value led by ``~`` is expanded by its reader against the home
    directory, which both processes share, and an absolute value already
    means one place.
    """
    monkeypatch.chdir(tmp_path)
    home_relative = os.path.join("~", "managed")
    absolute = str(tmp_path / "elsewhere")

    def handed_to_the_service(value: str) -> str:
        monkeypatch.setenv(variable.value, value)
        return _build_service_child_env(_ServiceChildEnvRequest())[variable.value]

    assert handed_to_the_service("managed") == os.path.abspath("managed")
    assert handed_to_the_service(home_relative) == home_relative
    assert handed_to_the_service(absolute) == absolute


def test_settings_relative_to_a_root_or_the_status_directory_are_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """These are relative by definition, to something other than a process."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(EnvVar.DATA_DIR.value, os.path.join(".vault", "data"))
    monkeypatch.setenv(EnvVar.QDRANT_DIR.value, "qdrant")
    monkeypatch.setenv(EnvVar.LOG_FILE.value, "service.log")

    env = _build_service_child_env(_ServiceChildEnvRequest())

    assert env[EnvVar.DATA_DIR.value] == os.path.join(".vault", "data")
    assert env[EnvVar.QDRANT_DIR.value] == "qdrant"
    assert env[EnvVar.LOG_FILE.value] == "service.log"
