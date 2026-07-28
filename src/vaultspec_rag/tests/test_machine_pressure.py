"""The machine pressure tier: classification, hysteresis, and its surfaces.

Surfacing only: the tier is computed and shown, and nothing defers,
shrinks, yields, or refuses work because of it. No mocks, stubs, or
patches: every case feeds recorded signal values through the evaluator's
real input dataclass with an injected clock, and the envelope tests run
the production route composition.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from ..pressure import (
    PRESSURE_TIERS,
    MachinePressureSignals,
    PressureEvaluator,
    reset_pressure_evaluator,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

pytestmark = [pytest.mark.unit]

# The evaluator folds samples closer than its acceptance interval, so every
# driven sequence steps the injected clock by a comfortably larger stride.
_STEP = 5.0
_T0 = 100_000.0
# Escalation is three consecutive over-threshold samples.
_ATTACK = 3

_PRESSURE_KEYS = {"tier", "entered_at", "evidence"}
_EVIDENCE_KEYS = {"forward", "gpu", "backend", "encode_waiters", "store_failures"}
_FORWARD_KEYS = {"in_flight", "age_seconds", "slice_ordinal", "items", "thread_alive"}
_GPU_KEYS = {"available", "utilization_percent", "memory_used_mb", "memory_total_mb"}
_BACKEND_KEYS = {"probed", "alive", "latency_seconds", "detail"}


def _as_map(value: object) -> dict[str, object]:
    """Assert one payload member is a mapping and type it as one."""
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _drive(
    evaluator: PressureEvaluator,
    signals: MachinePressureSignals,
    *,
    count: int,
    start: float = _T0,
) -> dict[str, object]:
    """Feed one signal shape as *count* accepted samples; return the verdict."""
    block: dict[str, object] = {}
    for index in range(count):
        block = evaluator.observe(signals, now=start + index * _STEP)
    return block


#: The incident's card: pinned on utilization and on device memory at once.
#: Held as a built signal rather than a kwargs dict so every field keeps its
#: declared type - unpacking a ``dict[str, float]`` erases all of them.
_SATURATED_GPU = MachinePressureSignals(
    gpu_utilization_percent=100.0,
    gpu_memory_used_mb=15872.0,
    gpu_memory_total_mb=16384.0,
)


class TestClassification:
    """One signal shape, sustained past the attack window, lands one tier."""

    @pytest.mark.parametrize(
        ("signals", "expected"),
        [
            pytest.param(MachinePressureSignals(), "nominal", id="quiet_host"),
            pytest.param(
                MachinePressureSignals(
                    forward_in_flight=True,
                    forward_age_seconds=59.0,
                    forward_thread_alive=True,
                ),
                "nominal",
                id="forward_under_threshold",
            ),
            pytest.param(
                MachinePressureSignals(
                    forward_in_flight=True,
                    forward_age_seconds=60.0,
                    forward_thread_alive=True,
                ),
                "elevated",
                id="forward_at_threshold",
            ),
            pytest.param(
                MachinePressureSignals(
                    forward_in_flight=False,
                    forward_age_seconds=4000.0,
                    forward_thread_alive=True,
                ),
                "nominal",
                id="an_old_exit_is_not_a_stretch",
            ),
            pytest.param(
                _SATURATED_GPU,
                "elevated",
                id="gpu_saturated_on_both_axes",
            ),
            pytest.param(
                MachinePressureSignals(
                    gpu_utilization_percent=100.0,
                    gpu_memory_used_mb=4000.0,
                    gpu_memory_total_mb=16384.0,
                ),
                "nominal",
                id="utilization_alone_is_a_busy_card",
            ),
            pytest.param(
                MachinePressureSignals(
                    gpu_utilization_percent=20.0,
                    gpu_memory_used_mb=16000.0,
                    gpu_memory_total_mb=16384.0,
                ),
                "nominal",
                id="memory_alone_is_a_resident_model",
            ),
            pytest.param(
                MachinePressureSignals(
                    backend_probed=True,
                    backend_alive=True,
                    backend_latency_seconds=1.2,
                    backend_probe_bound_seconds=2.0,
                ),
                "elevated",
                id="backend_slow",
            ),
            pytest.param(
                MachinePressureSignals(
                    backend_probed=True,
                    backend_alive=True,
                    backend_latency_seconds=0.4,
                    backend_probe_bound_seconds=2.0,
                ),
                "nominal",
                id="backend_quick",
            ),
            pytest.param(
                MachinePressureSignals(backend_probed=True, backend_alive=False),
                "critical",
                id="backend_failed",
            ),
            pytest.param(
                MachinePressureSignals(backend_probed=True, backend_alive=None),
                "critical",
                id="backend_unanswered",
            ),
            pytest.param(
                MachinePressureSignals(backend_probed=False, backend_alive=None),
                "nominal",
                id="an_unprobed_backend_is_absence_not_a_verdict",
            ),
            pytest.param(
                MachinePressureSignals(
                    forward_in_flight=True,
                    forward_age_seconds=5.0,
                    forward_thread_alive=False,
                ),
                "critical",
                id="encode_thread_dead_under_an_open_window",
            ),
            pytest.param(
                MachinePressureSignals(
                    forward_in_flight=False,
                    forward_age_seconds=5.0,
                    forward_thread_alive=False,
                ),
                "nominal",
                id="a_closed_window_needs_no_thread",
            ),
            pytest.param(
                MachinePressureSignals(encode_waiters=1),
                "elevated",
                id="encode_waiters_queueing",
            ),
            pytest.param(
                MachinePressureSignals(encode_waiters=0),
                "nominal",
                id="an_empty_admission_queue",
            ),
        ],
    )
    def test_a_sustained_signal_lands_its_tier(
        self,
        signals: MachinePressureSignals,
        expected: str,
    ) -> None:
        block = _drive(PressureEvaluator(), signals, count=_ATTACK)
        assert block["tier"] == expected


class TestHysteresis:
    """Fast attack over consecutive samples, slow stepwise release."""

    def test_escalation_waits_for_the_full_attack_window(self) -> None:
        evaluator = PressureEvaluator()
        signals = _SATURATED_GPU
        assert _drive(evaluator, signals, count=_ATTACK - 1)["tier"] == "nominal"
        assert (
            evaluator.observe(signals, now=_T0 + (_ATTACK - 1) * _STEP)["tier"]
            == "elevated"
        )

    def test_polls_inside_the_sample_interval_are_one_sample(self) -> None:
        """Three concurrent pollers must not triple the attack speed."""
        evaluator = PressureEvaluator()
        block: dict[str, object] = {}
        for offset in (0.0, 1.0, 2.0, 3.0, 4.0, 4.9):
            block = evaluator.observe(_SATURATED_GPU, now=_T0 + offset)
        assert block["tier"] == "nominal", (
            "sub-interval polls must fold into one sample, not stack the streak"
        )

    def test_an_interrupted_streak_does_not_escalate(self) -> None:
        evaluator = PressureEvaluator()
        pressured = _SATURATED_GPU
        evaluator.observe(pressured, now=_T0)
        evaluator.observe(pressured, now=_T0 + _STEP)
        evaluator.observe(MachinePressureSignals(), now=_T0 + 2 * _STEP)
        block = evaluator.observe(pressured, now=_T0 + 3 * _STEP)
        assert block["tier"] == "nominal", (
            "a calm sample must restart the escalation streak"
        )

    def test_clearing_needs_a_continuous_quiet_minute(self) -> None:
        evaluator = PressureEvaluator()
        block = _drive(evaluator, _SATURATED_GPU, count=3)
        assert block["tier"] == "elevated"
        quiet = MachinePressureSignals()
        clear_start = _T0 + 3 * _STEP
        moment = clear_start
        while moment - clear_start < 60.0:
            block = evaluator.observe(quiet, now=moment)
            assert block["tier"] == "elevated", (
                "the tier must hold until the quiet window completes"
            )
            moment += _STEP
        assert evaluator.observe(quiet, now=moment)["tier"] == "nominal"

    def test_a_relapse_restarts_the_clear_clock(self) -> None:
        evaluator = PressureEvaluator()
        pressured = _SATURATED_GPU
        _drive(evaluator, pressured, count=3)
        quiet = MachinePressureSignals()
        moment = _T0 + 3 * _STEP
        for _ in range(10):  # 50 s of quiet - short of the window
            evaluator.observe(quiet, now=moment)
            moment += _STEP
        evaluator.observe(pressured, now=moment)  # relapse
        moment += _STEP
        block: dict[str, object] = {}
        for _ in range(11):  # 55 s of quiet after the relapse
            block = evaluator.observe(quiet, now=moment)
            moment += _STEP
        assert block["tier"] == "elevated", (
            "a pressured sample mid-window must restart the clear clock"
        )

    def test_critical_releases_one_rung_per_window(self) -> None:
        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        block = _drive(evaluator, failed, count=3)
        assert block["tier"] == "critical"
        quiet = MachinePressureSignals()
        seen: list[str] = []
        moment = _T0 + 3 * _STEP
        for _ in range(30):  # 150 s of quiet: enough for two windows
            tier = evaluator.observe(quiet, now=moment)["tier"]
            seen.append(cast("str", tier))
            moment += _STEP
        assert "elevated" in seen, (
            "critical must step down through elevated, never straight to nominal"
        )
        assert seen[-1] == "nominal"
        assert seen.index("elevated") < seen.index("nominal")

    def test_a_mixed_streak_escalates_to_its_floor(self) -> None:
        """One critical sample among elevated ones cannot buy critical."""
        evaluator = PressureEvaluator()
        elevated = _SATURATED_GPU
        critical = MachinePressureSignals(backend_probed=True, backend_alive=False)
        evaluator.observe(critical, now=_T0)
        evaluator.observe(elevated, now=_T0 + _STEP)
        block = evaluator.observe(critical, now=_T0 + 2 * _STEP)
        assert block["tier"] == "elevated", (
            "the streak escalates to the worst tier every sample supported"
        )

    def test_a_sustained_critical_streak_reaches_critical_directly(self) -> None:
        block = _drive(
            PressureEvaluator(),
            MachinePressureSignals(backend_probed=True, backend_alive=None),
            count=_ATTACK,
        )
        assert block["tier"] == "critical"

    def test_entered_at_moves_only_on_transition(self) -> None:
        evaluator = PressureEvaluator()
        pressured = _SATURATED_GPU
        first = evaluator.observe(MachinePressureSignals(), now=_T0)
        assert first["entered_at"] == _T0
        _drive(evaluator, pressured, count=3, start=_T0 + _STEP)
        # Kept on the sample cadence rather than jumped forward: a gap wide
        # enough to skip samples is a stale verdict, which is a different
        # rule being exercised - here the tier must simply hold.
        held = _drive(evaluator, pressured, count=7, start=_T0 + 4 * _STEP)
        assert held["tier"] == "elevated"
        assert held["entered_at"] == _T0 + 3 * _STEP, (
            "entered_at is the escalation moment and must hold while the tier holds"
        )


class TestStaleVerdictsFailOpen:
    """An unmeasured machine is not a machine under a verdict."""

    def test_a_verdict_nothing_refreshed_lapses_to_nominal(self) -> None:
        """Proven able to fail: making ``_stale`` always return ``False`` -
        so a verdict is carried forward across any gap - holds ``critical``
        and fails the assertion below by name; restored, it passes."""
        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        assert _drive(evaluator, failed, count=_ATTACK)["tier"] == "critical"
        resumed = _T0 + _ATTACK * _STEP + 3600.0
        assert evaluator.observe(MachinePressureSignals(), now=resumed)["tier"] == (
            "nominal"
        ), "an hour of silence must release the verdict, not preserve it"

    def test_a_backwards_clock_releases_the_verdict(self) -> None:
        """An unknowable gap fails open the same way a long one does."""
        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        assert _drive(evaluator, failed, count=_ATTACK)["tier"] == "critical"
        assert evaluator.observe(failed, now=_T0 - 500.0)["tier"] == "nominal"

    def test_a_polled_surface_never_trips_the_staleness_window(self) -> None:
        """The window must not fire under a surface that is still polling."""
        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        moment = _T0
        seen: list[object] = []
        for _ in range(20):
            seen.append(evaluator.observe(failed, now=moment)["tier"])
            moment += _STEP
        assert seen[-1] == "critical", "a verdict fed on the sample cadence must stand"


class TestStoreFailuresReachCritical:
    """A full disk answers a read probe; the dead jobs are the evidence."""

    def test_a_disk_failure_is_critical_on_one_sighting(self) -> None:
        block = _drive(
            PressureEvaluator(),
            MachinePressureSignals(
                backend_probed=True,
                backend_alive=True,
                backend_latency_seconds=0.01,
                backend_probe_bound_seconds=2.0,
                store_failures=("disk_full",),
            ),
            count=_ATTACK,
        )
        assert block["tier"] == "critical", (
            "a live probe must not outrank a job the store already killed"
        )

    @pytest.mark.parametrize("kind", ["timeout", "unavailable"])
    def test_one_transient_failure_is_not_critical(self, kind: str) -> None:
        """Proven able to fail: treating these as critical on one sighting -
        dropping the repetition minimum - lands ``critical`` and fails the
        assertion below by name; restored, it passes."""
        block = _drive(
            PressureEvaluator(),
            MachinePressureSignals(store_failures=(kind,)),
            count=_ATTACK,
        )
        assert block["tier"] == "nominal", (
            "a single transient failure must not condemn a working store"
        )

    @pytest.mark.parametrize("kind", ["timeout", "unavailable"])
    def test_a_repeated_transient_failure_is_critical(self, kind: str) -> None:
        block = _drive(
            PressureEvaluator(),
            MachinePressureSignals(store_failures=(kind, kind)),
            count=_ATTACK,
        )
        assert block["tier"] == "critical"

    def test_an_unrelated_failure_kind_is_not_store_evidence(self) -> None:
        """A job killed by its own corpus limit says nothing about the store."""
        block = _drive(
            PressureEvaluator(),
            MachinePressureSignals(
                store_failures=("corpus_limit_exceeded", "corpus_limit_exceeded")
            ),
            count=_ATTACK,
        )
        assert block["tier"] == "nominal"


class TestGpuNeverCritical:
    """The incident invariant: a starved card is never a critical machine."""

    def test_gpu_side_signals_alone_never_reach_critical(self) -> None:
        """Saturation plus a stretched forward caps at ``elevated``.

        Proven able to fail: adding the saturated-GPU or stretched-forward
        findings to the critical classification - the escalation this
        guards against - fails the ``never critical`` assertion below by
        name; restored, it passes.
        """
        evaluator = PressureEvaluator()
        starved = replace(
            _SATURATED_GPU,
            forward_in_flight=True,
            forward_age_seconds=3600.0,  # an hour-long forward, thread alive
            forward_thread_alive=True,
            encode_waiters=4,
        )
        seen: set[object] = set()
        block: dict[str, object] = {}
        for index in range(40):  # 200 s: far past every attack window
            block = evaluator.observe(starved, now=_T0 + index * _STEP)
            seen.add(block["tier"])
        assert "critical" not in seen, (
            "GPU-side signals alone must never reach critical"
        )
        assert block["tier"] == "elevated", (
            "a starved card must still be surfaced, one tier below critical"
        )


@pytest.fixture
def fresh_evaluator() -> Iterator[None]:
    reset_pressure_evaluator()
    yield
    reset_pressure_evaluator()


@pytest.fixture(autouse=True)
def own_status_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    from ..config._settings import reset_config
    from ..jobs import reset

    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    reset_config()
    reset()
    yield
    reset()
    reset_config()


def _forward_block(
    *,
    entered_at: float,
    exited_at: float | None,
    thread_ident: int | None = None,
) -> dict[str, object]:
    return {
        "entered_at": entered_at,
        "exited_at": exited_at,
        "slice_ordinal": 3,
        "items": 64,
        "thread_ident": (
            thread_ident if thread_ident is not None else threading.get_ident()
        ),
        "thread_name": "encode",
    }


class TestMachinePressureBlock:
    """The service-side block: evidence shapes, probe discipline, worst pick."""

    @pytest.mark.usefixtures("fresh_evaluator")
    def test_an_idle_machine_reports_nominal_without_probing(self) -> None:
        from ..jobs import machine_pressure

        block = machine_pressure(now=_T0, forwards=[], project_root=None, source="code")
        assert set(block) == _PRESSURE_KEYS
        assert block["tier"] == "nominal"
        assert block["entered_at"] == _T0
        evidence = _as_map(block["evidence"])
        assert set(evidence) == _EVIDENCE_KEYS
        assert set(_as_map(evidence["forward"])) == _FORWARD_KEYS
        assert set(_as_map(evidence["gpu"])) == _GPU_KEYS
        backend = _as_map(evidence["backend"])
        assert set(backend) == _BACKEND_KEYS
        assert backend["probed"] is False, (
            "an idle machine must not pay a store probe for its tier"
        )
        assert backend["alive"] is None

    @pytest.mark.usefixtures("fresh_evaluator")
    def test_the_worst_forward_wins_the_evidence_slot(self) -> None:
        from ..jobs import machine_pressure

        finished = _forward_block(entered_at=_T0 - 500.0, exited_at=_T0 - 490.0)
        stretched = _forward_block(entered_at=_T0 - 120.0, exited_at=None)
        block = machine_pressure(
            now=_T0,
            forwards=[finished, stretched],
            project_root=None,
            source="code",
        )
        forward = _as_map(_as_map(block["evidence"])["forward"])
        assert forward["in_flight"] is True, (
            "an open forward window outranks a finished one"
        )
        age = forward["age_seconds"]
        assert isinstance(age, float)
        assert age == pytest.approx(120.0)


class TestJobsRoutePressureExposure:
    """GET /jobs carries the pressure block beside the GPU reading."""

    @pytest.mark.usefixtures("fresh_evaluator")
    def test_the_listing_envelope_carries_the_pressure_block(self) -> None:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from .. import server as server_package
        from ..server._routes import jobs_route

        token = "pressure-exposure-test-token"
        previous_token = server_package._SERVICE_TOKEN
        server_package._SERVICE_TOKEN = token
        try:
            app = Starlette(routes=[Route("/jobs", jobs_route)])
            client: httpx.Client = cast("httpx.Client", TestClient(app))
            response: httpx.Response = client.get(
                "/jobs", headers={"Authorization": f"Bearer {token}"}
            )
            payload = _as_map(cast("object", response.json()))
        finally:
            server_package._SERVICE_TOKEN = previous_token
        pressure = _as_map(payload["pressure"])
        assert set(pressure) == _PRESSURE_KEYS, (
            "the polled listing is where every adapter reads the tier from"
        )
        assert pressure["tier"] in PRESSURE_TIERS
        assert set(_as_map(pressure["evidence"])) == _EVIDENCE_KEYS


class TestPlainFeedRendering:
    """The plain feed line: absent says nothing, nominal says nothing."""

    def test_an_absent_block_renders_nothing(self) -> None:
        from ..cli._service_jobs_presentation import _machine_pressure_line

        assert _machine_pressure_line({"jobs": []}) == ""

    def test_a_null_block_renders_nothing(self) -> None:
        from ..cli._service_jobs_presentation import _machine_pressure_line

        assert _machine_pressure_line({"pressure": None}) == ""

    def test_nominal_is_the_silent_steady_state(self) -> None:
        """Proven able to fail: rendering the nominal branch - the noise
        this guards against - returns a line here and fails this assertion
        by name; restored, it passes."""
        from ..cli._service_jobs_presentation import _machine_pressure_line

        line = _machine_pressure_line({"pressure": {"tier": "nominal"}})
        assert line == "", "the healthy steady state must not add a line"

    # ``catastrophic`` is no tier this build knows: a newer daemon naming a
    # worse state must be relayed, not swallowed by a known-tier whitelist.
    @pytest.mark.parametrize("tier", ["elevated", "critical", "catastrophic"])
    def test_a_pressured_tier_is_named(self, tier: str) -> None:
        from ..cli._service_jobs_presentation import _machine_pressure_line

        line = _machine_pressure_line({"pressure": {"tier": tier}})
        assert line == f"Machine pressure: {tier}"


class TestSampleClockTracksTheProbeCaches:
    """The evaluator's clock is the probe-cache period, not a copy of it."""

    def test_the_sample_interval_matches_the_probe_cache_period(self) -> None:
        """A faster clock would only resample a cache and let the number of
        pollers, rather than elapsed time, decide how fast the tier moves.

        The two constants live in different modules because the evaluator
        must not import the probing one, so this equality is the binding
        that stops them drifting apart under a later tuning pass.
        """
        from .. import pressure as pressure_module
        from ..jobs import _BACKEND_PROBE_CACHE_SECONDS, _GPU_SNAPSHOT_CACHE_SECONDS

        assert pressure_module._SAMPLE_INTERVAL_SECONDS == _BACKEND_PROBE_CACHE_SECONDS
        assert pressure_module._SAMPLE_INTERVAL_SECONDS == _GPU_SNAPSHOT_CACHE_SECONDS


class TestTransitionsAreParseableEvents:
    """Tier history is the deliverable, so it has to be machine-readable."""

    def test_a_transition_emits_a_structured_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from ..pressure import logger as pressure_logger

        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        with caplog.at_level(logging.INFO, logger=pressure_logger.name):
            _drive(evaluator, failed, count=_ATTACK)
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "service.pressure event=tier_changed" in message
            and "previous=nominal" in message
            and "tier=critical" in message
            and "backend_failed" in message
            for message in messages
        ), f"a transition must be parseable, got {messages}"

    def test_a_lapsed_verdict_names_staleness_as_its_cause(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A verdict released for want of evidence must not read as recovery."""
        from ..pressure import logger as pressure_logger

        evaluator = PressureEvaluator()
        failed = MachinePressureSignals(backend_probed=True, backend_alive=False)
        _drive(evaluator, failed, count=_ATTACK)
        with caplog.at_level(logging.INFO, logger=pressure_logger.name):
            evaluator.observe(
                MachinePressureSignals(), now=_T0 + _ATTACK * _STEP + 3600.0
            )
        assert any(
            "evidence_stale" in record.getMessage() for record in caplog.records
        ), "a stale release is a different fact from a measured recovery"
