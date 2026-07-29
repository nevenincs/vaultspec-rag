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

import time

import pytest

from ..cli._cli_format import _format_mb, _format_seconds, compact_duration
from ..cli._service_jobs_presentation import render_jobs_result
from ..jobs import count, flag, measurement

pytestmark = [pytest.mark.unit]


#: One hostile input per row, with the exact answer each reader owes it.
#: A measurement accepts any real number and widens it to ``float``; a count
#: accepts only a whole number and refuses a fractional one outright rather
#: than truncating it; a signal answers only for a genuine ``bool``. Every
#: reader refuses ``bool`` for a number, which is the whole point of the
#: table - ``True`` and ``False`` are the first two rows for that reason.
_CONTRACT: tuple[tuple[str, object, float | None, int | None, bool | None], ...] = (
    ("bool true", True, None, None, True),
    ("bool false", False, None, None, False),
    ("negative int", -1, -1.0, -1, None),
    ("negative float", -1.0, -1.0, None, None),
    ("zero", 0, 0.0, 0, None),
    ("fractional float", 3.9, 3.9, None, None),
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
    """The three canonical readers, pinned cell by cell.

    Proved able to fail: dropping the ``isinstance(value, bool)`` clause from
    the measurement reader fails the ``bool true`` and ``bool false`` cells on
    ``_assert_exact``'s ``assert result is None``, reporting ``assert 1.0 is
    None``; restoring the clause returns all 34 cells to green.
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
        # later reader does not "fix" the count into truncating.
        assert measurement(3.9) == 3.9
        assert count(3.9) is None


class TestTheFormattersRefuseABool:
    """The last line of defence behind every routed numeric site.

    Each of these renders a bare ``int`` happily, so a ``bool`` reaching one
    used to print as a real duration or a real size instead of as absent.

    Proved able to fail: dropping the ``isinstance(raw, bool)`` clause from
    the seconds formatter fails both of its cells on the ``== "not reported"``
    assertion, rendering ``True`` as ``1 second`` and ``False`` as ``less than
    1 second``; restoring the clause returns all 7 cells to green.
    """

    @pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
    def test_format_seconds_refuses_a_bool(self, value: bool) -> None:
        assert _format_seconds(value) == "not reported"

    @pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
    def test_format_mb_refuses_a_bool(self, value: bool) -> None:
        assert _format_mb(value) == "not reported"

    @pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
    def test_compact_duration_refuses_a_bool(self, value: bool) -> None:
        assert compact_duration(value) == "—"

    def test_the_formatters_still_render_a_real_number(self) -> None:
        # The bool guard must not have cost the accepting path, and ``1``
        # is the value a leaked ``True`` would have arrived as.
        assert _format_seconds(1) == "1 second"
        assert _format_mb(1) != "not reported"
        assert compact_duration(1) == "1s"


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
