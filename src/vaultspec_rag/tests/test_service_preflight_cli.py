"""Real transport coverage for the non-authorizing service preflight CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..serviceclient._discovery import HEARTBEAT_STALENESS_SECONDS
from ..serviceclient._transport import _try_http_admin
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._production_service import production_service, publish_discovery

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_preflight_observes_safe_service_but_never_authorizes_gpu(
    isolated_status_dir: Path,
) -> None:
    """A safe remote snapshot succeeds only as an observation, never a grant."""
    with production_service(isolated_status_dir) as service:
        pause = _try_http_admin("pause_service", {}, service.port)
        assert pause is not None, "the real pause route did not answer"
        assert pause["status"] == "quiesced", pause
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) == 1, result.output
    assert '"ok": true' in result.output
    assert '"source": "service"' in result.output
    assert f'"port": {service.port}' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output
    assert (
        '"authorization": "A borrower lease is required before GPU work may begin."'
        in result.output
    )
    assert '"state": "quiesced"' in result.output
    assert '"safe_to_borrow_gpu": true' in result.output
    assert '"capacity": {' in result.output


def test_preflight_refuses_a_discovered_service_that_is_not_safe(
    isolated_status_dir: Path,
) -> None:
    """Running is observable, but only acknowledged quiescence is safe."""
    with production_service(isolated_status_dir):
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"ok": false' in result.output
    assert '"error": "service_not_safe_to_borrow_gpu"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_stale_discovery_without_a_local_fallback(
    isolated_status_dir: Path,
) -> None:
    """A stale discovery record fails before any remote observation is trusted."""
    with production_service(isolated_status_dir) as service:
        publish_discovery(
            isolated_status_dir,
            port=service.port,
            heartbeat=(
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALENESS_SECONDS + 5)
            ).isoformat(timespec="seconds"),
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_stale"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_when_no_service_is_discovered(
    isolated_status_dir: Path,
) -> None:
    """A missing service is never replaced with a local device probe."""
    del isolated_status_dir
    result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_unavailable"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


class TestTorchFreedom:
    """The CLI observation surface must remain torch-free on import."""

    def test_importing_the_verb_loads_no_torch(self) -> None:
        assert_fresh_import_excludes(
            import_probe_source("vaultspec_rag.cli._service_preflight")
        )
