"""Obtaining the monitor, over a real transport, with nothing asked of anyone.

Every case here runs the shipped provisioner against a stand-in release
served over HTTPS from the loopback address, with a certificate the client
verifies the way it verifies any other. The archive is a real archive of this
platform's format, the digests are real digests of its bytes, and the install
lands in a managed directory of the test's own.

What the pins say is the provisioner's argument rather than something written
into the package, so no test substitutes a trust constant: a stand-in release
is a value, and the checks that admit it are the shipped ones.

The other thing held here is what an operator is told. Getting the monitor is
automatic from end to end, so no outcome may tell anyone to install it,
download it, configure it or point at it. Each failure says what happened and
that the next start tries again.
"""

from __future__ import annotations

import inspect
import os
import re
import time
from dataclasses import replace
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..monitor_runtime import _provision as monitor_provision
from ..monitor_runtime._assets import monitor_archive_name, monitor_executable_name
from ..monitor_runtime._pins import MonitorPin, PinProvenance
from ..monitor_runtime._provision import (
    provision_monitor,
    provision_pinned_monitor,
    retire_superseded,
)
from ..monitor_runtime._resolve import managed_monitor_path, managed_monitor_root
from ..native_binary._download import DownloadLimits
from ..native_binary._install import STAGING_SUFFIX
from ..native_binary._targets import host_target
from ._loopback_tls import (
    LOOPBACK_HOST,
    LoopbackSources,
    send_bytes,
    trusted_loopback_sources,
)
from ._stand_in_release import build_archive, sha256_hex
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..native_binary._report import ProvisionReport
    from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

_VERSION = "9.9.9"
_TAG = f"vaultspec-rag-v{_VERSION}"
#: The bytes a stand-in monitor is made of.
_MONITOR = b"#!stand-in monitor\x00" * 512
#: What a source that is serving something else sends.
_WRONG = b"not this release's monitor at all"
#: A process id no process has. Nothing is signalled with it; it only has to
#: read as gone.
_DEAD_PID = 2_000_000_000

#: Anything that reads as an instruction to go and get the monitor. None of
#: these may appear in any outcome: the only hands this passes through are
#: the ones already running.
_INSTRUCTIONS = re.compile(
    r"\b(install the|download the|run:|run `|set VAULTSPEC_RAG_MONITOR|"
    r"add .* to PATH|build the monitor)\b",
    re.IGNORECASE,
)


def _archive(executable: bytes = _MONITOR) -> bytes:
    """A monitor-only archive of this platform's format, laid out as released."""
    target = host_target()
    return build_archive(
        monitor_archive_name(_VERSION, target),
        {f"monitor/{monitor_executable_name(target)}": executable},
    )


def _pin(archive: bytes, executable: bytes = _MONITOR) -> MonitorPin:
    """The pin a release of *archive* and *executable* would carry here."""
    target = host_target()
    return MonitorPin(
        provenance=PinProvenance.RELEASE,
        version=_VERSION,
        tag=_TAG,
        target=target,
        archive_name=monitor_archive_name(_VERSION, target),
        archive_sha256=sha256_hex(archive),
        executable_name=monitor_executable_name(target),
        executable_sha256=sha256_hex(executable),
    )


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def managed(tmp_path: Path) -> Generator[Path]:
    """A managed service directory of this test's own, with no monitor in it."""
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


def _responder(body: bytes) -> Callable[[QuietHandler], None]:
    """Answer every request with *body*."""

    def respond(handler: QuietHandler) -> None:
        send_bytes(handler, body)

    return respond


def _install_from(
    sources: LoopbackSources,
    served: bytes,
    pin: MonitorPin,
    *,
    lines: list[str] | None = None,
) -> tuple[ProvisionReport, list[str]]:
    """Provision *pin* from a loopback source serving *served*.

    Args:
        lines: Collects the stages the run reports, for a test about the
            order they happen in.

    Returns:
        The report, and the paths the source was asked for.
    """
    source = sources.serve(_responder(served))
    said = lines if lines is not None else []
    with managed_env(
        **{
            EnvVar.MONITOR_RELEASE_BASE_URL.value: source.url(),
            EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
        }
    ):
        report = provision_pinned_monitor(pin, on_progress=said.append)
    return report, source.requests


def _no_instruction(report: ProvisionReport) -> None:
    """Hold an outcome to saying nothing anyone is meant to act on."""
    assert not _INSTRUCTIONS.search(report.message), report.message
    assert EnvVar.MONITOR_BINARY.value not in report.message


@pytest.mark.usefixtures("managed")
class TestAFirstInstall:
    def test_the_archive_is_fetched_verified_and_the_member_installed(
        self, sources: LoopbackSources
    ) -> None:
        archive = _archive()
        pin = _pin(archive)
        lines: list[str] = []

        report, requests = _install_from(sources, archive, pin, lines=lines)

        # The reported sequence follows the enforced one.
        assert lines.index("Verifying the monitor download checksum...") < lines.index(
            "Extracting the monitor..."
        )

        assert report.action is ProvisionAction.CREATED, report.message
        assert requests == [f"/{_TAG}/{pin.archive_name}"]
        installed = managed_monitor_path(pin.version, pin.target)
        assert report.binary == installed
        assert installed.read_bytes() == _MONITOR
        # The archive is a working file of the run, not something kept.
        assert list(installed.parent.glob(f".*{STAGING_SUFFIX}")) == []

    def test_a_second_run_fetches_nothing(self, sources: LoopbackSources) -> None:
        """Offline after the first install, which is every start but one.

        Mutation: reported nothing as installed, whatever is at the
        installed name. Observed this test fail on the action assertion,
        with the archive fetched and installed a second time. Restored;
        passes.
        """
        archive = _archive()
        pin = _pin(archive)
        _install_from(sources, archive, pin)

        report, requests = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.UNCHANGED, report.message
        assert requests == []

    def test_a_preview_touches_neither_the_network_nor_the_disk(
        self, sources: LoopbackSources
    ) -> None:
        archive = _archive()
        pin = _pin(archive)
        source = sources.serve(_responder(archive))

        with managed_env(
            **{
                EnvVar.MONITOR_RELEASE_BASE_URL.value: source.url(),
                EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
            }
        ):
            report = provision_pinned_monitor(pin, dry_run=True)

        assert report.action is ProvisionAction.DRY_RUN
        assert source.requests == []
        assert not managed_monitor_path(pin.version, pin.target).exists()


@pytest.mark.usefixtures("managed")
class TestWhatIsRefused:
    def test_a_source_serving_other_bytes_installs_nothing(
        self, sources: LoopbackSources
    ) -> None:
        """The digest is checked before anything is extracted.

        Order is the security property, and what shows it is the sequence
        the run reports: a rejected archive is never described as extracted,
        because nothing reads a member out of it.

        Mutation: moved the archive digest comparison after the extraction.
        Observed this test fail on the extraction assertion: the archive was
        unpacked and only then refused. Restored; passes.
        """
        pin = _pin(_archive())
        lines: list[str] = []

        report, _ = _install_from(sources, _archive(_WRONG), pin, lines=lines)

        assert report.action is ProvisionAction.FAILED
        assert not managed_monitor_path(pin.version, pin.target).exists()
        assert "not what this release published" in report.message
        assert "Verifying the monitor download checksum..." in lines
        assert "Extracting the monitor..." not in lines, lines
        _no_instruction(report)

    def test_a_refusal_leaves_no_empty_directory_chain_behind(
        self, sources: LoopbackSources
    ) -> None:
        """An install that kept nothing leaves no directories either.

        The run has to create the version and target directories before it
        can stage anything, and a refused archive leaves them empty under
        the managed directory, where nothing looks again.

        Mutation: dropped the empty-directory removal from the failure path.
        Observed this test fail on the version-directory assertion, with
        both directories left behind. Restored; passes.
        """
        pin = _pin(_archive())

        report, _ = _install_from(sources, _archive(_WRONG), pin)

        assert report.action is ProvisionAction.FAILED
        version_dir = managed_monitor_root() / pin.version
        assert not version_dir.exists(), sorted(version_dir.rglob("*"))
        # The managed directory itself is nobody's to remove: it holds every
        # other version's install.
        assert managed_monitor_root().is_dir()

    def test_an_archive_holding_another_executable_installs_nothing(
        self, sources: LoopbackSources
    ) -> None:
        """Both digests are checked, so matching one is not enough.

        The archive served is the pinned archive; the member inside it is
        not the pinned executable, which is what a tampered build would be.

        Mutation: dropped the executable digest comparison. Observed this
        test fail on the "nothing installed" assertion. Restored; passes.
        """
        archive = _archive(_WRONG)
        # The archive served is the pinned archive; the member inside it is
        # not the pinned executable.
        pin = replace(_pin(archive), executable_sha256=sha256_hex(_MONITOR))

        report, _ = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.FAILED
        assert not managed_monitor_path(pin.version, pin.target).exists()
        _no_instruction(report)

    def test_a_source_that_cannot_be_reached_says_the_next_start_retries(
        self, sources: LoopbackSources
    ) -> None:
        """No network on the first start of a release is not a setup failure."""
        pin = _pin(_archive())

        with managed_env(
            **{
                EnvVar.MONITOR_RELEASE_BASE_URL.value: sources.refused_url(),
                EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
            }
        ):
            report = provision_pinned_monitor(pin)

        assert report.action is ProvisionAction.FAILED
        assert "could not reach the source" in report.message
        assert "The next start tries again." in report.message
        _no_instruction(report)

    def test_a_source_that_has_no_such_file_installs_nothing(
        self, sources: LoopbackSources
    ) -> None:
        pin = _pin(_archive())

        def missing(handler: QuietHandler) -> None:
            send_bytes(handler, b"no such release", status=HTTPStatus.NOT_FOUND)

        source = sources.serve(missing)
        with managed_env(
            **{
                EnvVar.MONITOR_RELEASE_BASE_URL.value: source.url(),
                EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
            }
        ):
            report = provision_pinned_monitor(pin)

        assert report.action is ProvisionAction.FAILED
        assert "published no such file" in report.message
        _no_instruction(report)

    def test_a_build_published_nowhere_fetches_nothing(
        self, sources: LoopbackSources
    ) -> None:
        """A development build's monitor is not on any release source.

        Its digests describe a monitor compiled on this machine, which no
        tag published, so there is nothing to request. The repository's own
        setup installs that one.
        """
        archive = _archive()
        local = replace(_pin(archive), provenance=PinProvenance.DEVELOPMENT, tag="")
        source = sources.serve(_responder(archive))

        with managed_env(
            **{
                EnvVar.MONITOR_RELEASE_BASE_URL.value: source.url(),
                EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
            }
        ):
            report = provision_pinned_monitor(local)

        assert report.action is ProvisionAction.FAILED
        assert source.requests == []
        assert "published nowhere" in report.message
        _no_instruction(report)


@pytest.mark.usefixtures("managed")
class TestAnUpgrade:
    def test_the_new_release_is_installed_and_the_old_one_removed(
        self, sources: LoopbackSources
    ) -> None:
        """An upgrade leaves one install behind, not a directory per release.

        Mutation: retired every version including the new one. Observed this
        test fail on the installed-file assertion. Restored; passes.
        """
        archive = _archive()
        pin = _pin(archive)
        superseded = managed_monitor_root() / "0.0.1" / pin.target
        superseded.mkdir(parents=True)
        (superseded / pin.executable_name).write_bytes(b"an older monitor")

        report, _ = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.CREATED, report.message
        assert managed_monitor_path(pin.version, pin.target).exists()
        assert not superseded.parent.exists()
        assert "0.0.1" in report.message

    def test_retiring_keeps_the_release_in_use(self) -> None:
        root = managed_monitor_root()
        for version in ("0.0.1", _VERSION, "0.0.2"):
            (root / version).mkdir(parents=True)

        retired = retire_superseded(_VERSION)

        assert sorted(retired) == ["0.0.1", "0.0.2"]
        assert (root / _VERSION).is_dir()


#: The random part of a staging file's name, in both shapes it comes in. An
#: all-digit token is one name in about two hundred and seventy, and it is the
#: one that tells a name read by position from a name searched for something
#: pid-shaped: searched, the token answers and the recorded pid is never seen.
_TOKENS = ("0123456789ab", "012345678901")


@pytest.mark.usefixtures("managed")
@pytest.mark.parametrize("token", _TOKENS)
class TestWhatAKilledRunLeftBehind:
    """Nothing serialises these installs, so a sweep answers to two witnesses.

    A staging file's name carries the process that created it, and no
    transfer outlasts the deadline the run was given. A file whose creator
    is gone, or that is older than that deadline, is one no run can still be
    writing. A pid is recycled, which is why age is asked as well.
    """

    def _abandon(self, pin: MonitorPin, pid: int, token: str) -> Path:
        """Leave a file exactly as a run killed mid-download leaves one."""
        version_dir = managed_monitor_path(pin.version, pin.target).parent
        version_dir.mkdir(parents=True, exist_ok=True)
        left = version_dir / f".{pin.archive_name}.{pid}.{token}{STAGING_SUFFIX}"
        left.write_bytes(b"half a download from a run that was killed")
        return left

    def test_a_file_whose_run_is_gone_is_swept_on_the_next_install(
        self, sources: LoopbackSources, token: str
    ) -> None:
        """Mutation: dropped the sweep from the install. Observed this test
        fail on the removal assertion, the abandoned file still there after
        a successful install. Restored; passes."""
        archive = _archive()
        pin = _pin(archive)
        left = self._abandon(pin, _DEAD_PID, token)

        report, _ = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.CREATED, report.message
        assert not left.exists()

    def test_a_file_a_live_run_may_still_be_writing_is_left_alone(
        self, sources: LoopbackSources, token: str
    ) -> None:
        """A second run installing right now is not something to clean up.

        Mutation: swept every staging file found, whatever its name said.
        Observed this test fail on the survival assertion, this process's
        own fresh file removed. Restored; passes.

        Mutation: read the pid as the last all-digit part of the name rather
        than the part it is written at. Observed this test fail on the
        survival assertion for the all-digit token alone, the token answering
        as a pid no process has and this process's fresh file swept.
        Restored; passes.
        """
        archive = _archive()
        pin = _pin(archive)
        live = self._abandon(pin, os.getpid(), token)

        report, _ = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.CREATED, report.message
        assert live.exists()

    def test_a_live_pid_s_file_older_than_the_deadline_is_swept(
        self, sources: LoopbackSources, token: str
    ) -> None:
        """A pid is not an identity, so age is the second witness.

        No transfer outlasts the deadline its run was given, so a file older
        than that belongs to a run that is gone whoever answers to its pid
        now.
        """
        archive = _archive()
        pin = _pin(archive)
        live = self._abandon(pin, os.getpid(), token)
        stale = time.time() - monitor_provision._DOWNLOAD_DEADLINE_SECONDS - 60
        os.utime(live, (stale, stale))

        report, _ = _install_from(sources, archive, pin)

        assert report.action is ProvisionAction.CREATED, report.message
        assert not live.exists()


def test_the_download_deadline_is_sized_for_the_monitor_s_own_bytes() -> None:
    """The archive is about three times the server binary's, with no resume.

    The shared default is sized for tens of megabytes, so taking it would
    ask three times the bandwidth of a first start that has to succeed on a
    slow link.

    Mutation: took the shared default. Observed this test fail on the
    deadline assertion. Restored; passes.
    """
    default = DownloadLimits()
    limits = monitor_provision._DOWNLOAD_LIMITS

    assert limits.deadline_seconds == pytest.approx(3 * default.deadline_seconds)
    # Only the deadline differs: nothing else about the transfer changes.
    assert limits.stall_seconds == default.stall_seconds
    assert limits.max_bytes == default.max_bytes
    assert limits.attempts == default.attempts


@pytest.mark.usefixtures("managed")
class TestTheEntryPointEveryCommandUses:
    @pytest.mark.usefixtures("unpinned_installation")
    def test_an_installation_with_no_digests_reports_and_fetches_nothing(
        self, sources: LoopbackSources
    ) -> None:
        """An installation with nothing to admit one provisions nothing.

        What this installation carries is a stated input: a checkout that
        compiled a monitor of its own carries digests for it, and this case
        is the one that carries none.
        """
        source = sources.serve(_responder(_archive()))

        with managed_env(
            **{
                EnvVar.MONITOR_RELEASE_BASE_URL.value: source.url(),
                EnvVar.MONITOR_DOWNLOAD_HOSTS.value: LOOPBACK_HOST,
            }
        ):
            report = provision_monitor()

        assert report.action is ProvisionAction.FAILED
        assert source.requests == []
        _no_instruction(report)


def test_nothing_in_the_provisioner_names_the_operator_settings() -> None:
    """The one place a monitor message may name a variable is not this one.

    The settings exist for an operator running their own build. Naming them
    where an automatic fetch failed would turn a failure into a setup
    instruction, which is the one thing no monitor message does.

    Mutation: added the path variable to a download remedy. Observed this
    test fail naming that line. Restored; passes.
    """
    source = inspect.getsource(monitor_provision)

    assert EnvVar.MONITOR_BINARY.value not in source
    assert EnvVar.MONITOR_BINARY_SHA256.value not in source
