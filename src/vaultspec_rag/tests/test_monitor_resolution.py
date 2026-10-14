"""Which monitor an installation runs, and what it is held to before it runs.

The monitor is a native executable started on every service start, so what
decides which file that is has to be the file's own content and never its
name or its place on a search path. These tests drive the real resolver over
real files: an executable whose bytes are the pinned ones, one whose bytes
are not, one planted in the working directory, and one named by the operator
settings.

The pin is the resolver's argument, so a stand-in release is a value a test
passes rather than a trust constant it writes: no case here asks what this
checkout's own generated digests say, and none can be answered by a monitor
this checkout compiled for itself.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

import pytest

from tools.monitor.pins import GeneratedPins

from ..config._types import EnvVar
from ..monitor_runtime._assets import monitor_archive_name, monitor_executable_name
from ..monitor_runtime._errors import MonitorError
from ..monitor_runtime._launch import verify_monitor
from ..monitor_runtime._pins import MonitorPin, PinProvenance
from ..monitor_runtime._resolve import (
    MONITOR_BINARY_BUSY,
    MONITOR_BINARY_INVALID,
    MONITOR_BINARY_UNVERIFIED,
    MONITOR_NOT_INSTALLED,
    MonitorSource,
    managed_monitor_path,
    resolve_monitor,
    resolve_pinned_monitor,
)
from ..native_binary._install import file_sha256
from ..native_binary._targets import host_target
from ._planted_programs import stock_search_state
from ._separate_installation import INSTALLED_FROM_A_WHEEL, build_installation
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_VERSION = "9.9.9"
#: The bytes a stand-in monitor is made of. Its digest is the pin.
_MONITOR = b"#!stand-in monitor\x00" * 64
_OTHER = b"#!a monitor of some other build\x00" * 64
#: What an archive install's launcher is called on this platform.
_LAUNCHER_SUFFIX = ".exe" if sys.platform == "win32" else ""

#: Run in a separate installation: resolve the monitor a pin, passed as the
#: one argument, admits, and report what was chosen.
_RESOLVE_THE_PINNED_MONITOR = """
import json
import sys

from vaultspec_rag.monitor_runtime._pins import MonitorPin, PinProvenance
from vaultspec_rag.monitor_runtime._resolve import resolve_pinned_monitor

fields = json.loads(sys.argv[1])[0]
pin = MonitorPin(**{**fields, "provenance": PinProvenance(fields["provenance"])})
resolved = resolve_pinned_monitor(pin)
print(json.dumps({
    "path": None if resolved is None else str(resolved.path),
    "source": None if resolved is None else str(resolved.source),
}))
"""

#: Run in a separate installation: a launch, and what it refused with.
_LAUNCH_THE_MONITOR = """
import json

from vaultspec_rag.monitor_runtime._errors import MonitorError
from vaultspec_rag.monitor_runtime._resolve import monitor_for_launch

try:
    monitor_for_launch()
except MonitorError as refused:
    print(json.dumps({"error": refused.error, "message": str(refused)}))
else:
    print(json.dumps({"error": None, "message": ""}))
"""


def _pin(executable: bytes = _MONITOR) -> MonitorPin:
    """The pin a release of *executable* would carry for this host."""
    target = host_target()
    return MonitorPin(
        provenance=PinProvenance.RELEASE,
        version=_VERSION,
        tag=f"vaultspec-rag-v{_VERSION}",
        target=target,
        archive_name=monitor_archive_name(_VERSION, target),
        archive_sha256="a" * 64,
        executable_name=monitor_executable_name(target),
        executable_sha256=file_sha256_of(executable),
    )


def _released_as(pin: MonitorPin) -> GeneratedPins:
    """The generated digests of the release *pin* describes, as a build writes them."""
    return GeneratedPins(
        provenance=pin.provenance,
        version=pin.version,
        tag=pin.tag,
        archives={pin.target: pin.archive_sha256},
        executables={pin.target: pin.executable_sha256},
    )


def file_sha256_of(payload: bytes) -> str:
    """The digest *payload* hashes to, computed the way the resolver does."""
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _install(path: Path, payload: bytes) -> Path:
    """Write *payload* at *path* as an installed executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if sys.platform != "win32":
        path.chmod(0o700)
    return path


@pytest.fixture
def managed(tmp_path: Path) -> Generator[Path]:
    """A managed service directory of this test's own, and no monitor in it."""
    status = tmp_path / "status"
    status.mkdir(parents=True, exist_ok=True)
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(status),
            EnvVar.MONITOR_BINARY.value: None,
            EnvVar.MONITOR_BINARY_SHA256.value: None,
        }
    ):
        yield status


@pytest.fixture
def sibling(tmp_path: Path) -> Generator[Path]:
    """A real place this installation's programs are, that a test can own.

    An archive install is a launcher that carries this package as a wheel and
    installs it into a cache environment of its own on first run, so the
    monitor it shipped with sits beside the launcher rather than in that
    environment. That makes the launcher's own directory one of the places
    resolution looks, and the only one a test can put a file in without
    writing beside the real interpreter. The launcher states its path exactly
    as it does in a real install, and nothing about the lookup is replaced.

    A monitor this checkout compiled for itself stays where it is and cannot
    answer in this one's place: the stand-in release's pin admits its own
    bytes and nothing else.

    Yields:
        The launcher's own directory.
    """
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    launcher = _install(bundle / f"vaultspec-rag{_LAUNCHER_SUFFIX}", b"launcher")
    with managed_env(**{EnvVar.PYAPP.value: str(launcher)}):
        yield bundle


@pytest.mark.usefixtures("managed")
class TestWhatIsChosen:
    def test_the_managed_install_is_chosen_when_its_content_is_the_pinned_one(
        self,
    ) -> None:
        pin = _pin()
        installed = _install(managed_monitor_path(pin.version, pin.target), _MONITOR)

        resolved = resolve_pinned_monitor(pin)

        assert resolved is not None
        assert resolved.path == installed
        assert resolved.source is MonitorSource.MANAGED_INSTALL
        assert resolved.sha256 == pin.executable_sha256
        assert resolved.version == _VERSION
        # Keyed by release version and target, so one host serves every
        # environment of that release and no other.
        assert installed.parent.name == pin.target
        assert installed.parent.parent.name == _VERSION

    def test_a_monitor_beside_the_installation_is_chosen_before_the_managed_one(
        self, sibling: Path
    ) -> None:
        """An archive install runs the monitor it shipped with.

        The layout is the real one: the monitor beside the launcher the
        install was started by, with the launcher stating its own path.

        Mutation: yielded the managed install before the sibling. Observed
        this test fail on the source assertion, with the managed install
        chosen. Restored; passes.

        Mutation: left the launcher's own directory out of the places this
        installation's programs are in. Observed this test fail on the "not
        None" assertion, which is an archive install downloading a monitor it
        already has. Restored; passes.
        """
        _install(managed_monitor_path(_pin().version, _pin().target), _MONITOR)
        beside = _install(sibling / monitor_executable_name(host_target()), _MONITOR)

        resolved = resolve_pinned_monitor(_pin())

        assert resolved is not None
        assert resolved.path == beside.resolve()
        assert resolved.source is MonitorSource.INSTALLATION_SIBLING

    def test_a_sibling_that_is_not_this_release_s_is_passed_over(
        self, sibling: Path
    ) -> None:
        """A bundle beside an upgraded wheel does not hold the wheel back.

        Mutation: admitted either candidate without comparing its content.
        Observed this test fail on the path assertion, with the other
        build's monitor chosen, and the next case fail too. Restored;
        passes.
        """
        _install(sibling / monitor_executable_name(host_target()), _OTHER)
        pin = _pin()
        installed = _install(managed_monitor_path(pin.version, pin.target), _MONITOR)

        resolved = resolve_pinned_monitor(pin)

        assert resolved is not None
        assert resolved.path == installed
        assert resolved.source is MonitorSource.MANAGED_INSTALL

    def test_nothing_installed_resolves_to_nothing(self) -> None:
        """Absent is absent: provisioning answers it, not an unverified file."""
        assert resolve_pinned_monitor(_pin()) is None

    def test_a_managed_file_that_is_not_this_release_s_counts_as_absent(self) -> None:
        """The managed directory holds this release's monitor and nothing else.

        Nothing of anyone's is ever copied there, so a file that is not the
        pinned one is not a modification to preserve: it is reported as
        absent and the provisioner replaces it, which is what keeps the path
        automatic.
        """
        pin = _pin()
        _install(managed_monitor_path(pin.version, pin.target), _OTHER)

        assert resolve_pinned_monitor(pin) is None


@pytest.mark.usefixtures("managed")
class TestSeveralPlacesHoldOneName:
    def test_a_monitor_of_another_build_in_the_environment_masks_nothing(
        self, sibling: Path, tmp_path: Path
    ) -> None:
        """Every place is judged by content, so their order cannot decide.

        An upgraded launcher installs a new wheel into a new cache
        environment, and an older monitor left in that environment's scripts
        directory is still a file of the right name, found first. Resolving
        the first one found would hand the install that one and refuse it.

        The environment is a real one built for the case: an interpreter of
        its own, whose own scripts directory holds the older monitor, resolving
        in a fresh interpreter beside a launcher that holds the right one and
        states its path as a launcher does. The directory the interpreter
        reports is the one the older monitor is put in.

        Mutation: offered only the first match. Observed this test fail on
        the answer it compares, with nothing resolved: the older monitor was
        the only candidate and its content is not this release's. Restored;
        passes.
        """
        installed = build_installation(
            tmp_path / "installation",
            version=_VERSION,
            direct_url=INSTALLED_FROM_A_WHEEL,
            own_environment=True,
        )
        _install(installed.scripts / monitor_executable_name(host_target()), _OTHER)
        beside = _install(sibling / monitor_executable_name(host_target()), _MONITOR)

        resolved = installed.run(_RESOLVE_THE_PINNED_MONITOR, asdict(_pin()))

        assert resolved == {
            "path": str(beside.resolve()),
            "source": str(MonitorSource.INSTALLATION_SIBLING),
        }


@pytest.mark.usefixtures("managed")
class TestThePathIsNotSearched:
    def test_a_monitor_on_the_path_is_never_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Where a start was typed cannot decide what the start runs.

        The planted file's content is the pinned content, so nothing but
        where it sits can be what refuses it. A stock Windows machine looks
        in the working directory before anywhere else for a bare program
        name, and the ``PATH`` here holds an empty entry, a relative entry
        and the checkout, which mean the same thing elsewhere.

        Mutation: added the PATH tier back to the lookup. Observed this test
        fail on the "resolved to nothing" assertion, with the planted file
        resolved. Restored; passes.
        """
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        stock_search_state(monkeypatch, checkout, checkout)
        _install(checkout / monitor_executable_name(host_target()), _MONITOR)

        assert resolve_pinned_monitor(_pin()) is None


@pytest.mark.usefixtures("managed")
class TestTheOperatorsOwn:
    def test_a_declared_executable_wins_and_is_held_to_its_declared_digest(
        self, tmp_path: Path
    ) -> None:
        """An operator who named an executable is never handed another."""
        pin = _pin()
        _install(managed_monitor_path(pin.version, pin.target), _MONITOR)
        theirs = _install(tmp_path / "theirs" / "monitor", _OTHER)

        with managed_env(
            **{
                EnvVar.MONITOR_BINARY.value: str(theirs),
                EnvVar.MONITOR_BINARY_SHA256.value: file_sha256(theirs),
            }
        ):
            resolved = resolve_monitor()

            assert resolved is not None
            assert resolved.path == theirs
            assert resolved.source is MonitorSource.OPERATOR_SETTING
            assert resolved.sha256 == file_sha256(theirs)
            # Nobody has established which release an operator's build is.
            assert resolved.version == ""

    def test_half_a_pair_is_refused_and_never_falls_through(
        self, tmp_path: Path
    ) -> None:
        """A path with no digest is a refusal, not a reason to run something else.

        Mutation: swallowed the half-pair refusal and carried on. Observed
        this test fail on the ``monitor_binary_invalid`` code, having
        reached past the operator settings to report something else about
        this installation instead. Restored; passes.
        """
        pin = _pin()
        _install(managed_monitor_path(pin.version, pin.target), _MONITOR)
        theirs = _install(tmp_path / "theirs" / "monitor", _OTHER)

        with (
            managed_env(
                **{
                    EnvVar.MONITOR_BINARY.value: str(theirs),
                    EnvVar.MONITOR_BINARY_SHA256.value: None,
                }
            ),
            pytest.raises(MonitorError) as refused,
        ):
            resolve_monitor()

        assert refused.value.error == MONITOR_BINARY_INVALID


@pytest.mark.usefixtures("managed")
class TestWhatCannotBeRead:
    def test_something_unreadable_at_the_installed_name_is_its_own_answer(self) -> None:
        """A file that cannot be read is not a file that failed its digest.

        Nothing is known about it, replacing it is not the remedy, and what
        stops the read is usually gone a moment later. A directory at the
        installed name is the case every platform can produce.
        """
        pin = _pin()
        managed_monitor_path(pin.version, pin.target).mkdir(parents=True)

        with pytest.raises(MonitorError) as refused:
            resolve_pinned_monitor(pin)

        assert refused.value.error == MONITOR_BINARY_BUSY


@pytest.mark.usefixtures("managed")
class TestALaunchWithNothingToLaunch:
    def test_a_launch_refuses_rather_than_fetching_anything(
        self, tmp_path: Path
    ) -> None:
        """The launcher downloads nothing; provisioning runs before it.

        A launch asks the installation it runs in which digests admit a
        monitor, rather than being handed them, so it runs in an installation
        of its own: an installed release whose generated digests are those of
        the stand-in release, in an environment whose scripts directory is
        empty, beside a managed directory that holds nothing. This checkout's
        own monitor is installed in the suite's scripts directory, which is
        not that environment's, so "this release's monitor is installed
        nowhere" is a state the installation can really be in.

        Mutation: returned the unresolved answer instead of raising. Observed
        this test fail on the error code it compares, with none raised.
        Restored; passes.
        """
        installed = build_installation(
            tmp_path / "installation",
            version=_VERSION,
            direct_url=INSTALLED_FROM_A_WHEEL,
            pins=_released_as(_pin()),
            own_environment=True,
        )

        refused = installed.run(_LAUNCH_THE_MONITOR)

        assert refused["error"] == MONITOR_NOT_INSTALLED
        assert "next start" in str(refused["message"])


@pytest.mark.usefixtures("managed")
class TestVerificationBeforeRunning:
    def test_a_monitor_that_changed_after_resolution_is_not_run(self) -> None:
        """Resolution judged the file then; a launch meets whatever is there now.

        Mutation: dropped the digest comparison from the hold. Observed this
        test fail on the ``MonitorError`` it expects, with the replaced file
        accepted. Restored; passes.
        """
        pin = _pin()
        installed = _install(managed_monitor_path(pin.version, pin.target), _MONITOR)
        resolved = resolve_pinned_monitor(pin)
        assert resolved is not None
        _install(installed, _OTHER)

        with pytest.raises(MonitorError) as refused:
            verify_monitor(resolved)

        assert refused.value.error == MONITOR_BINARY_UNVERIFIED
        assert "next start" in str(refused.value)

    def test_an_empty_digest_is_a_mismatch_like_any_other(self) -> None:
        """There is no branch on which a monitor runs unhashed.

        Mutation: skipped the comparison when the expected digest was empty.
        Observed this test fail on the ``MonitorError`` it expects.
        Restored; passes.
        """
        pin = _pin()
        installed = _install(managed_monitor_path(pin.version, pin.target), _MONITOR)
        resolved = resolve_pinned_monitor(pin)
        assert resolved is not None

        with pytest.raises(MonitorError) as refused:
            verify_monitor(replace(resolved, sha256=""))

        assert refused.value.error == MONITOR_BINARY_UNVERIFIED
        assert installed.read_bytes() == _MONITOR


def test_the_managed_monitor_lives_beside_the_managed_qdrant_binary(
    managed: Path,
) -> None:
    """One isolation knob carries every provisioned artifact's state."""
    from ..qdrant_runtime._resolve import qdrant_bin_dir

    pin = _pin()
    monitor = managed_monitor_path(pin.version, pin.target)

    assert monitor.is_relative_to(managed)
    # {status}/bin/monitor/{version}/{target}/ beside {status}/bin/qdrant/{version}/
    assert os.path.normcase(
        str(monitor.parent.parent.parent.parent)
    ) == os.path.normcase(str(qdrant_bin_dir().parent.parent))
