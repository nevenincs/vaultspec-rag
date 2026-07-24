"""Unit tests for service-lifecycle helper logic.

These tests exercise pure-logic helpers that do not require a live daemon,
a real port, or GPU models.  They redirect the status directory via
VAULTSPEC_RAG_STATUS_DIR (the project's designated isolation mechanism —
see the ``feedback_service_tests_isolate_STATUS_DIR`` memory note).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ..cli._service_status import _update_service_token

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# _update_service_token — atomic token persistence into service.json
# ---------------------------------------------------------------------------


class TestUpdateServiceToken:
    """_update_service_token persists the token from /health into service.json."""

    def _make_status_file(self, status_dir: Path, data: dict[str, object]) -> Path:
        sf = status_dir / "service.json"
        sf.write_text(json.dumps(data), encoding="utf-8")
        return sf

    def test_writes_token_into_existing_file(self, isolated_status_dir: Path) -> None:
        """Token is merged into service.json, preserving all existing fields."""
        self._make_status_file(isolated_status_dir, {"pid": 12345, "port": 8766})

        _update_service_token("tok-abc123")

        sf = isolated_status_dir / "service.json"
        result = json.loads(sf.read_text(encoding="utf-8"))
        assert result["service_token"] == "tok-abc123"
        assert result["pid"] == 12345
        assert result["port"] == 8766

    def test_noop_when_file_absent(self, isolated_status_dir: Path) -> None:
        """Helper is silent (no exception, no file created) when absent."""
        sf = isolated_status_dir / "service.json"
        assert not sf.exists()

        _update_service_token("tok-xyz")

        assert not sf.exists()

    def test_noop_when_token_already_matches(self, isolated_status_dir: Path) -> None:
        """No disk write occurs when the stored token equals the incoming token."""
        sf = self._make_status_file(
            isolated_status_dir,
            {"pid": 1, "port": 8766, "service_token": "tok-same"},
        )
        mtime_before = sf.stat().st_mtime_ns

        _update_service_token("tok-same")

        assert sf.stat().st_mtime_ns == mtime_before

    def test_overwrites_stale_token(self, isolated_status_dir: Path) -> None:
        """An outdated token in service.json is replaced with the fresh one."""
        self._make_status_file(
            isolated_status_dir,
            {"pid": 1, "port": 8766, "service_token": "old-token"},
        )

        _update_service_token("new-token")

        sf = isolated_status_dir / "service.json"
        result = json.loads(sf.read_text(encoding="utf-8"))
        assert result["service_token"] == "new-token"

    def test_write_is_atomic_tmp_file_cleaned_up(
        self, isolated_status_dir: Path
    ) -> None:
        """No .tmp artefact left after a successful write."""
        self._make_status_file(isolated_status_dir, {"pid": 1, "port": 8766})

        _update_service_token("tok-clean")

        tmp = isolated_status_dir / "service.tmp"
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# _startup_phase_label — the cold-start stage the CLI start spinner renders
# ---------------------------------------------------------------------------


class TestStartupPhaseLabel:
    """The wait spinner names the daemon's current cold-start stage."""

    def _write_status(self, status_dir: Path, data: dict[str, object]) -> None:
        (status_dir / "service.json").write_text(json.dumps(data), encoding="utf-8")

    def test_serving_health_status_wins(self, isolated_status_dir: Path) -> None:
        from ..cli._service_start import _startup_phase_label

        self._write_status(
            isolated_status_dir,
            {"pid": 1, "port": 8766, "phase": "warming", "phase_detail": "x"},
        )
        assert _startup_phase_label({"status": "ready"}) == "serving, health: ready"

    def test_renders_granular_phase_detail_while_warming(
        self, isolated_status_dir: Path
    ) -> None:
        from ..cli._service_start import _startup_phase_label

        self._write_status(
            isolated_status_dir,
            {
                "pid": 1,
                "port": 8766,
                "phase": "warming",
                "phase_detail": "provisioning the qdrant server",
            },
        )
        assert _startup_phase_label(None) == "provisioning the qdrant server"

    def test_renders_determinate_count_when_total_present(
        self, isolated_status_dir: Path
    ) -> None:
        from ..cli._service_start import _startup_phase_label

        self._write_status(
            isolated_status_dir,
            {
                "pid": 1,
                "port": 8766,
                "phase": "warming",
                "phase_detail": "loading models",
                "phase_done": 2,
                "phase_total": 3,
            },
        )
        assert _startup_phase_label(None) == "loading models (2/3)"

    def test_older_daemon_without_a_count_falls_back_to_plain_label(
        self, isolated_status_dir: Path
    ) -> None:
        # Guard for the descriptor-less fallback: a daemon that stamps a label
        # but no count (an older build, or a countless stage) must render the
        # plain label with NO "(x/y)" suffix. Both directions: adding the count
        # keys makes the suffix appear (asserted above); their absence must not.
        # Break-and-watch: temporarily writing phase_total here would flip the
        # assertion to the counted form, proving the suffix is bound to the
        # count fields and not always emitted.
        from ..cli._service_start import _startup_phase_label

        self._write_status(
            isolated_status_dir,
            {
                "pid": 1,
                "port": 8766,
                "phase": "warming",
                "phase_detail": "loading models",
            },
        )
        assert _startup_phase_label(None) == "loading models"

    def test_falls_back_to_generic_warming_without_detail(
        self, isolated_status_dir: Path
    ) -> None:
        from ..cli._service_start import _startup_phase_label

        self._write_status(
            isolated_status_dir, {"pid": 1, "port": 8766, "phase": "warming"}
        )
        assert _startup_phase_label(None) == "warming (loading models)"

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_waiting_when_no_status_published_yet(self) -> None:
        from ..cli._service_start import _startup_phase_label

        assert _startup_phase_label(None) == "waiting for the daemon to come up"


def _serving_health(**overrides: object) -> dict[str, object]:
    """A health payload from a daemon that has finished coming up."""
    payload: dict[str, object] = {
        "status": "ready",
        "models_loaded": True,
        "qdrant": {"mode": "server", "alive": True},
        "degraded_reasons": [],
    }
    payload.update(overrides)
    return payload


class TestDaemonIsServing:
    """The start wait ends when the daemon can serve, not when its history is clean."""

    def test_job_history_degradation_still_counts_as_serving(self) -> None:
        """A daemon degraded only by a failed job is serving and must end the wait.

        This is the regression guard for a start that burned its full 300s
        deadline against a daemon that had been answering requests the whole
        time. The payload below is the shape a real service reports once any
        indexing job has ever failed: every infrastructure signal is healthy and
        the only complaint is job history. Asserting on ``models_loaded`` and the
        backend rather than the status word is the point - gating on
        ``status == "ready"`` is exactly the defect.
        """
        from ..cli._service_start import _daemon_is_serving

        health = _serving_health(
            status="degraded",
            degraded_reasons=["the latest indexing job failed: other"],
        )
        assert _daemon_is_serving(health) is True

    def test_models_not_loaded_is_not_serving(self) -> None:
        from ..cli._service_start import _daemon_is_serving

        assert _daemon_is_serving(_serving_health(models_loaded=False)) is False

    def test_dead_vector_backend_is_not_serving(self) -> None:
        from ..cli._service_start import _daemon_is_serving

        health = _serving_health(qdrant={"mode": "server", "alive": False})
        assert _daemon_is_serving(health) is False

    def test_local_backend_needs_no_live_server(self) -> None:
        """Local mode has no server to be alive, so models alone decide."""
        from ..cli._service_start import _daemon_is_serving

        health = _serving_health(qdrant={"mode": "local", "alive": False})
        assert _daemon_is_serving(health) is True


class TestServingWarningLines:
    """A start that succeeds against a degraded daemon still reports why."""

    def test_reasons_are_rendered(self) -> None:
        from ..cli._service_start import _serving_warning_lines

        lines = _serving_warning_lines(
            {"degraded_reasons": ["the latest indexing job failed: other"]}
        )
        assert lines == (
            "Serving, with warnings:",
            "  - the latest indexing job failed: other",
        )

    def test_unrecognised_reason_is_never_swallowed(self) -> None:
        """An unknown reason is shown verbatim rather than filtered out.

        The reason strings are daemon-side display text and get reworded; a
        renderer that only knew a fixed vocabulary would silently drop the one
        message explaining a degradation.
        """
        from ..cli._service_start import _serving_warning_lines

        lines = _serving_warning_lines({"degraded_reasons": ["something brand new"]})
        assert "  - something brand new" in lines

    def test_no_reasons_render_nothing(self) -> None:
        from ..cli._service_start import _serving_warning_lines

        assert _serving_warning_lines({"degraded_reasons": []}) == ()
        assert _serving_warning_lines({}) == ()
