"""Which monitor an installation runs, and what it is held to before it runs.

The monitor is a native executable started on every service start, so what
decides which file that is has to be the file's own content and never its
name or its place on a search path. These tests drive the real resolver over
real files: an executable whose bytes are the pinned ones, one whose bytes
are not, one planted in the working directory, and one named by the operator
settings.

Nothing here reads the digests generated into the package. The pin is the
resolver's argument, so a stand-in release is a value a test passes rather
than a trust constant it writes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

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
    expected_monitor_sha256,
    managed_monitor_path,
    monitor_for_launch,
    resolve_monitor,
    resolve_pinned_monitor,
)
from ..native_binary._install import file_sha256
from ..native_binary._targets import host_target
from ._planted_programs import stock_search_state
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_VERSION = "9.9.9"
#: The bytes a stand-in monitor is made of. Its digest is the pin.
_MONITOR = b"#!stand-in monitor\x00" * 64
_OTHER = b"#!a monitor of some other build\x00" * 64


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
def sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory standing in for the one this installation's programs are in.

    The running program is stood in for, so nothing is planted beside the
    real interpreter.
    """
    beside = tmp_path / "beside"
    beside.mkdir()
    monkeypatch.setattr(sys, "executable", str(beside / "vaultspec-rag"))
    return beside


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
        """A bundle install runs the monitor it shipped with.

        Mutation: yielded the managed install before the sibling. Observed
        this test fail on the path assertion, with the managed install
        chosen. Restored; passes.
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
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The launcher downloads nothing; provisioning runs before it."""
        monkeypatch.setattr(
            "vaultspec_rag.monitor_runtime._resolve.monitor_pin", lambda _target: _pin()
        )

        with pytest.raises(MonitorError) as refused:
            monitor_for_launch()

        assert refused.value.error == MONITOR_NOT_INSTALLED
        assert "next start" in str(refused.value)


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


@pytest.mark.usefixtures("managed")
class TestTheDigestACallerCanAskFor:
    def test_the_operator_s_declaration_is_what_a_monitor_is_held_to(
        self, tmp_path: Path
    ) -> None:
        theirs = _install(tmp_path / "theirs" / "monitor", _OTHER)

        with managed_env(
            **{
                EnvVar.MONITOR_BINARY.value: str(theirs),
                EnvVar.MONITOR_BINARY_SHA256.value: file_sha256(theirs),
            }
        ):
            assert expected_monitor_sha256() == file_sha256(theirs)

    def test_an_installation_with_nothing_to_admit_a_monitor_says_so(self) -> None:
        """``None`` rather than a raise: a caller asking is always answered."""
        if "vaultspec_rag.monitor_runtime._generated_pins" in sys.modules:
            pytest.skip("this checkout has generated monitor digests of its own")

        assert expected_monitor_sha256() is None

    def test_a_half_set_operator_pair_is_answered_too(self, tmp_path: Path) -> None:
        """A caller asking what the digest would be never meets an exception."""
        theirs = _install(tmp_path / "theirs" / "monitor", _OTHER)

        with managed_env(
            **{
                EnvVar.MONITOR_BINARY.value: str(theirs),
                EnvVar.MONITOR_BINARY_SHA256.value: None,
            }
        ):
            assert expected_monitor_sha256() is None


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
