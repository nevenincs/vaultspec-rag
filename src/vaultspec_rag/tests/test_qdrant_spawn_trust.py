"""Guard tests for checking the qdrant binary inside every spawn.

A check made once, when the service resolves its binary, says nothing about
the file a later spawn runs: the heartbeat restarts a dead child, and the
recovery loop re-spawns after moving a collection aside. So the check lives in
the supervisor's one spawn path, and these tests reach it by each of the three
ways a child comes to exist.

No mocks: every binary here is a real launcher on the real filesystem, the
supervisor spawns it as a real subprocess, and "it never ran" is proven by a
file the launcher would have written. A managed binary is stood in for by a
launcher held to its own digest, the way an operator-registered install is,
because no stand-in can hash to a release executable's committed digest.

Every test here is a guard and has been observed failing for its intended
reason; the mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from ..qdrant_runtime import _supervise
from ..qdrant_runtime._constants import BinarySource, ResolvedBinary
from ..qdrant_runtime._provision import file_sha256
from ..qdrant_runtime._resolve import QdrantBinaryError, verify_resolved_binary
from ..qdrant_runtime._supervise import QdrantSupervisor
from ._fake_qdrant_binary import FAKE_SERVER, fake_qdrant_binary, unpinned
from ._ports import free_loopback_port

pytestmark = [pytest.mark.unit]

_MANAGED_SOURCES = (BinarySource.MANAGED_DOWNLOAD, BinarySource.MANAGED_OPERATOR)

# Writes a file and exits. Whether that file exists afterwards is the whole
# observation: it is the only trace a refused binary could leave if it ran.
_RECORDS_THAT_IT_RAN = """
import pathlib

pathlib.Path({marker!r}).write_text("ran", encoding="utf-8")
"""

# Counts its own runs, changes the bytes of the launcher that started it, then
# dies naming a collection - the output that makes the recovery loop move that
# collection aside and spawn again. The second spawn therefore meets a binary
# that verified a moment ago and no longer does.
_REWRITES_ITS_LAUNCHER_THEN_DIES = """
import pathlib
import sys

with pathlib.Path({runs!r}).open("a") as stream:
    stream.write("run\\n")
with pathlib.Path({launcher!r}).open("ab") as stream:
    stream.write({appended!r})
print("panicked: cannot load collection r0000_vault_docs: corrupt segment", flush=True)
sys.exit(1)
"""

#: Bytes that change a launcher's digest and leave it a working launcher, so a
#: spawn that skipped the check would run it and not merely fail to start.
_HARMLESS_TAIL = (
    b"\r\nREM changed after it was verified\r\n"
    if sys.platform == "win32"
    else b"\n# changed after it was verified\n"
)


def _held_to_its_own_digest(
    launcher: Path, source: BinarySource = BinarySource.MANAGED_OPERATOR
) -> ResolvedBinary:
    """A managed binary whose expected digest is the launcher's digest now."""
    return ResolvedBinary(path=launcher, source=source, sha256=file_sha256(launcher))


def _supervisor(binary: ResolvedBinary | None, tmp_path: Path) -> QdrantSupervisor:
    return QdrantSupervisor(
        binary,
        http_port=free_loopback_port(),
        storage_dir=tmp_path / "qdrant" / "storage",
        log_path=tmp_path / "qdrant.log",
    )


def _marker_launcher(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "it-ran.txt"
    launcher = fake_qdrant_binary(
        tmp_path, _RECORDS_THAT_IT_RAN.format(marker=str(marker)), name="marker"
    )
    return launcher, marker


class TestAManagedBinaryIsHashedBeforeItRuns:
    """No managed binary runs on a digest that is wrong, empty, or absent."""

    @pytest.mark.parametrize("source", _MANAGED_SOURCES)
    def test_a_binary_that_does_not_match_its_digest_never_runs(
        self, source: BinarySource, tmp_path: Path
    ) -> None:
        """Mutation it catches: dropping the check from ``spawn()``.

        The launcher then runs, no exception is raised, and this fails on the
        missing ``QdrantBinaryError``.
        """
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(
            ResolvedBinary(path=launcher, source=source, sha256="0" * 64), tmp_path
        )
        try:
            with pytest.raises(QdrantBinaryError) as refused:
                supervisor.spawn()
        finally:
            assert supervisor.stop(timeout=10.0)

        assert refused.value.error == "qdrant_binary_unverified"
        assert "vaultspec-rag server qdrant install --upgrade" in str(refused.value)
        assert supervisor.pid is None
        assert not marker.exists(), "a binary that failed its digest was run"

    @pytest.mark.parametrize("source", _MANAGED_SOURCES)
    def test_a_binary_with_no_digest_never_runs(
        self, source: BinarySource, tmp_path: Path
    ) -> None:
        """An empty digest is a mismatch, not a reason to skip the check.

        Mutation it catches: returning early from the check when the expected
        digest is empty. That is the branch that let an install whose manifest
        recorded no digest run unverified; with it restored the launcher runs
        and this fails on the missing ``QdrantBinaryError``.
        """
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(ResolvedBinary(path=launcher, source=source), tmp_path)
        try:
            with pytest.raises(QdrantBinaryError) as refused:
                supervisor.spawn()
        finally:
            assert supervisor.stop(timeout=10.0)

        assert refused.value.error == "qdrant_binary_unverified"
        assert supervisor.pid is None
        assert not marker.exists(), "a binary with no digest was run"

    def test_a_binary_that_matches_its_digest_runs(self, tmp_path: Path) -> None:
        """The control: the refusals above are not a spawn that never works."""
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(_held_to_its_own_digest(launcher), tmp_path)
        try:
            supervisor.spawn()
            process = supervisor._proc
            assert process is not None
            assert process.wait(timeout=30.0) == 0
        finally:
            assert supervisor.stop(timeout=10.0)

        assert marker.read_text(encoding="utf-8") == "ran"


@pytest.mark.usefixtures("isolated_singleton_dirs")
class TestEveryLaterSpawnIsHashedAgain:
    """A binary that verified at the first start is checked at each later one."""

    def test_a_restart_refuses_a_binary_changed_since_the_first_start(
        self, tmp_path: Path
    ) -> None:
        """The heartbeat's restart must not be a way around the check.

        The changed launcher still works, so a restart that did not hash it
        would bring the server back and report success.

        Mutation it catches: checking only while ``restart_count`` is zero.
        The restart then returns ``True`` with a live child, and this fails on
        the ``restarted is False`` assertion.
        """
        launcher = fake_qdrant_binary(tmp_path, FAKE_SERVER.format(enforce=True))
        supervisor = _supervisor(_held_to_its_own_digest(launcher), tmp_path)
        try:
            supervisor.start(timeout=30.0)
            assert supervisor.is_alive()
            with launcher.open("ab") as stream:
                stream.write(_HARMLESS_TAIL)

            restarted = supervisor.restart(timeout=30.0)
            alive = supervisor.is_alive()
        finally:
            assert supervisor.stop(timeout=10.0)

        assert restarted is False
        assert alive is False
        assert supervisor.pid is None

    def test_a_recovery_retry_refuses_a_binary_changed_since_the_first_spawn(
        self, tmp_path: Path
    ) -> None:
        """The retry after a quarantine is a spawn like any other.

        The child changes its own launcher and then dies naming a collection.
        The loop quarantines that collection and spawns again; that second
        spawn must stop on the changed launcher.

        Mutation it catches: checking once per ``start()`` instead of once per
        spawn. The launcher then runs a second time, the run count below reads
        two, and the start ends in the readiness failure instead of the
        refusal.
        """
        storage = tmp_path / "qdrant" / "storage"
        (storage / "collections" / "r0000_vault_docs").mkdir(parents=True)
        runs = tmp_path / "runs.txt"
        suffix = ".bat" if sys.platform == "win32" else ".sh"
        launcher = fake_qdrant_binary(
            tmp_path,
            _REWRITES_ITS_LAUNCHER_THEN_DIES.format(
                runs=str(runs),
                launcher=str(tmp_path / f"rewriter{suffix}"),
                appended=_HARMLESS_TAIL,
            ),
            name="rewriter",
        )
        assert launcher == tmp_path / f"rewriter{suffix}"
        supervisor = _supervisor(_held_to_its_own_digest(launcher), tmp_path)
        try:
            with pytest.raises(QdrantBinaryError) as refused:
                supervisor.start(timeout=30.0)
        finally:
            assert supervisor.stop(timeout=10.0)

        assert refused.value.error == "qdrant_binary_unverified"
        # The first spawn ran and was recovered from, so the refusal came from
        # the retry and not from a start that never got going.
        assert (storage / "quarantine").is_dir()
        assert runs.read_text(encoding="utf-8") == "run\n"


class TestAnOperatorSettingBinaryRunsUnpinnedAndSaysSo:
    """The one source with no digest is still the file that was named."""

    def test_it_runs_without_a_digest_and_reports_its_source(
        self, tmp_path: Path
    ) -> None:
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(unpinned(launcher), tmp_path)
        try:
            supervisor.spawn()
            process = supervisor._proc
            assert process is not None
            assert process.wait(timeout=30.0) == 0
        finally:
            assert supervisor.stop(timeout=10.0)

        assert marker.read_text(encoding="utf-8") == "ran"
        assert supervisor.state().to_dict()["binary_source"] == "env"
        assert supervisor.binary_source.operator_supplied

    def test_a_file_swapped_for_a_link_after_it_was_named_is_refused(
        self, tmp_path: Path
    ) -> None:
        """What was named is what runs, at every spawn.

        The link points at a working launcher, so a spawn that did not look
        again would run it.

        Mutation it catches: skipping the shape check for the operator setting
        inside the spawn check. The launcher then runs through the link and
        this fails on the missing ``QdrantBinaryError``.
        """
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(unpinned(launcher), tmp_path)
        moved = launcher.with_name(f"moved-{launcher.name}")
        launcher.rename(moved)
        launcher.symlink_to(moved)
        try:
            with pytest.raises(QdrantBinaryError) as refused:
                supervisor.spawn()
        finally:
            assert supervisor.stop(timeout=10.0)

        assert refused.value.error == "qdrant_binary_invalid"
        assert "is a symbolic link" in str(refused.value)
        assert not marker.exists(), "a binary reached through a link was run"


class TestAnAttachedSupervisorNeverSpawns:
    """Attached means no binary, so there is nothing a spawn could run."""

    def test_spawn_and_restart_refuse_without_creating_a_process(
        self, tmp_path: Path
    ) -> None:
        """Mutation it catches: removing the no-binary refusal from ``spawn()``.

        The spawn then reaches the check with nothing to check, and this fails
        on an ``AttributeError`` escaping the expected refusal.
        """
        supervisor = _supervisor(None, tmp_path)

        with pytest.raises(RuntimeError, match="attached to a qdrant server"):
            supervisor.spawn()
        assert supervisor.restart(timeout=1.0) is False
        assert supervisor.pid is None
        assert supervisor.binary_source is BinarySource.ATTACHED
        assert supervisor.state().to_dict()["binary_source"] == "attached"
        assert not supervisor.binary_source.operator_supplied

    def test_the_attached_source_is_never_executable(self, tmp_path: Path) -> None:
        """A binary labelled attached is refused, whatever file it names.

        Mutation it catches: letting any source that is not the operator
        setting fall through to the digest comparison. The file below matches
        its own digest, so the check then passes and this fails on the missing
        ``QdrantBinaryError``.
        """
        launcher, _marker = _marker_launcher(tmp_path)
        labelled = _held_to_its_own_digest(launcher, BinarySource.ATTACHED)

        with pytest.raises(QdrantBinaryError, match="never executed"):
            verify_resolved_binary(labelled)


class TestTheSourceVocabulary:
    def test_only_the_two_operator_sources_are_operator_supplied(self) -> None:
        supplied = {source for source in BinarySource if source.operator_supplied}
        assert supplied == {
            BinarySource.OPERATOR_SETTING,
            BinarySource.MANAGED_OPERATOR,
        }

    def test_the_values_status_surfaces_print_are_stable(self) -> None:
        assert {source.name: source.value for source in BinarySource} == {
            "OPERATOR_SETTING": "env",
            "MANAGED_DOWNLOAD": "provisioned",
            "MANAGED_OPERATOR": "registered",
            "ATTACHED": "attached",
        }


class TestSpawnIsTheOnlyPlaceAProcessIsCreated:
    """The check guards every process creation only if there is one of them."""

    _CREATORS = ("subprocess.", "os.spawn", "os.exec", "os.startfile", "os.system")

    def test_every_process_creation_sits_in_spawn_after_the_check(self) -> None:
        """A second creation site would be a second, unchecked way to run it.

        Mutation it catches: dropping the check from ``spawn()`` (no check is
        found before the creation), or creating a process in any other
        function of the module (the owner set stops being ``{"spawn"}``).
        """
        tree = ast.parse(Path(_supervise.__file__).read_text(encoding="utf-8"))
        creations: list[tuple[str, int]] = []
        checks: list[tuple[str, int]] = []
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                called = ast.unparse(call.func)
                if called.startswith(self._CREATORS):
                    creations.append((function.name, call.lineno))
                elif called == "verify_resolved_binary":
                    checks.append((function.name, call.lineno))

        assert creations, "the supervisor creates no process here; has it moved?"
        assert {owner for owner, _line in creations} == {"spawn"}
        checked_at = [line for owner, line in checks if owner == "spawn"]
        assert checked_at, "spawn() creates a process without checking the binary"
        assert max(checked_at) < min(line for _owner, line in creations)
