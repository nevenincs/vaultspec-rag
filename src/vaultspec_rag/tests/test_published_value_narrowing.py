"""Every surface narrows a published value through the same three readers.

A published field arrives as ``object`` and has to become a number, a count,
or a signal before it can be rendered. When each renderer wrote its own
``isinstance`` test for that, the tests disagreed: a Python ``bool`` is an
``int``, so an unguarded ``isinstance(value, int | float)`` accepted ``True``
and rendered it as ``1``. That produced a fabricated "1 of 1" completion, a
"GPU: 1% busy" reading, a one-second retry delay, and - worst - a job
timestamp of ``True`` reading as a 1970 clock time instead of as unreported.

The readers are the contract, so they are pinned here cell by cell rather
than sampled, and the formatters are pinned as the backstop behind them.

No mocks, patches, or fakes: the real readers and the real renderer run, and
the assertions read what they returned and printed.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from .. import jobs as _jobs_module
from ..cli._cli_format import _format_mb, _format_seconds, compact_duration
from ..cli._jobs_tui import _capability, _fetch_error
from ..cli._service_jobs_presentation import _nested_section, render_jobs_result
from ..cli._service_watcher import _format_delay_milliseconds, _format_delay_seconds
from ..jobs import count, flag, mapping, measurement
from ..server._routes_jobs import _job_capability

pytestmark = [pytest.mark.unit]


#: One hostile input per row, with the exact answer each reader owes it.
#: A measurement accepts a NON-NEGATIVE real number and widens it to
#: ``float``; a count accepts only a whole non-negative number and refuses a
#: fractional one outright rather than truncating it; a signal answers only
#: for a genuine ``bool``. Every reader refuses ``bool`` for a number, which
#: is the whole point of the table - ``True`` and ``False`` are the first two
#: rows for that reason.
#:
#: The negative rows read ``None`` for both numeric readers because these
#: read a published *quantity*, and a quantity is never negative. A signed
#: figure - a delta between two readings, a clock offset - does not belong in
#: these readers at all, and a derived age that can come out negative is
#: clamped at zero by its own helper rather than refused here.
#:
#: ``nan`` and the infinities are refused because JSON has no syntax for them
#: but Python's ``json`` emits and accepts them anyway, so a persisted record
#: can carry one. A ``nan`` is the dangerous shape: it compares ``False``
#: against every threshold, so it suppresses a verdict silently instead of
#: reading as an unreadable field.
_CONTRACT: tuple[tuple[str, object, float | None, int | None, bool | None], ...] = (
    ("bool true", True, None, None, True),
    ("bool false", False, None, None, False),
    ("negative int", -1, None, None, None),
    ("negative float", -1.0, None, None, None),
    ("negative fractional float", -0.5, None, None, None),
    ("zero", 0, 0.0, 0, None),
    ("fractional float", 3.9, 3.9, None, None),
    ("not a number", float("nan"), None, None, None),
    ("positive infinity", float("inf"), None, None, None),
    ("negative infinity", float("-inf"), None, None, None),
    ("numeric string", "3", None, None, None),
    ("empty string", "", None, None, None),
    ("absent", None, None, None, None),
    ("empty list", [], None, None, None),
    ("empty dict", {}, None, None, None),
)

_CONTRACT_IDS = tuple(row[0] for row in _CONTRACT)


def _assert_exact(result: object, expected: object) -> None:
    """Assert value *and* type, so ``True`` can never satisfy an expected ``1``.

    ``True == 1`` and ``False == 0`` in Python, so an equality-only assertion
    passes for exactly the leak this module exists to catch.
    """
    if expected is None:
        assert result is None
        return
    assert type(result) is type(expected)
    assert result == expected


class TestTheReadersNarrowIdentically:
    """The canonical readers, pinned cell by cell.

    Proved able to fail: dropping the ``isinstance(value, bool)`` clause from
    the measurement reader fails the ``bool true`` and ``bool false`` cells on
    ``_assert_exact``'s ``assert result is None``, reporting ``assert 1.0 is
    None``; restoring the clause returns all 45 cells to green.

    Proved able to fail for the non-negative rule: dropping ``or numeric < 0``
    from the measurement reader fails the three negative cells on ``assert
    result is None``, reporting ``assert -1.0 is None``; restoring it returns
    all 45 cells to green.

    Proved able to fail for the finiteness rule: dropping ``not
    math.isfinite(numeric) or`` from the measurement reader fails the ``not a
    number`` and ``positive infinity`` cells on ``assert result is None``,
    reporting ``assert nan is None``; restoring it returns all 45 cells to
    green.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(row[1], row[2]) for row in _CONTRACT],
        ids=_CONTRACT_IDS,
    )
    def test_measurement_answers_every_hostile_input(
        self,
        value: object,
        expected: float | None,
    ) -> None:
        _assert_exact(measurement(value), expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(row[1], row[3]) for row in _CONTRACT],
        ids=_CONTRACT_IDS,
    )
    def test_count_answers_every_hostile_input(
        self,
        value: object,
        expected: int | None,
    ) -> None:
        _assert_exact(count(value), expected)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(row[1], row[4]) for row in _CONTRACT],
        ids=_CONTRACT_IDS,
    )
    def test_flag_answers_every_hostile_input(
        self,
        value: object,
        expected: bool | None,
    ) -> None:
        _assert_exact(flag(value), expected)

    def test_a_count_and_a_measurement_disagree_only_about_fractions(self) -> None:
        # The one deliberate difference between the pair, stated once so a
        # later reader does not "fix" the count into truncating. A slot cap of
        # 3.7 is a broken field, not "3".
        assert measurement(3.9) == 3.9
        assert count(3.9) is None

    def test_a_measurement_reads_a_quantity_not_a_signed_figure(self) -> None:
        # The boundary the reader's docstring names, asserted so a later
        # caller cannot quietly route a delta or a clock offset through it and
        # lose the negative half of its range without a test noticing.
        assert measurement(12.5) == 12.5
        assert measurement(-12.5) is None

    def test_a_derived_age_clamps_where_a_reading_is_refused(self) -> None:
        # The counterpart contract, so the two stay distinguishable: an age
        # computed by subtracting two readings can legitimately come out
        # negative from clock skew, and floors at zero rather than vanishing.
        from ..server._routes_jobs import _age_seconds

        assert _age_seconds(120.0, 100.0) == 0.0
        assert _age_seconds(100.0, 120.0) == 20.0
        assert _age_seconds(None, 100.0) is None


class TestTheMappingReaderNarrowsAContainer:
    """The structural member of the family, which never answers ``None``.

    Proved able to fail: changing ``mapping``'s fallback from ``{}`` to
    ``None`` fails ``test_an_unusable_container_reads_as_empty`` on ``assert
    mapping(value) == {}``, reporting ``assert None == {}``; restoring ``{}``
    returns all 8 cells to green.
    """

    @pytest.mark.parametrize(
        "value",
        [None, "", 0, [], True, 3.9, {"unrelated": 1}],
        ids=[
            "absent",
            "empty string",
            "zero",
            "empty list",
            "bool true",
            "fractional float",
            "populated mapping",
        ],
    )
    def test_it_always_returns_something_gettable(self, value: object) -> None:
        # The whole point of the empty-mapping fallback: a caller can reach
        # for its field without a guard, on every input.
        assert mapping(value).get("missing") is None

    def test_an_unusable_container_reads_as_empty(self) -> None:
        assert mapping(None) == {}
        assert mapping("not a mapping") == {}

    def test_a_real_container_survives_intact(self) -> None:
        payload = {"alive": True, "latency_seconds": 0.25}
        assert mapping(payload) == payload

    def test_it_composes_with_the_scalar_readers(self) -> None:
        # The documented composition, which is how every nested published
        # field is reached now that the twins are gone.
        record = {"progress": {"completed": 3, "last_updated": 1_800_000_000.0}}
        assert count(mapping(record.get("progress")).get("completed")) == 3
        assert measurement(mapping(record.get("progress")).get("last_updated")) == (
            1_800_000_000.0
        )
        assert measurement(mapping(record.get("absent")).get("anything")) is None


#: Every operator-facing formatter that takes an untrusted ``object``, with
#: what it renders for an unreadable value. Enumerated ACROSS MODULES on
#: purpose: an earlier version of this class imported only from the shared
#: format module, and a second identically-named, identically-shaped
#: ``_format_seconds`` in the watcher module - also reading a service payload
#: \- sat outside its field of view and stayed unhardened. Import-scoping a
#: family guard to one module is what let that survive, so the table names the
#: module of every member.
_FORMATTERS: tuple[tuple[str, Callable[[object], str], str], ...] = (
    ("_cli_format._format_seconds", _format_seconds, "not reported"),
    ("_cli_format._format_mb", _format_mb, "not reported"),
    ("_cli_format.compact_duration", compact_duration, "—"),
    (
        "_service_watcher._format_delay_milliseconds",
        _format_delay_milliseconds,
        "not reported",
    ),
    (
        "_service_watcher._format_delay_seconds",
        _format_delay_seconds,
        "not reported",
    ),
)

_FORMATTER_IDS = tuple(row[0] for row in _FORMATTERS)


class TestTheFormattersRefuseABool:
    """The last line of defence behind every routed numeric site.

    Each of these renders a bare ``int`` happily, so a ``bool`` reaching one
    used to print as a real duration or a real size instead of as absent - and
    the delay renderers read a service payload directly, with no reader in
    front of them at all.

    Proved able to fail: dropping the ``isinstance(raw, bool)`` clause from
    the shared seconds formatter fails both of its cells on the ``== "not
    reported"`` assertion, rendering ``True`` as ``1 second`` and ``False`` as
    ``less than 1 second``; restoring the clause returns all 15 cells to
    green. Dropping it from the watcher's delay-seconds renderer fails that
    row's two cells the same way, rendering ``True`` as ``1 second`` and
    ``False`` as ``immediately``.
    """

    @pytest.mark.parametrize(
        ("render", "absent"),
        [(row[1], row[2]) for row in _FORMATTERS],
        ids=_FORMATTER_IDS,
    )
    @pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
    def test_every_formatter_refuses_a_bool(
        self,
        render: Callable[[object], str],
        absent: str,
        value: bool,
    ) -> None:
        assert render(value) == absent

    def test_the_formatters_still_render_a_real_number(self) -> None:
        # The bool guard must not have cost the accepting path, and ``1``
        # is the value a leaked ``True`` would have arrived as.
        assert _format_seconds(1) == "1 second"
        assert _format_mb(1) != "not reported"
        assert compact_duration(1) == "1s"
        assert _format_delay_seconds(1) == "1 second"
        assert _format_delay_milliseconds(1) == "1 millisecond"

    def test_the_delay_renderers_keep_their_own_vocabulary(self) -> None:
        # They are NOT the shared elapsed formatter under another name, and
        # must not be merged into it: zero is a setting rather than a
        # quantity, a fraction survives, and the cascade stops at minutes
        # because that is the unit the knob is configured in.
        assert _format_delay_seconds(0) == "immediately"
        assert _format_seconds(0) == "less than 1 second"
        assert _format_delay_seconds(59.5) == "59.5 seconds"
        assert _format_delay_seconds(3600) == "60 minutes"
        assert _format_seconds(3600) == "1 hour"


class TestABooleanTimestampReadsAsUnreported:
    """A job timestamp of ``True`` must not render as a 1970 clock time."""

    def test_a_boolean_finished_at_does_not_render_as_a_1970_time(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The label the old unguarded narrowing produced, derived rather than
        # hardcoded: ``float(True)`` is 1.0, one second past the epoch, and
        # its clock reading depends on the machine's timezone.
        epoch_label = time.strftime("%H:%M:%S", time.localtime(1.0))
        render_jobs_result(
            {
                "jobs": [
                    {
                        "id": "job-with-a-boolean-timestamp",
                        "phase": "failed",
                        "source": "code",
                        "finished_at": True,
                        "result": "index write refused",
                    }
                ]
            },
            job_id=None,
            port=8765,
        )
        out = capsys.readouterr().out
        assert "time not reported" in out
        assert epoch_label not in out

    def test_a_real_finished_at_still_renders_its_clock_time(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The guard must reject the bool without costing the real timestamp
        # beside it, which is the whole value of the field.
        finished_at = 1_800_000_000.0
        expected = time.strftime("%H:%M:%S", time.localtime(finished_at))
        render_jobs_result(
            {
                "jobs": [
                    {
                        "id": "job-with-a-real-timestamp",
                        "phase": "failed",
                        "source": "code",
                        "finished_at": finished_at,
                        "result": "index write refused",
                    }
                ]
            },
            job_id=None,
            port=8765,
        )
        out = capsys.readouterr().out
        assert expected in out
        assert "time not reported" not in out


#: The surfaces that render published job values. A numeric ``isinstance``
#: anywhere in one of these is a reader being written a second time.
_NARROWING_SURFACES: tuple[str, ...] = (
    "cli/_jobs_tui.py",
    "cli/_jobs_tui_status.py",
    "cli/_jobs_tui_log.py",
    "cli/_jobs_tui_palette.py",
    "cli/_service_jobs_presentation.py",
    "cli/_cli_format.py",
    "cli/_service_watcher.py",
    "server/_routes_jobs.py",
)

#: The ONLY functions on those surfaces allowed to narrow a number with their
#: own ``isinstance``, each named with the reason it cannot route through a
#: reader. The list is asserted exhaustive in both directions - an unnamed
#: offender fails, and a name that no longer needs exempting also fails - so
#: it can neither grow silently nor rot into a blanket suppression.
#:
#: Every entry is a terminal renderer taking an untrusted ``object``. They sit
#: BEHIND the readers as the last line of defence, so they are reached both by
#: values a reader already narrowed and by raw payload fields, and they cannot
#: delegate their guard to a caller that may not exist.
_NARROWING_EXEMPT: dict[str, str] = {
    # Renders an elapsed duration for any caller; also the backstop reached
    # directly with a raw payload field.
    "_format_seconds": "terminal renderer of an untrusted object",
    # Same, in the bounded fixed-width form a table column needs.
    "compact_duration": "terminal renderer of an untrusted object",
    # Same, converting from milliseconds before delegating.
    "_format_milliseconds": "terminal renderer of an untrusted object",
    # Same, for a mebibyte measure.
    "_format_mb": "terminal renderer of an untrusted object",
    # Renders a CONFIGURED delay, whose vocabulary differs from an elapsed
    # duration's; reads the watcher payload with no reader in front of it.
    "_format_delay_milliseconds": "terminal renderer of an untrusted object",
    # Same, at second granularity.
    "_format_delay_seconds": "terminal renderer of an untrusted object",
}

_NUMERIC_SHAPES = frozenset({"int", "float"})


def _numeric_isinstance_offenders() -> dict[str, list[str]]:
    """Map each function that narrows a number itself to where it does so."""
    package_root = Path(_jobs_module.__file__).parent
    offenders: dict[str, list[str]] = {}
    for relative in _NARROWING_SURFACES:
        path = package_root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if (
                    not isinstance(node, ast.Call)
                    or not isinstance(node.func, ast.Name)
                    or node.func.id != "isinstance"
                    or len(node.args) != 2
                ):
                    continue
                named = {
                    inner.id
                    for inner in ast.walk(node.args[1])
                    if isinstance(inner, ast.Name)
                }
                if named & _NUMERIC_SHAPES:
                    offenders.setdefault(function.name, []).append(
                        f"{relative}:{node.lineno}"
                    )
    return offenders


class TestNoSurfaceNarrowsANumberTwice:
    """No renderer may re-derive a reader the jobs module already owns.

    The structural duplicate guard elsewhere in the suite cannot see this
    family. It requires name equality, body-shape equality, unrelated modules,
    and a three-statement floor, and these twins failed every one of those:
    they were spelled ``_measurement`` against ``measurement``, one truncated
    where another refused, they lived in sibling modules, and the smallest was
    two statements. So the rule is asserted directly on the source instead.

    Proved able to fail: replacing ``measurement(gpu.get(...))`` in
    ``_gpu_cell`` with an inline ``isinstance(raw, int | float)`` test fails
    ``test_no_unexempted_function_narrows_a_number`` on ``assert unexempted ==
    {}``, reporting ``{'_gpu_cell': ['cli/_jobs_tui.py:1374']} == {}``;
    restoring the reader call returns every test here to green.
    """

    def test_no_unexempted_function_narrows_a_number(self) -> None:
        offenders = _numeric_isinstance_offenders()
        unexempted = {
            name: sites
            for name, sites in offenders.items()
            if name not in _NARROWING_EXEMPT
        }
        assert unexempted == {}

    def test_every_exemption_is_still_earning_its_place(self) -> None:
        # The other direction: a name that stopped narrowing must leave the
        # list, so it can never decay into a blanket suppression covering
        # code nobody checked.
        offenders = _numeric_isinstance_offenders()
        stale = sorted(set(_NARROWING_EXEMPT) - set(offenders))
        assert stale == []

    def test_the_readers_still_live_in_exactly_one_place(self) -> None:
        # The survivors are the jobs module's, and the surfaces import them
        # rather than restating them.
        assert measurement.__module__ == _jobs_module.__name__
        assert count.__module__ == _jobs_module.__name__
        assert mapping.__module__ == _jobs_module.__name__
        assert flag.__module__ == _jobs_module.__name__


class TestTheLookalikesThatMustNotBeMerged:
    """Three pairs that read as duplicates and are not.

    Each is pinned by exercising both sides on the input where they disagree,
    which is stronger than a comment: a later merge cannot pass these, and an
    entry that stopped diverging would fail rather than sit here unread.
    """

    def test_the_two_capability_readers_invert_on_an_absent_key(self) -> None:
        # The interface reads absent as PERMITTED so a restored record is not
        # inert and the service can refuse the press on its own authority;
        # the route reads absent as denied because it is publishing a claim.
        # Merging these silently greys out every key against an older daemon.
        restored: dict[str, object] = {"id": "restored-job"}
        assert _capability(restored, "pause") is True
        assert _job_capability(restored, "pause") is False

        # They agree wherever the service actually said something.
        denied: dict[str, object] = {"capabilities": {"pause": False}}
        assert _capability(denied, "pause") is False
        assert _job_capability(denied, "pause") is False

    def test_the_nested_section_reader_answers_none_not_empty(self) -> None:
        # Its ``None`` is consumed to suppress a captioned block entirely.
        # The canonical mapping reader cannot express that difference, which
        # is why this one is not routed through it.
        assert _nested_section({}, "resources", "current") is None
        empty_record: dict[str, object] = {}
        assert mapping(empty_record.get("resources")) == {}

        present: dict[str, object] = {"resources": {"current": {"rss_mb": 12.0}}}
        assert _nested_section(present, "resources", "current") == {"rss_mb": 12.0}

    def test_the_two_envelope_readers_answer_opposite_questions(self) -> None:
        # Same input shape, opposite outputs: one returns the payload worth
        # reading, the other returns why the payload cannot be believed.
        from ..cli._jobs_tui_status import _ok_payload

        refusal: dict[str, object] = {"ok": False, "error": "refused"}
        assert _ok_payload(refusal) == {}
        assert _fetch_error(refusal) is not None

        good: dict[str, object] = {"ok": True, "jobs": []}
        assert _ok_payload(good) == good
        assert _fetch_error(good) is None
