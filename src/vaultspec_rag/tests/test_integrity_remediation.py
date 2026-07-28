"""A shrunken verdict heals itself; every other verdict changes nothing.

These tests pin the remediation registry's decision table: only a
demonstrated shrink may request a repair, exactly one request per spacing
interval, ``consistent`` clears the memory, ``unverifiable`` acts on nothing,
and the operator switch turns the hand off while leaving the eyes on. The
status surface and the search envelope carry the repair id so an operator
sees "shrunken, repair in flight" rather than a mystery reindex.

No mocks, stubs, or patches: the registry is exercised through its real
decision function with real clocks passed in, the status surface through the
production ``index_job_status`` against a real (isolated) job manager, and
the envelope through the one canonical builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from .._index_integrity import (
    VERDICT_CONSISTENT,
    VERDICT_SHRUNKEN,
    VERDICT_UNVERIFIABLE,
)
from .._integrity_remediation import (
    REPAIR_REQUEST_MIN_INTERVAL_SECONDS,
    _record_verdict,
    reset_observations,
    shrunken_observations,
)
from .._source_types import PublicSourceType
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    reset_observations()
    yield
    reset_observations()


class TestRepairDecision:
    def test_only_shrunken_requests_a_repair(self, tmp_path: Path) -> None:
        """Neither of the honest-ignorance verdicts may touch anything.

        Catches ``unverifiable`` being escalated to an automatic repair -
        acting on an unreadable claim is the forbidden direction, so with the
        guard broken the first assertion fails on ``request_repair`` and the
        second on the observation it recorded.
        """
        request, job_id = _record_verdict(
            tmp_path, PublicSourceType.CODE, VERDICT_UNVERIFIABLE, now=100.0
        )
        assert request is False
        assert job_id is None
        assert shrunken_observations(tmp_path, now=100.5) == {}

    def test_a_shrink_requests_exactly_one_repair_per_interval(
        self, tmp_path: Path
    ) -> None:
        """Repeated shrunken searches must not stack repair requests.

        Catches the request spacing being dropped: with the interval check
        removed, the second observation requests again and the middle
        assertion fails.
        """
        first, _ = _record_verdict(
            tmp_path, PublicSourceType.CODE, VERDICT_SHRUNKEN, now=100.0
        )
        assert first is True
        again, _ = _record_verdict(
            tmp_path, PublicSourceType.CODE, VERDICT_SHRUNKEN, now=101.0
        )
        assert again is False
        past_interval, _ = _record_verdict(
            tmp_path,
            PublicSourceType.CODE,
            VERDICT_SHRUNKEN,
            now=101.0 + REPAIR_REQUEST_MIN_INTERVAL_SECONDS,
        )
        assert past_interval is True

    def test_consistent_clears_the_observation(self, tmp_path: Path) -> None:
        _record_verdict(tmp_path, PublicSourceType.CODE, VERDICT_SHRUNKEN, now=100.0)
        assert "code" in shrunken_observations(tmp_path, now=100.5)
        _record_verdict(tmp_path, PublicSourceType.CODE, VERDICT_CONSISTENT, now=101.0)
        # Catches the clear being dropped: a healed collection must stop
        # being reported the moment a search proves it whole.
        assert shrunken_observations(tmp_path, now=101.5) == {}

    def test_domains_are_tracked_independently(self, tmp_path: Path) -> None:
        _record_verdict(tmp_path, PublicSourceType.CODE, VERDICT_SHRUNKEN, now=100.0)
        _record_verdict(
            tmp_path, PublicSourceType.DOCUMENT, VERDICT_SHRUNKEN, now=100.0
        )
        _record_verdict(tmp_path, PublicSourceType.CODE, VERDICT_CONSISTENT, now=101.0)
        assert set(shrunken_observations(tmp_path, now=102.0)) == {"document"}


class TestOperatorSwitch:
    def test_disabling_auto_repair_keeps_detection_but_never_requests(
        self, tmp_path: Path
    ) -> None:
        """The switch turns the hand off while the eyes stay on.

        Catches the knob being ignored: with the enabled-check removed, the
        request assertion fails first; with detection accidentally disabled
        alongside it, the observation assertion fails instead.
        """
        with managed_env(VAULTSPEC_RAG_INTEGRITY_AUTO_REPAIR="0"):
            request, _ = _record_verdict(
                tmp_path, PublicSourceType.CODE, VERDICT_SHRUNKEN, now=100.0
            )
            assert request is False
            observed = shrunken_observations(tmp_path, now=100.5)
            assert observed["code"]["auto_repair"] == "disabled"
            assert observed["code"]["repair_job_id"] is None

    def test_the_knob_defaults_on(self) -> None:
        from ..config._settings import get_config

        assert bool(get_config().integrity_auto_repair) is True
        with managed_env(VAULTSPEC_RAG_INTEGRITY_AUTO_REPAIR="0"):
            assert bool(get_config().integrity_auto_repair) is False


class TestStatusSurface:
    def test_the_domain_status_names_the_shrink_and_its_repair(
        self,
        tmp_path: Path,
    ) -> None:
        """``index_job_status`` degrades a shrunken domain with attribution.

        Catches the merge being dropped from the status route: with it gone,
        a shrunken collection whose latest job is green reports nothing and
        the reason lookup below fails.
        """
        import time

        from ..jobs import index_job_status, reset

        with managed_env(VAULTSPEC_RAG_STATUS_DIR=str(tmp_path / "status")):
            reset()
            try:
                root = tmp_path / "project"
                root.mkdir()
                # Stamped with the registry's own clock: the status route
                # reads with the live clock, so a fabricated stamp would
                # read as long expired.
                _record_verdict(
                    root,
                    PublicSourceType.DOCUMENT,
                    VERDICT_SHRUNKEN,
                    now=time.monotonic(),
                )
                status = index_job_status(root)
                raw_degraded = status["degraded_reasons"]
                assert isinstance(raw_degraded, list)
                degraded = cast("list[dict[str, object]]", raw_degraded)
                shrunken = [
                    entry for entry in degraded if entry["reason"] == "shrunken"
                ]
                assert len(shrunken) == 1
                assert shrunken[0]["source"] == "document"
                assert shrunken[0]["auto_repair"] == "enabled"
                assert shrunken[0]["job_id"] is None
            finally:
                reset()


class TestEnvelopeCarriesTheRepair:
    def test_the_repair_id_rides_the_integrity_block_additively(self) -> None:
        from pathlib import Path

        from .._index_integrity import IndexIntegrity
        from .._search_state import BreadthFindings, search_index_state

        integrity = IndexIntegrity(
            verdict=VERDICT_SHRUNKEN,
            source="code",
            claimed_count=5,
            live_count=3,
            generation_id="g",
            reason=None,
        )
        state = search_index_state(
            indexed_count=3,
            requested_root=Path("root"),
            search_type=PublicSourceType.CODE,
            findings=BreadthFindings(
                integrity=integrity, integrity_repair_job_id="job-1"
            ),
        )
        raw_block = state["index_integrity"]
        assert isinstance(raw_block, dict)
        block = cast("dict[str, object]", raw_block)
        assert block["repair_job_id"] == "job-1"

        without = search_index_state(
            indexed_count=3,
            requested_root=Path("root"),
            search_type=PublicSourceType.CODE,
            findings=BreadthFindings(integrity=integrity),
        )
        block_without = without["index_integrity"]
        assert isinstance(block_without, dict)
        # Additive means additive: a surface that queued no repair emits the
        # block exactly as before, absent key included.
        assert "repair_job_id" not in block_without
