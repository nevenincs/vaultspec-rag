"""What the readiness report tells an environment to do about a missing dependency.

The report is read by ``server doctor`` and by status surfaces, and its remedy
is a command someone will run. So it has to be a command that will act for the
environment that asked: a client needs neither the model files nor the Qdrant
server and must not be told either is missing, and a host whose accelerator
stack is not usable yet must not be sent to a fetch command that would decline
it.

The capability is handed to the report as a caller that probed out of process
hands it. Everything else is real: a model cache this file owns in which every
model is missing, and managed directories that hold no Qdrant server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._readiness import ReadinessStatus, compute_readiness
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability
from ..operator_state._models import ComputeReport
from ._model_cache_seed import STAND_IN_DENSE, STAND_IN_RERANKER, seed_model_cache
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from .._readiness import DependencyReadiness

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("nothing_provisioned")]

_CLIENT = "this installation is a client"
_START_FETCHES = "`vaultspec-rag server start` fetches it"


@pytest.fixture
def nothing_provisioned(
    monkeypatch: pytest.MonkeyPatch, isolated_singleton_dirs: Path, tmp_path: Path
) -> Generator[None]:
    """Server mode, no Qdrant server installed or named, and no model cached."""
    del isolated_singleton_dirs
    with managed_env(
        **{
            EnvVar.LOCAL_ONLY.value: None,
            EnvVar.QDRANT_SERVER.value: None,
            EnvVar.QDRANT_URL.value: None,
            EnvVar.QDRANT_BINARY.value: None,
            EnvVar.QDRANT_BINARY_SHA256.value: None,
            EnvVar.HF_HUB_OFFLINE.value: "1",
        }
    ):
        seed_model_cache(
            monkeypatch,
            tmp_path / "hf-cache",
            missing=[STAND_IN_DENSE, STAND_IN_RERANKER],
        )
        yield


def _rows(capability: ComputeCapability) -> dict[str, DependencyReadiness]:
    report = compute_readiness(compute=ComputeReport(capability=capability))
    rows: dict[str, DependencyReadiness] = {}
    for name in ("models", "qdrant"):
        row = report.dimension(name)
        assert row is not None
        rows[name] = row
    return rows


def test_a_client_is_told_it_needs_neither_and_is_not_called_unready() -> None:
    """A client's report has nothing missing, because it needs nothing.

    Mutation check: with the client answer removed from the models row, that
    row reads not ready and names the missing repositories, and the status
    assertion fails for ``models``. With it removed from the Qdrant row, that
    row reads not ready because no binary resolves, and the same assertion
    fails for ``qdrant``. Restoring each passes.
    """
    rows = _rows(ComputeCapability.NOT_APPLICABLE)

    for name, row in rows.items():
        assert row.status == ReadinessStatus.READY, (name, row.detail)
        assert _CLIENT in row.detail, (name, row.detail)
    assert rows["models"].info == {"repos": {}}
    assert rows["qdrant"].info["binary_source"] == "not_needed"


def test_a_host_that_cannot_serve_yet_is_not_sent_to_a_command_that_declines() -> None:
    """The truth about what is missing, with a remedy that will act.

    Both fetch commands answer ``skipped`` for an environment that cannot run
    the service, so naming either would send the operator round a loop. The
    rows stay not ready - the files really are missing - and say what fetches
    them once the environment is repaired.

    Mutation check: with the remedy no longer asking what the environment can
    do, the models row names ``server warmup`` and the Qdrant row names
    ``server qdrant install``, and the first assertion on each fails.
    Restoring it passes.
    """
    rows = _rows(ComputeCapability.CPU_ONLY_BUILD)

    for name, declines in (
        ("models", "server warmup"),
        ("qdrant", "server qdrant install"),
    ):
        row = rows[name]
        assert declines not in row.detail, (name, row.detail)
        assert _START_FETCHES in row.detail, (name, row.detail)
        assert row.status == ReadinessStatus.NOT_READY, (name, row.detail)


def test_a_host_that_can_serve_is_given_the_command_that_fetches() -> None:
    """An environment the fetch commands will act for is given them, whole."""
    rows = _rows(ComputeCapability.READY)

    assert "run `vaultspec-rag server warmup`" in rows["models"].detail
    assert "run `vaultspec-rag server qdrant install`" in rows["qdrant"].detail
    for name, row in rows.items():
        assert row.status == ReadinessStatus.NOT_READY, (name, row.detail)
        assert _START_FETCHES not in row.detail, (name, row.detail)
