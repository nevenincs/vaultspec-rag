"""What a provisioning run makes of a managed directory it did not leave tidy.

A run can be killed at any instruction, a file can be held or unreadable, and
something that is not a file can sit where the executable belongs. These tests
put the managed directory into each such state for real and drive whole
provisioning calls over it.

A whole call judges what is installed against the committed pins, and no
stand-in hashes to a committed digest. So every call here runs with a
stand-in release pinned through the one declared seam: the public call, the
same checks, held to the digests of a stand-in that a real loopback source
serves. That is what lets a healthy install be staged at all.

The two kills are real ones. The run happens in a child process, which stops
where the test asks by waiting in its own progress sink, and the parent ends
it with the operating system's kill. No ``finally`` runs in the child, which
is the point: what is on disk afterwards is what a killed run leaves.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .._anchor_claim import (
    AnchorOutcome,
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)
from .._python_child import module_command
from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import (
    MANIFEST_FILENAME,
    MANIFEST_SOURCE_UNRECORDED,
    QDRANT_SERVER_VERSION,
)
from ..qdrant_runtime._managed_install import InstallState, classify_managed_binary
from ..qdrant_runtime._provision import (
    _LOCK_FILENAME,
    provision,
    provisioned_versions,
)
from ..qdrant_runtime._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
    read_manifest,
)
from ._fake_qdrant_binary import unreadable
from ._loopback_tls import (
    LoopbackSources,
    send_bytes,
    trusted_loopback_sources,
)
from ._provisioning_child import REACHED
from ._stand_in_release import (
    NEW_EXECUTABLE,
    ServedRelease,
    abandon_a_working_file,
    place_stand_in,
    served_stand_in,
    sha256_hex,
    working_files,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..qdrant_runtime._constants import ProvisionReport

pytestmark = [pytest.mark.unit]

_OTHER_EXECUTABLE = b"bytes that are no release executable, pinned or stand-in"
_UPGRADE_COMMAND = "`vaultspec-rag server qdrant install --upgrade`"


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def version_dir(isolated_singleton_dirs: Path) -> Path:
    """The managed version dir, relocated under the test's temp dir."""
    del isolated_singleton_dirs
    return qdrant_bin_dir()


@pytest.fixture
def release(sources: LoopbackSources, version_dir: Path) -> Generator[ServedRelease]:
    """A stand-in release, pinned and served as the configured release source."""
    del version_dir
    with served_stand_in(sources) as served:
        yield served


def _run(
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    lines: list[str] | None = None,
) -> ProvisionReport:
    """One whole provisioning call, through the public function."""
    seen: list[str] = [] if lines is None else lines
    return provision(upgrade=upgrade, dry_run=dry_run, on_progress=seen.append)


def _manifest(version_dir: Path) -> dict[str, object]:
    recorded = read_manifest(version_dir)
    assert recorded is not None, "the manifest is missing or does not parse"
    return recorded


def _assert_describes_the_release(
    version_dir: Path, release: ServedRelease, source: str
) -> None:
    """The manifest records the pinned release, arrived by *source*."""
    asset = asset_for_platform()
    manifest = _manifest(version_dir)
    assert manifest["version"] == QDRANT_SERVER_VERSION
    assert manifest["asset"] == asset
    assert manifest["asset_sha256"] == sha256_hex(release.archive)
    assert manifest["binary_sha256"] == sha256_hex(NEW_EXECUTABLE)
    assert manifest["source"] == source


class TestAHealthyInstall:
    """The pinned executable is healthy whatever sits beside it."""

    def test_a_second_run_downloads_nothing(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        """An install that is already the pinned release costs no request.

        Mutation: made ``_judge_content`` match no committed digest. Observed
        the second action assertion fail (``failed`` where ``unchanged`` was
        required): the install this very code had just made was refused.
        Restored; passes.
        """
        first = _run()
        recorded = (version_dir / MANIFEST_FILENAME).read_bytes()

        second = _run()

        assert first.action == ProvisionAction.CREATED, first.message
        assert second.action == ProvisionAction.UNCHANGED, second.message
        assert len(release.source.requests) == 1
        assert (version_dir / MANIFEST_FILENAME).read_bytes() == recorded
        _assert_describes_the_release(version_dir, release, "download")

    @pytest.mark.parametrize(
        "manifest",
        [
            pytest.param(None, id="no manifest"),
            pytest.param("{ not json", id="a manifest that does not parse"),
            pytest.param({"version": QDRANT_SERVER_VERSION}, id="only a version"),
            pytest.param(
                {"version": QDRANT_SERVER_VERSION, "source": "operator"},
                id="claiming an operator binary",
            ),
            pytest.param(
                {"version": "0.0.1", "source": "download"}, id="another version"
            ),
        ],
    )
    def test_the_manifest_never_decides_and_a_wrong_one_is_written_again(
        self,
        release: ServedRelease,
        version_dir: Path,
        manifest: dict[str, str] | str | None,
    ) -> None:
        """The executable is the pinned one, so the install is healthy.

        Each manifest here once made this install unusable: missing, it was
        an install with nothing to vouch for it; claiming an operator, it was
        refused outright. None of them says anything about the bytes.

        Mutation: made ``_recorded_source`` accept any manifest, and no
        manifest, as describing the install. Observed the action assertion
        fail (``unchanged`` where ``updated`` was required) in every case: the
        wrong manifest was left as it was. Restored; passes.
        """
        binary = place_stand_in()
        if manifest is not None:
            text = manifest if isinstance(manifest, str) else json.dumps(manifest)
            (version_dir / MANIFEST_FILENAME).write_text(text, encoding="utf-8")

        report = _run()

        assert report.action == ProvisionAction.UPDATED, report.message
        assert "nothing was downloaded" in report.message
        assert report.binary == binary
        assert release.source.requests == []
        assert binary.read_bytes() == NEW_EXECUTABLE
        # How it arrived is recorded as what it is: not known.
        _assert_describes_the_release(version_dir, release, MANIFEST_SOURCE_UNRECORDED)
        again = _run()
        assert again.action == ProvisionAction.UNCHANGED, again.message

    def test_a_dry_run_over_a_missing_manifest_writes_nothing(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        place_stand_in()

        report = _run(dry_run=True)

        assert report.action == ProvisionAction.UNCHANGED
        assert "would write it again" in report.message
        assert release.source.requests == []
        assert sorted(path.name for path in version_dir.iterdir()) == [
            binary_filename()
        ]
        assert not (version_dir.parent / _LOCK_FILENAME).exists()

    def test_other_bytes_are_refused_with_both_ways_out_and_never_overwritten(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        """What is not the pinned release is not run and not replaced unasked.

        The manifest beside it is the one a real install writes, naming the
        pinned asset and both digests, so nothing in the directory disagrees
        with anything else in it. Only the bytes do.

        Mutation: made ``_plan`` treat a refused install as one to replace
        without being asked. Observed the action assertion fail (``updated``
        where ``failed`` was required), the executable overwritten. Restored;
        passes.
        """
        _run()
        binary = version_dir / binary_filename()
        binary.write_bytes(_OTHER_EXECUTABLE)
        asked = len(release.source.requests)

        report = _run()

        assert report.action == ProvisionAction.FAILED
        assert sha256_hex(_OTHER_EXECUTABLE) in report.message
        # Both routes, each as something that can be done as written.
        assert _UPGRADE_COMMAND in report.message
        assert "install --upgrade --archive <file>`" in report.message
        assert EnvVar.QDRANT_BINARY.value in report.message
        assert EnvVar.QDRANT_BINARY_SHA256.value in report.message
        assert len(release.source.requests) == asked
        assert binary.read_bytes() == _OTHER_EXECUTABLE

        upgraded = _run(upgrade=True)

        assert upgraded.action == ProvisionAction.UPDATED, upgraded.message
        assert binary.read_bytes() == NEW_EXECUTABLE
        assert len(release.source.requests) == asked + 1


@dataclass(frozen=True)
class _StoppedRun:
    """A provisioning run in a child process, waiting at the stage asked for.

    Attributes:
        started: The process this test started.
        pid: The interpreter running the provisioning call. It is the
            process started, except where the interpreter is reached
            through a launcher; then it is that launcher's child.
    """

    started: subprocess.Popen[str]
    pid: int


def _stopped_at(stage: str, scratch: Path) -> _StoppedRun:
    """Start a provisioning run in a child and return it stopped at *stage*.

    The child is alive when this returns, waiting in its progress sink at the
    stage named. The caller ends it.
    """
    assert __package__ is not None
    with (scratch / "child-stderr.txt").open("w", encoding="utf-8") as errors:
        child = subprocess.Popen(
            module_command(
                sys.executable,
                f"{__package__}._provisioning_child",
                stage,
            ),
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            cwd=scratch,
        )
    assert child.stdout is not None
    # A child that never reaches the stage must not hang the suite: ending it
    # ends the read below, which then fails on what it read.
    backstop = threading.Timer(120.0, child.kill)
    backstop.start()
    try:
        said = child.stdout.readline().strip()
    finally:
        backstop.cancel()
    reached, _, pid = said.rpartition(" ")
    if reached != REACHED or not pid.isdecimal():
        child.kill()
        child.wait(timeout=30)
        errors_text = (scratch / "child-stderr.txt").read_text(encoding="utf-8")
        pytest.fail(f"the child said {said!r} instead of stopping: {errors_text}")
    return _StoppedRun(child, int(pid))


def _kill_hard(run: _StoppedRun) -> None:
    """End the run as the operating system ends a process: at once, unasked.

    The interpreter itself is what is killed. The process this test started
    is then waited for, which is the interpreter or a launcher that ends
    with it, so the run is gone by the time this returns.
    """
    # Windows has one way to end a process from outside and this is it;
    # elsewhere the signal that cannot be caught is the equivalent.
    os.kill(run.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    run.started.wait(timeout=30)
    if run.started.stdout is not None:
        run.started.stdout.close()


class TestAKilledRun:
    """Whatever instruction a run dies at, the next run needs no help."""

    def test_a_run_killed_between_the_replace_and_the_manifest_is_finished_by_the_next(
        self, release: ServedRelease, version_dir: Path, tmp_path: Path
    ) -> None:
        """The pinned executable with no manifest is healthy, and is completed.

        The child is killed after it moved the verified executable into place
        and before it wrote the manifest. That leaves the pinned executable,
        no manifest, and the downloaded archive still in its working file. A
        plain next run, with no upgrade asked for, must accept the
        executable, ask the source for nothing, write the manifest and remove
        the working file.

        Mutation: made ``_plan`` fail an install whose manifest does not
        describe it, which is what a missing manifest used to mean. Observed
        the action assertion fail (``failed`` where ``updated`` was
        required). Then, with that restored, removed the sweep the locked
        step makes. Observed the working-file assertion fail, listing the
        archive the killed run had left. Restored after each; passes.
        """
        binary = version_dir / binary_filename()

        _kill_hard(_stopped_at("Recording the installed Qdrant server", tmp_path))

        # What the kill left: the executable in place, nothing recording it,
        # and the archive nobody came back for.
        assert binary.read_bytes() == NEW_EXECUTABLE
        assert not (version_dir / MANIFEST_FILENAME).exists()
        assert working_files(version_dir) != []
        assert len(release.source.requests) == 1
        # What a start is told about it, before any run has repaired anything.
        judged = classify_managed_binary(binary)
        assert judged.state is InstallState.HEALTHY

        report = _run()

        assert report.action == ProvisionAction.UPDATED, report.message
        assert len(release.source.requests) == 1
        assert binary.read_bytes() == NEW_EXECUTABLE
        _assert_describes_the_release(version_dir, release, MANIFEST_SOURCE_UNRECORDED)
        assert working_files(version_dir) == []
        again = _run()
        assert again.action == ProvisionAction.UNCHANGED, again.message
        assert len(release.source.requests) == 1

    def test_a_run_killed_while_it_holds_the_lock_does_not_hold_up_the_next(
        self, release: ServedRelease, version_dir: Path, tmp_path: Path
    ) -> None:
        """The lock dies with its holder; its record and its files do not bind.

        The child is stopped after it took the provisioning lock, recorded
        itself as the owner and created its working file. While it lives, a
        contender is refused and is told who holds the lock. Once it is
        killed the record still names it and the file is still there. The
        next run must take the lock at once, clear the file and install.

        Mutation: removed the sweep the locked step makes. Observed the
        working-file assertion fail, listing the file the dead holder had
        created. Restored; passes. That the lock is free the moment its
        holder dies is the operating system's doing: no line of the
        provisioner can be removed to make a dead process keep it, so that
        half has no mutation. Its premise is asserted instead: the same
        lock was refused, and its holder named, while the holder lived.
        """
        lock = version_dir.parent / _LOCK_FILENAME

        holder = _stopped_at("Downloading the Qdrant server (", tmp_path)
        try:
            contended = claim_anchor(lock, pid_record=True)
            held_by = contended.holder_pid
            if contended.descriptor is not None:
                release_anchor_claim(contended.descriptor, pid_record=True)
        finally:
            _kill_hard(holder)
        assert contended.outcome is AnchorOutcome.CONTENDED
        assert held_by == holder.pid
        assert working_files(version_dir) != []
        assert release.source.requests == []

        lines: list[str] = []
        report = _run(lines=lines)

        assert report.action == ProvisionAction.CREATED, report.message
        assert not any(line.startswith("Waiting for") for line in lines)
        assert working_files(version_dir) == []
        assert len(release.source.requests) == 1
        _assert_describes_the_release(version_dir, release, "download")


class TestAbandonedWorkingFiles:
    """A run with nothing to install still clears what a dead run left."""

    def test_a_run_that_finds_a_healthy_install_removes_them(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        """An install may never come, so the cleanup cannot wait for one.

        Mutation: removed the sweep ``provision`` makes for a plan that
        installs nothing. Observed the working-file assertion fail, here and
        in the refused case below. Restored; passes.
        """
        _run()
        abandon_a_working_file(version_dir)

        report = _run()

        assert report.action == ProvisionAction.UNCHANGED, report.message
        assert working_files(version_dir) == []
        assert len(release.source.requests) == 1

    def test_a_run_that_refuses_what_is_installed_removes_them(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        binary = place_stand_in(_OTHER_EXECUTABLE)
        abandon_a_working_file(version_dir)

        report = _run()

        assert report.action == ProvisionAction.FAILED
        assert working_files(version_dir) == []
        assert binary.read_bytes() == _OTHER_EXECUTABLE
        assert release.source.requests == []

    @pytest.mark.usefixtures("release")
    def test_a_working_file_is_left_alone_while_a_run_holds_the_lock(
        self, version_dir: Path
    ) -> None:
        """A file is abandoned only when no run can still be using it.

        The lock is held through a second descriptor, which the claim refuses
        exactly as it refuses another process. The file could be that
        holder's download in progress.

        Mutation: made ``_sweep_if_unclaimed`` remove the files without
        taking the lock. Observed the existence assertion fail: a file a live
        run could have been writing was deleted under it. Restored; passes.
        """
        _run()
        in_use = abandon_a_working_file(version_dir)
        claim = claim_anchor(version_dir.parent / _LOCK_FILENAME, pid_record=True)
        assert claim.descriptor is not None, claim
        record_claim_owner(claim.descriptor)
        lines: list[str] = []
        try:
            report = _run(lines=lines)
        finally:
            release_anchor_claim(claim.descriptor, pid_record=True)

        assert report.action == ProvisionAction.UNCHANGED, report.message
        assert in_use.is_file()
        # Nothing to install, so nothing to wait for.
        assert lines == []


class TestAnExecutableThatCannotBeRead:
    """Not being able to read a file says nothing about what is in it."""

    def test_a_plain_run_reports_it_unreadable_and_proposes_no_replacement(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        """One failed outcome, with the remedy for a file that is held.

        The executable is the pinned one. Telling the operator to replace it
        would be wrong, and following that advice used to end in a traceback.

        Mutation: made ``_judge_content`` let the failed read escape instead
        of reporting it. Observed the call raise ``PermissionError`` here, in
        the listing below, and in the upgrade. Restored; passes.
        """
        _run()
        binary = version_dir / binary_filename()
        asked = len(release.source.requests)

        with unreadable(binary):
            report = _run()

        assert report.action == ProvisionAction.FAILED
        assert "cannot be read" in report.message
        assert "Close whatever holds it" in report.message
        assert "permissions" in report.message
        assert "--upgrade" not in report.message
        assert len(release.source.requests) == asked
        assert binary.read_bytes() == NEW_EXECUTABLE

    @pytest.mark.usefixtures("version_dir")
    def test_a_listing_reports_it_and_does_not_raise(self) -> None:
        binary = place_stand_in()

        with unreadable(binary):
            entries = provisioned_versions()

        assert len(entries) == 1
        assert entries[0]["verified"] is False
        assert entries[0]["source"] == "unverified"
        assert "cannot be read" in str(entries[0]["problem"])
        assert "--upgrade" not in str(entries[0]["problem"])

    @pytest.mark.usefixtures("release")
    def test_the_upgrade_form_ends_in_one_outcome_too(self, version_dir: Path) -> None:
        """Asked to replace it, the run tries, and reports how that went.

        On Windows the handle that stops the read also stops the replace, so
        the outcome is the failure that says what holds the file. Elsewhere a
        file nobody may read can still be replaced, and is.
        """
        _run()
        binary = version_dir / binary_filename()

        with unreadable(binary):
            report = _run(upgrade=True)

        if sys.platform == "win32":
            assert report.action == ProvisionAction.FAILED
            assert "held open by another process" in report.message
            assert "`vaultspec-rag server stop`" in report.message
            assert f"Then run {_UPGRADE_COMMAND}" in report.message
        else:
            assert report.action == ProvisionAction.UPDATED, report.message
        assert binary.read_bytes() == NEW_EXECUTABLE
        assert working_files(version_dir) == []


class TestSomethingElseAtTheInstalledName:
    @pytest.mark.parametrize("upgrade", [False, True], ids=["plain", "upgrade"])
    def test_a_directory_there_is_reported_before_anything_is_downloaded(
        self, release: ServedRelease, version_dir: Path, upgrade: bool
    ) -> None:
        """No install can be written over a directory, so none is attempted.

        Mutation: made ``classify_managed_binary`` report anything that is
        not a regular file as absent. Observed the request-log assertion
        fail: the archive was downloaded, and only the final move discovered
        the directory. Restored; passes.
        """
        blocking = version_dir / binary_filename()
        blocking.mkdir(parents=True)

        report = _run(upgrade=upgrade)

        assert release.source.requests == []
        assert report.action == ProvisionAction.FAILED
        assert str(blocking) in report.message
        assert "Remove it" in report.message
        assert "`vaultspec-rag server qdrant install`" in report.message
        assert "server stop" not in report.message
        assert blocking.is_dir()


def _a_file_where_bin_belongs(status_dir: Path) -> None:
    (status_dir / "bin").write_text("not a directory", encoding="utf-8")


def _a_file_where_the_version_directory_belongs(status_dir: Path) -> None:
    versions = status_dir / "bin" / "qdrant"
    versions.mkdir(parents=True)
    (versions / QDRANT_SERVER_VERSION).write_text("not a directory", encoding="utf-8")


def _a_directory_where_the_lock_belongs(status_dir: Path) -> None:
    (status_dir / "bin" / "qdrant" / _LOCK_FILENAME).mkdir(parents=True)


class TestAManagedDirectoryThatCannotBeWritten:
    @pytest.mark.parametrize(
        "obstruct",
        [
            _a_file_where_bin_belongs,
            _a_file_where_the_version_directory_belongs,
            _a_directory_where_the_lock_belongs,
        ],
    )
    def test_the_failure_names_the_directory_setting_and_not_the_service(
        self,
        sources: LoopbackSources,
        isolated_singleton_dirs: Path,
        obstruct: Callable[[Path], None],
    ) -> None:
        """A fault of the directory is told as one, with a way out of it.

        None of these has anything to do with a running server, and stopping
        the service would repair none of them. Each is reported before a
        request is made.

        Mutation: dropped the remedy from the lock fault in
        ``_run_exclusively``. Observed the setting assertion fail in the two
        cases where the lock cannot be taken. Then dropped it from the
        filesystem branch of ``_failure_message``. Observed it fail in the
        third. Restored after each; passes.
        """
        obstruct(isolated_singleton_dirs)
        mirror = sources.serve(lambda handler: send_bytes(handler, b"not the release"))

        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/mirror")}
        ):
            report = provision()

        assert report.action == ProvisionAction.FAILED
        assert EnvVar.STATUS_DIR.value in report.message
        assert "`vaultspec-rag server qdrant install`" in report.message
        assert "server stop" not in report.message
        assert mirror.requests == []


class TestTwoStartsAtOnce:
    def test_the_second_adopts_what_the_first_installed_and_downloads_nothing(
        self, release: ServedRelease, version_dir: Path
    ) -> None:
        """A run that waited for the lock looks again before it acts.

        The run finds nothing installed and waits for the lock, which another
        run holds. While it waits, the pinned executable appears at the
        installed name, as it does when the holder's own install lands. The
        waiting run planned a download; holding the lock at last, it must
        find the executable healthy and ask the source for nothing.

        Mutation: made the locked step of ``provision`` act on the plan made
        before the wait. Observed the request-log assertion fail: the archive
        was downloaded and installed over the executable already there.
        Restored; passes.
        """
        claim = claim_anchor(
            version_dir.parent / _LOCK_FILENAME, pid_record=True, create_parent=True
        )
        assert claim.descriptor is not None, claim
        record_claim_owner(claim.descriptor)
        waiting = threading.Event()
        reports: list[ProvisionReport] = []

        def note_waiting(line: str) -> None:
            if line.startswith("Waiting for"):
                waiting.set()

        def second_start() -> None:
            reports.append(provision(on_progress=note_waiting))

        thread = threading.Thread(target=second_start)
        thread.start()
        try:
            assert waiting.wait(timeout=30), "the run never reported waiting"
            place_stand_in()
        finally:
            release_anchor_claim(claim.descriptor, pid_record=True)
        thread.join(timeout=60)

        assert release.source.requests == []
        assert [report.action for report in reports] == [ProvisionAction.UPDATED]
        assert (version_dir / binary_filename()).read_bytes() == NEW_EXECUTABLE
        _assert_describes_the_release(version_dir, release, MANIFEST_SOURCE_UNRECORDED)
