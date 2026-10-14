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
_START_FETCHES = "`vaultspec-rag server start` downloads it"


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

    Its rows read "not applicable", not "ready": a client cannot itself
    start the service, and a "ready" row would say otherwise. Not applicable
    still never counts as unready - it does not block the aggregate.

    Mutation check: with the client answer removed from the models row, that
    row reads not ready and names the missing repositories, and the status
    assertion fails for ``models``. With it removed from the Qdrant row, that
    row reads not ready because no binary resolves, and the same assertion
    fails for ``qdrant``. Restoring each passes.
    """
    rows = _rows(ComputeCapability.NOT_APPLICABLE)

    for name, row in rows.items():
        assert row.status == ReadinessStatus.NOT_APPLICABLE, (name, row.detail)
        assert _CLIENT in row.detail, (name, row.detail)
    assert rows["models"].info == {"repos": {}}
    assert rows["qdrant"].info["binary_source"] == "not_needed"


def test_a_host_that_cannot_serve_yet_is_not_sent_to_a_command_that_declines() -> None:
    """The truth about what is missing, with a remedy that will act.

    Both fetch commands answer ``skipped`` for an environment that cannot run
    the service, so naming either would send the operator round a loop. The
    rows stay not ready - the files really are missing - and say what fetches
    them: the start, which builds the environment that serves.

    Mutation check: naming the fetch command again whenever automatic
    download is on fails the first assertion for each row. Restoring passes.
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


def test_a_host_that_can_serve_is_given_the_one_command_that_fetches() -> None:
    """Starting is consent to download, so the start is the one command.

    Mutation check: appending the on-disk alternative to the Qdrant row fails
    the ``--local-only`` assertion; naming ``server warmup`` again fails the
    models row's first assertion. Restoring passes.
    """
    rows = _rows(ComputeCapability.READY)

    for name, row in rows.items():
        assert _START_FETCHES in row.detail, (name, row.detail)
        assert row.status == ReadinessStatus.NOT_READY, (name, row.detail)
        assert "--local-only" not in row.detail, (name, row.detail)


def test_switching_automatic_download_off_names_the_qdrant_install() -> None:
    """With the Qdrant download switched off, a start would refuse, so the
    install command is the one that acts.

    Mutation check: ignoring the switch fails the first assertion.
    Restoring passes.
    """
    with managed_env(**{EnvVar.QDRANT_AUTO_PROVISION.value: "0"}):
        rows = _rows(ComputeCapability.READY)

    assert "run `vaultspec-rag server qdrant install`" in rows["qdrant"].detail
    assert _START_FETCHES not in rows["qdrant"].detail
