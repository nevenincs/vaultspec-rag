"""Guard tests for checking the qdrant binary inside every spawn.

A check made once, when the service resolves its binary, says nothing about
the file a later spawn runs: the heartbeat restarts a dead child, and the
recovery loop re-spawns after moving a collection aside. So the check lives
where the process is created, and these tests reach it by each of the three
ways a child comes to exist.

No mocks: every binary here is a real launcher on the real filesystem, the
supervisor spawns it as a real subprocess, and "it never ran" is proven by a
file the launcher would have written. A managed binary is stood in for by a
launcher held to its own digest, because no stand-in can hash to a release
executable's committed digest; the check it then passes or fails is the same
comparison.

Every test here is a guard and has been observed failing for its intended
reason; the mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from ..qdrant_runtime import _spawn_trust, _supervise
from ..qdrant_runtime._constants import BinarySource, ResolvedBinary
from ..qdrant_runtime._provision import file_sha256
from ..qdrant_runtime._resolve import QdrantBinaryError
from ..qdrant_runtime._spawn_trust import verify_resolved_binary
from ..qdrant_runtime._supervise import QdrantSupervisor
from ._fake_qdrant_binary import FAKE_SERVER, fake_qdrant_binary, unpinned
from ._ports import free_loopback_port

pytestmark = [pytest.mark.unit]

#: Every source a process can be created from, with the remedy its refusal
#: must name. Neither has a way to run without a digest.
_RUNNABLE_SOURCES = (
    (BinarySource.MANAGED_DOWNLOAD, "vaultspec-rag server qdrant install --upgrade"),
    (BinarySource.OPERATOR_SETTING, "VAULTSPEC_RAG_QDRANT_BINARY_SHA256"),
)

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
    launcher: Path, source: BinarySource = BinarySource.MANAGED_DOWNLOAD
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


class TestEveryBinaryIsHashedBeforeItRuns:
    """No binary of any source runs on a digest that is wrong, empty, or absent."""

    @pytest.mark.parametrize(("source", "remedy"), _RUNNABLE_SOURCES)
    def test_a_binary_that_does_not_match_its_digest_never_runs(
        self, source: BinarySource, remedy: str, tmp_path: Path
    ) -> None:
        """Mutation it catches: dropping the check from ``spawn()``.

        The launcher then runs, no exception is raised, and this fails on the
        missing ``QdrantBinaryError``. Exempting the operator source from the
        comparison fails only that source's case, the same way.
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
        assert remedy in str(refused.value)
        assert supervisor.pid is None
        assert not marker.exists(), "a binary that failed its digest was run"

    @pytest.mark.parametrize(("source", "_remedy"), _RUNNABLE_SOURCES)
    def test_a_binary_with_no_digest_never_runs(
        self, source: BinarySource, _remedy: str, tmp_path: Path
    ) -> None:
        """An empty digest is a mismatch, not a reason to skip the check.

        Mutation it catches: returning early from the check when the expected
        digest is empty. That is the branch that let an install whose manifest
        recorded no digest, and any operator binary at all, run unverified;
        with it restored the launcher runs and this fails on the missing
        ``QdrantBinaryError``.
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

    @pytest.mark.parametrize(("source", "_remedy"), _RUNNABLE_SOURCES)
    def test_a_binary_that_matches_its_digest_runs(
        self, source: BinarySource, _remedy: str, tmp_path: Path
    ) -> None:
        """The control: the refusals above are not a spawn that never works."""
        launcher, marker = _marker_launcher(tmp_path)
        supervisor = _supervisor(_held_to_its_own_digest(launcher, source), tmp_path)
        try:
            supervisor.spawn()
            process = supervisor._proc
            assert process is not None
            assert process.wait(timeout=30.0) == 0
        finally:
            assert supervisor.stop(timeout=10.0)

        assert marker.read_text(encoding="utf-8") == "ran"
        assert supervisor.state().to_dict()["binary_source"] == str(source)


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


class TestAnOperatorBinaryIsStillTheFileThatWasNamed:
    """An operator binary is refused by name when it stops being that file."""

    def test_a_file_swapped_for_a_link_after_it_was_named_is_refused(
        self, tmp_path: Path
    ) -> None:
        """What was named is what runs, at every spawn.

        The link points at the very launcher whose digest was declared, so the
        digest alone would pass it; only looking at the name again refuses it.

        Mutation it catches: skipping the shape check for the operator setting
        inside the spawn check. The refusal then comes from the hold instead
        and this fails on the error-code assertion.
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
    def test_only_the_operator_settings_source_is_operator_supplied(self) -> None:
        supplied = {source for source in BinarySource if source.operator_supplied}
        assert supplied == {BinarySource.OPERATOR_SETTING}

    def test_the_values_status_surfaces_print_are_stable(self) -> None:
        """There is no source for a binary an operator put in the managed dir.

        Mutation it catches: adding such a source back fails the equality
        below, which is the only place the whole vocabulary is written out.
        """
        assert {source.name: source.value for source in BinarySource} == {
            "OPERATOR_SETTING": "env",
            "MANAGED_DOWNLOAD": "provisioned",
            "ATTACHED": "attached",
        }


class TestAProcessIsCreatedOnlyInsideTheHold:
    """The check guards a process creation only if the creation is inside it.

    Behaviour proves a refused binary does not run. It cannot prove there is
    no second way to run one, or that the process is created while the checked
    file is still held and from that file - those are properties of where the
    creation call sits, so they are read off the source.
    """

    _CREATORS = ("subprocess.", "os.spawn", "os.exec", "os.startfile", "os.system")

    @classmethod
    def _creations(cls, module_file: str) -> list[tuple[str, ast.Call]]:
        """Every process-creating call in a module, with its enclosing function."""
        tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
        return [
            (function.name, call)
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func).startswith(cls._CREATORS)
        ]

    def test_the_supervisor_creates_no_process_of_its_own(self) -> None:
        """A creation call in the supervisor would be a way around the check.

        Mutation it catches: any ``subprocess`` call added to the supervisor
        module fails the emptiness assertion below.
        """
        assert not [owner for owner, _call in self._creations(_supervise.__file__)]
        spawn = Path(_supervise.__file__).read_text(encoding="utf-8")
        assert "self._proc = spawn_verified(" in spawn

    def test_every_creation_is_inside_the_hold_and_names_the_held_file(self) -> None:
        """Created while the checked file is held, and from that file.

        Mutations it catches: moving a creation call out of the ``with``
        block that holds the verified file fails the containment assertion;
        dropping ``executable=`` or pointing it at the bare path fails the
        last assertion, and with it returns the Windows command-line lookup
        that completes a missing name with ``.exe``.
        """
        creations = self._creations(_spawn_trust.__file__)
        assert creations, "no process is created here; has the spawn moved?"
        assert {owner for owner, _call in creations} == {"spawn_verified"}

        tree = ast.parse(Path(_spawn_trust.__file__).read_text(encoding="utf-8"))
        holds = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            and [ast.unparse(item) for item in node.items]
            == ["_verified(resolved) as held"]
        ]
        held_calls = {
            (call.lineno, call.col_offset)
            for hold in holds
            for call in ast.walk(hold)
            if isinstance(call, ast.Call)
        }
        for _owner, call in creations:
            assert (call.lineno, call.col_offset) in held_calls, (
                f"line {call.lineno} creates a process outside the hold"
            )
            executable = [k.value for k in call.keywords if k.arg == "executable"]
            assert [ast.unparse(value) for value in executable] == [
                "held.launch_path"
            ], f"line {call.lineno} does not create the process from the held file"

    def test_a_file_that_changed_under_the_spawn_stops_the_new_process(self) -> None:
        """Where the hold cannot freeze the file, the process is checked after.

        The gap this covers is a few instructions wide and cannot be entered
        from a test without rewriting the function, so the test reads that the
        look-again is still the statement after the creation, still inside the
        hold, and still kills before it raises. What the look-again itself
        detects is proven by behaviour beside the hold.

        Mutation it catches: deleting the look-again, or raising without
        killing, fails the assertion on the block below.
        """
        tree = ast.parse(Path(_spawn_trust.__file__).read_text(encoding="utf-8"))
        look_again = [
            node
            for hold in ast.walk(tree)
            if isinstance(hold, ast.With)
            for node in hold.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "not held.unchanged(resolved.sha256)"
        ]
        assert len(look_again) == 1
        steps = [ast.unparse(step) for step in look_again[0].body]
        assert steps[0] == "proc.kill()"
        assert steps[-1].startswith("raise _refusal(resolved, ")
        creation_lines = [
            call.lineno for _owner, call in self._creations(_spawn_trust.__file__)
        ]
        assert look_again[0].lineno > max(creation_lines)
