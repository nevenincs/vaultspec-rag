"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from .._operator_commands import IndexCommandOptions, index_command
from ._process_probe_guard_helpers import (
    _PACKAGE_ROOT,
    function_nodes,
    is_attr_call,
    parsed_production_sources,
    _production_sources,
)

pytestmark = [pytest.mark.unit]


class TestFinalizationPhaseWalkHasOneCopy:
    """The durable metadata-publication transition exists once, on the base.

    ``CodeRunCheckpoint`` and ``DocumentRunCheckpoint`` each carried the same
    phase walk: INGESTING to STALE_RECONCILED, bail unless STALE_RECONCILED,
    publish, advance to METADATA_PUBLISHED. Only the publish call differed.

    The duplicated part is a DURABLE transition - it survives a restart - so
    two copies could disagree about when metadata is publishable and the
    disagreement would persist across runs. The base already declared
    ``_content_kind`` and ``_kind_label`` for exactly this, and its docstring
    already promised subclasses inherit the generation-publication decisions.
    """

    def test_only_the_base_advances_the_finalization_phase(self) -> None:
        # Keys on STALE_RECONCILED: it appears only in the walk that advances
        # through it, so a second mention means a second copy of the durable
        # transition. Reading the phase elsewhere is fine and stays uncaught.
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_checkpoint_common.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "FinalizationPhase.STALE_RECONCILED" in line
        ]
        assert not find_offenders, (
            f"the finalization phase walk is duplicated at {find_offenders}; call "
            "RunCheckpointBase.publish_metadata_transition so the durable "
            "transition has one definition"
        )

    def test_each_subclass_supplies_only_its_publish_call(self) -> None:
        import inspect

        from ..indexer._checkpoint_common import RunCheckpointBase
        from ..indexer._document_checkpoint import DocumentRunCheckpoint
        from ..indexer._run_checkpoint import CodeRunCheckpoint

        assert hasattr(RunCheckpointBase, "publish_metadata_transition")
        for cls in (CodeRunCheckpoint, DocumentRunCheckpoint):
            source = inspect.getsource(cls.publish_metadata)
            assert "publish_metadata_transition" in source, (
                f"{cls.__name__}.publish_metadata must go through the shared "
                "transition rather than walking the phases itself"
            )
            # The label the envelope emits is built from _kind_label, so each
            # subclass must still declare the one it had.
            assert cls._kind_label in {"code", "document"}


class TestShortfallProseHasOneHome:
    """The words warning an operator their index is short have one source.

    Three renderers described the same deficits: two on the command line and
    one in the service summary. They had already drifted - the summary named
    the point shortfall alone, so a publication covering a fraction of the
    files it named reached an agent as an unqualified count, and the two
    surfaces disagreed on the noun. Both the consequence clause and the
    remediation command now live beside the figures they describe.
    """

    def test_only_the_breadth_module_spells_the_consequence(self) -> None:
        from .._index_breadth import SHORTFALL_CONSEQUENCE

        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_index_breadth.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "not evidence that no such" in line
        ]
        assert not find_offenders, (
            f"the shortfall consequence is spelled again at {find_offenders}; import "
            f"SHORTFALL_CONSEQUENCE ({SHORTFALL_CONSEQUENCE!r}) so both surfaces "
            "cannot describe one deficit differently"
        )

    def test_only_the_breadth_module_spells_the_remediation(self) -> None:
        from .._index_breadth import SHORTFALL_REMEDIATION

        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_index_breadth.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if SHORTFALL_REMEDIATION in line
        ]
        assert not find_offenders, (
            f"the shortfall remediation is spelled again at {find_offenders}; import "
            "SHORTFALL_REMEDIATION so an operator is never sent to a command a "
            "rename removed from one copy"
        )

    def test_every_surface_walks_both_shortfall_kinds(self) -> None:
        """Neither renderer may read one key and stay blind to the other."""
        import inspect

        from ..cli._search import _render_shortfall_warnings
        from ..server._routes import search_summary

        for renderer in (_render_shortfall_warnings, search_summary):
            source = inspect.getsource(renderer)
            assert "shortfall_warnings" in source, (
                f"{renderer.__name__} must walk the shared reader; keying on one "
                "shortfall name is how the summary went silent on file breadth"
            )
            assert '"file_shortfall"' not in source, (
                f"{renderer.__name__} reaches for a shortfall key directly, which "
                "is what lets one kind be handled and the other forgotten"
            )


class TestBackoffMathHasOneHome:
    """Capped exponential backoff is computed in ``_backoff`` and nowhere else.

    Five sites grew their own: the file-replacement ladder, the watcher retry
    policy, and three copies inside the watcher's replacement scheduler. They
    had already diverged where it counts - the retry policy clamped the
    exponent so a long failure streak could not overflow, and the three
    scheduler copies, written from the same idea, did not.
    """

    def test_only_the_backoff_module_raises_two_to_a_power(self) -> None:
        """A new capped exponential anywhere else is a new copy."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_backoff.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Pow)
                and isinstance(node.left, ast.Constant)
                and node.left.value in (2, 2.0)
            )
        assert not find_offenders, (
            f"base-2 exponentiation outside the backoff module at {find_offenders}; "
            "call capped_exponential or jittered_backoff so the exponent clamp "
            "cannot be present in one copy and absent in the next"
        )

    def test_the_replacement_constants_feed_one_scheduler(self) -> None:
        """Only ``defer_replacement`` may turn the streak into a deadline."""
        from .. import watcher

        source = Path(watcher.__file__).read_text(encoding="utf-8")
        uses = [
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if "_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS" in line
            and not line.startswith("_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS")
        ]
        assert len(uses) == 1, (
            f"the replacement backoff base is read at {uses}; exactly one "
            "reader (defer_replacement) may exist, or the streak increment and "
            "the deadline drift apart again"
        )

    def test_a_long_failure_streak_returns_the_cap_instead_of_overflowing(
        self,
    ) -> None:
        """The defect the three scheduler copies carried.

        ``2 ** (streak - 1)`` builds an integer before the float multiply, so a
        streak past 1024 raised ``OverflowError`` instead of returning the cap
        - reachable after about eight and a half hours of sustained
        replacement failure at the thirty-second cap.

        Proven able to fail: dropping the ``min(exponent, _MAX_EXPONENT)``
        clamp in ``capped_exponential`` fails this test on the ``pytest.fail``
        below, which is why the overflow is caught rather than left to error
        the test out.
        """
        from .._backoff import capped_exponential

        for streak in (1025, 100_000):
            try:
                delay = capped_exponential(streak - 1, base=1.0, cap=30.0)
            except OverflowError as exc:
                pytest.fail(f"streak {streak} overflowed instead of capping: {exc}")
            assert delay == 30.0

    def test_jitter_cannot_push_a_wait_past_the_cap(self) -> None:
        """A cap is a cap; an upward draw must not exceed it.

        The replacement ladder previously applied jitter to an already-capped
        nominal without re-clamping, so its longest sleep ran a quarter over
        the maximum it declared.

        Proven able to fail: returning ``max(0.0, nominal + jitter)`` without
        the outer ``min(cap, ...)`` fails this test on the upper-bound
        assertion below.
        """
        from .._backoff import jittered_backoff

        for exponent in range(0, 12):
            for unit in (0.0, 0.5, 1.0):
                delay = jittered_backoff(
                    exponent, base=0.005, cap=0.15, fraction=0.25, random_unit=unit
                )
                assert 0.0 <= delay <= 0.15, (exponent, unit, delay)


class TestNoCompatibilityAliases:
    """A canonical name is imported and used, never rebound under a second one.

    Fourteen module-level aliases had accumulated - ``_WIN_CREATE_NO_WINDOW =
    WIN_CREATE_NO_WINDOW`` and friends - each giving one fact a second name in
    a module that did not own it. Two carried comments admitting the motive:
    "Kept under the existing names so importers and tests are unaffected" and
    "Compatibility aliases for the established focused rollback tests". An
    alias reads as an abstraction, hides the real owner, and survives every
    later refactor, so there must not be one.

    The scan is structural rather than name-based, because the next alias will
    not be spelled like the last one.
    """

    #: Empty, and meant to stay that way. It is the staging mechanism, not a
    #: permission list: an entry records an alias a cleanup has not reached
    #: yet, and the companion test below fails once that alias is gone so the
    #: entry cannot outlive it and quietly re-permit the name.
    KNOWN: ClassVar[frozenset[tuple[str, str]]] = frozenset()

    @staticmethod
    def _module_level_imports(tree: ast.Module) -> set[str]:
        """Return every name a top-level import binds in *tree*."""
        imported: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imported.update(a.asname or a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.asname or a.name.split(".")[0] for a in node.names)
        return imported

    @staticmethod
    def _rebinds_an_import(value: ast.expr, imported: set[str]) -> bool:
        """``X = Y``, or ``X = mod.Y``, where the right-hand side is imported."""
        return (isinstance(value, ast.Name) and value.id in imported) or (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in imported
        )

    def test_no_module_rebinds_an_imported_name(self) -> None:
        find_offenders: list[str] = []
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            imported = self._module_level_imports(tree)
            for node in tree.body:
                if not (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    continue
                target = node.targets[0].id
                if not self._rebinds_an_import(node.value, imported):
                    continue
                if (path.name, target) in self.KNOWN:
                    continue
                find_offenders.append(
                    f"{path.name}:{node.lineno} {target} = {ast.unparse(node.value)}"
                )
        assert not find_offenders, (
            f"compatibility aliases at {find_offenders}; import the canonical name "
            "and use it, rather than giving one fact a second name in a module "
            "that does not own it"
        )

    def test_every_allowlisted_alias_still_exists(self) -> None:
        """The allowlist must not outlive what it allows.

        An entry left behind after its alias is gone would silently permit a
        fresh alias of that name in that module. Vacuously true while KNOWN is
        empty, which is the intended resting state.
        """
        stale = [
            f"{module}:{name}"
            for module, name in sorted(self.KNOWN)
            if not any(
                path.name == module and f"{name} = " in path.read_text(encoding="utf-8")
                for path in _production_sources()
            )
        ]
        assert not stale, (
            f"allowlist entries with no alias behind them: {stale}; drop them "
            "so the scan covers those modules fully again"
        )


class TestAtomicJsonPublishHasOneWriter:
    """Publishing a JSON document goes through ``write_json_atomically``.

    Thirteen sites wrote the sequence out: serialize, write a temp sibling,
    replace. Two had learned to unlink the temp in a ``finally`` and to give
    it a name two writers could not collide on; the other eleven had not, so a
    failed write or a replace outlasting the sharing ladder left the temp on
    disk forever. The suite already asserted no temp survives in several
    places, which is exactly how the careful and naive versions sat side by
    side without the gap being visible.
    """

    #: Streams its sidecar entry by entry and fsyncs the handle, so the whole
    #: document is never held in memory. That is a different operation, not a
    #: copy of this one: it exists because the code sidecar can be large.
    STREAMING: ClassVar[str] = "_code_meta.py"

    #: Writes its recovery marker to a temp whose NAME a reaper globs, so the
    #: spelling is a contract rather than an implementation detail. Delegating
    #: it would leave the sweeper matching nothing and its test vacuously
    #: green. Its durability step is shared; only the naming is its own.
    NAMED_TEMP_CONTRACT: ClassVar[str] = "watcher_retry.py"

    @staticmethod
    def _call_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        """Return canonical names of every call in one function."""
        names: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            if isinstance(node.func, ast.Attribute) and isinstance(
                node.func.value, ast.Name
            ):
                names.add(f"{node.func.value.id}.{node.func.attr}")
        return names

    @staticmethod
    def _opens_a_directory(call: ast.Call) -> bool:
        """Return whether *call* opens a directory with bare ``O_RDONLY``."""
        if not is_attr_call(call, "os", "open") or len(call.args) != 2:
            return False
        flags = call.args[1]
        return (
            isinstance(flags, ast.Attribute)
            and flags.attr == "O_RDONLY"
            and isinstance(flags.value, ast.Name)
            and flags.value.id == "os"
        )

    @classmethod
    def _directory_fsync_functions(
        cls, tree: ast.Module
    ) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        """Return functions which both open a directory and fsync a descriptor."""
        return [node for node in function_nodes(tree) if cls._is_directory_fsync(node)]

    @classmethod
    def _is_directory_fsync(cls, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Return whether one function has both directory-sync operations."""
        calls = [inner for inner in ast.walk(node) if isinstance(inner, ast.Call)]
        return any(cls._opens_a_directory(call) for call in calls) and any(
            is_attr_call(call, "os", "fsync")
            and bool(call.args)
            and isinstance(call.args[0], ast.Name)
            for call in calls
        )

    def test_no_function_hand_rolls_the_serialize_and_replace(self) -> None:
        """Structural, not textual: the first version of this scan missed four.

        It keyed on ``json.dumps`` within a few lines of a replace, so it saw
        neither the ``json.dump(stream)`` form nor the sites whose serialize
        and replace sat further apart. Both shapes were live. This walks each
        function and asks whether it does BOTH, at any distance and in either
        spelling.
        """
        excluded = {"_atomic_write.py", self.STREAMING, self.NAMED_TEMP_CONTRACT}
        find_offenders = [
            f"{path.name}:{node.lineno} {node.name}"
            for path, tree in parsed_production_sources(
                _production_sources(), excluded
            )
            for node in function_nodes(tree)
            if {"json.dump", "json.dumps"} & self._call_names(node)
            and {"replace_atomically", "replace_durably"} & self._call_names(node)
        ]
        assert not find_offenders, (
            f"hand-rolled atomic JSON publish at {find_offenders}; call "
            "write_json_atomically so the temp file is named without collision "
            "and removed when the write or the replace fails"
        )

    def test_the_directory_fsync_has_one_implementation(self) -> None:
        """Forcing a directory entry to disk belongs to ``_atomic_write``.

        A second copy no-opped on Windows, so a crash-recovery record got a
        replace with no write-through on the platform this project targets
        first - the weaker half of a guarantee its own name promised. A third
        synced freshly created directories, a different purpose built from the
        identical three syscalls.

        Keyed on the shape only a directory sync has: opened with a bare
        ``os.O_RDONLY`` and fsynced by descriptor. A file sync passes
        ``stream.fileno()``, and a file opened for writing ORs its flags, so
        neither matches. Two looser predicates were tried first and both
        flagged modules that merely open a file - one on ``os.O_RDONLY``
        appearing anywhere in a line, one on any ``os.open`` plus any
        descriptor fsync.
        """

        find_offenders = [
            f"{path.name}:{node.lineno} {node.name}"
            for path, tree in parsed_production_sources(
                _production_sources(), {"_atomic_write.py"}
            )
            for node in self._directory_fsync_functions(tree)
        ]
        assert not find_offenders, (
            f"a directory fsync outside _atomic_write at {find_offenders}; call "
            "fsync_directory, which replace_durably also uses, so the Windows "
            "no-op and the POSIX sync are decided in one place"
        )

    def test_the_temp_file_is_removed_when_the_replace_fails(self) -> None:
        """The defect the eleven naive copies carried.

        Proven able to fail: dropping the ``finally`` in
        ``write_json_atomically`` fails this test on the leftovers assertion
        below, not on a crash.
        """
        from unittest.mock import patch

        from .. import _atomic_write

        directory = Path(tempfile.mkdtemp())
        target = directory / "sidecar.json"

        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError(28, "No space left on device")

        with (
            patch.object(_atomic_write, "replace_atomically", _refuse),
            pytest.raises(OSError, match="No space left"),
        ):
            _atomic_write.write_json_atomically(target, {"a": 1})

        leftovers = sorted(p.name for p in directory.iterdir())
        assert leftovers == [], f"temp file survived a failed replace: {leftovers}"

    def test_the_temp_name_cannot_collide_between_writers(self) -> None:
        """Two writers of one target must not choose the same temp path.

        ``path.with_suffix(".tmp")`` gave them the same name, and gave anyone
        watching the directory a predictable one to pre-plant.

        Proven able to fail: replacing the random component with a constant
        fails this test on the distinctness assertion below.
        """
        from .. import _atomic_write

        directory = Path(tempfile.mkdtemp())
        target = directory / "sidecar.json"
        seen: set[str] = set()
        real_replace = _atomic_write.replace_atomically

        def _capture(source: Path | str, destination: Path | str) -> None:
            seen.add(Path(str(source)).name)
            real_replace(source, destination)

        with patch.object(_atomic_write, "replace_atomically", _capture):
            for index in range(8):
                _atomic_write.write_json_atomically(target, {"n": index})

        assert len(seen) == 8, f"temp names repeated across writers: {sorted(seen)}"
        assert all(name.startswith(".sidecar.json.") for name in seen), sorted(seen)


class TestOperatorCommandsHaveOneSpelling:
    """A command we tell an operator to run is spelled in one place.

    A remediation line is an instruction someone pastes into a shell, so every
    flag in it promises that flag exists. ``server jobs`` once took
    ``--running``; the option became ``--state active`` and two tests now
    exist for no reason other than asserting the old spelling stays gone. A
    guard against a renamed flag reappearing is a guard against copies that
    were missed the first time.
    """

    def test_no_module_builds_its_own_port_option(self) -> None:
        """Four modules computed this one conditional; three identically.

        Proven able to fail: reintroducing the inline conditional in any
        module fails this test on the offender list below.
        """
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '" --port {' in line or '" --port %' in line
        ]
        assert not find_offenders, (
            f"a hand-built --port option at {find_offenders}; call port_option so "
            "one rule decides when a port is known enough to name"
        )

    def test_no_module_spells_the_jobs_command(self) -> None:
        """Its flags are the ones with a demonstrated history of changing."""
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "vaultspec-rag server jobs " in line
        ]
        assert not find_offenders, (
            f"a hand-spelled server-jobs command at {find_offenders}; call "
            "server_jobs_command so a renamed flag changes in one place"
        )

    def test_no_module_spells_a_bare_status_or_start_command(self) -> None:
        """A command handed over as a whole string must come from the builder.

        Scoped to a string that IS the command, which is what a caller passes
        as a next action. A sentence that mentions the tool in passing is
        prose and keeps its own words; the sites that hand an operator
        something to run do not.
        """
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_operator_commands.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                text = node.value
                if text.startswith(
                    ("vaultspec-rag server status", "vaultspec-rag server start")
                ):
                    find_offenders.append(f"{path.name}:{node.lineno} {text!r}")
        assert not find_offenders, (
            f"a hand-spelled status/start command at {find_offenders}; call "
            "server_status_command or server_start_command so a renamed flag "
            "changes in one place"
        )

    def test_the_not_running_message_has_one_wording(self) -> None:
        """Ten modules carried this sentence verbatim.

        An operator meeting it from two different verbs must not be told two
        different things, and the command inside it has to survive a rename.
        """
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "Service is not running. Start it with" in line
        ]
        assert not find_offenders, (
            f"the service-not-running sentence is spelled again at {find_offenders}; "
            "import SERVICE_NOT_RUNNING_MESSAGE"
        )

    def test_no_module_spells_an_index_command(self) -> None:
        """The index verb is a family, not a set of unrelated one-offs.

        Counting repeats made this look like it was not duplication - each of
        the thirteen sites named a different flag combination. What repeats is
        the VOCABULARY: the verb, its flag names and their order, and which
        source spellings exist.
        """
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_operator_commands.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "vaultspec-rag index" in line
        ]
        assert not find_offenders, (
            f"a hand-spelled index command at {find_offenders}; call index_command "
            "so a renamed flag changes in one place"
        )

    def test_every_source_reaches_the_rebuild_remediation(self) -> None:
        """A source the flag accepts must be a source the operator is offered.

        The four spellings were hand-enumerated, so a new member of
        PublicSourceType would have been accepted by --type and silently
        missing from the rebuild remediation - the operator would never be
        told the command that fixes their index.

        Proven able to fail: pinning that remediation to a fixed list fails
        this test on the missing-source assertion below.
        """
        import inspect

        from .._source_types import PublicSourceType
        from ..cli import _index

        source = inspect.getsource(_index)
        rendered = {
            index_command(member, IndexCommandOptions(rebuild=True))
            for member in PublicSourceType
        }
        assert len(rendered) == len(PublicSourceType), (
            "two source types render the same rebuild command"
        )
        assert "for source in PublicSourceType" in source, (
            "the rebuild remediation must be derived from PublicSourceType, "
            "not enumerated, or a new source type is accepted by --type and "
            "never offered to the operator"
        )

    def test_the_renamed_flag_is_not_reachable(self) -> None:
        """``--running`` was replaced by ``--state active`` and must stay gone.

        The builder is the only thing that can emit this command now, so this
        asks the builder rather than scanning for a string: no argument
        combination may produce the retired option.
        """
        from .._operator_commands import server_jobs_command

        rendered = [
            server_jobs_command(),
            server_jobs_command(8766),
            server_jobs_command(8766, failed=True),
            server_jobs_command(8766, index="code"),
            server_jobs_command(8766, state="finished"),
        ]
        assert all("--running" not in command for command in rendered), rendered
        assert all(
            command.startswith("vaultspec-rag server jobs") for command in rendered
        )
