"""A scheduled storage-maintenance cycle closes every job record it opens."""

from __future__ import annotations

import pytest

from .. import jobs as _jobs
from ..job_models import JobSource
from ..server._lifecycle import _storage_maintenance_tick_sync

pytestmark = pytest.mark.unit


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_cycle_whose_client_cannot_be_built_still_closes_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building the Qdrant client loads the CA bundle even for a plain http URL,
    # so a damaged environment fails right after the record opens. That
    # construction sat outside the guard, leaving a record running with no
    # thread behind it, and each hourly cycle added another. Mutation: moving
    # the construction back above the guard fails the phase assertion.
    _jobs.reset()

    def unbuildable(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", "cacert.pem")

    monkeypatch.setattr("qdrant_client.QdrantClient", unbuildable)

    with pytest.raises(FileNotFoundError):
        _storage_maintenance_tick_sync()

    [record] = [
        record
        for record in _jobs.snapshot()
        if record.get("source") == JobSource.MAINTENANCE.value
    ]
    assert record["phase"] == "error"
    assert "cacert.pem" in str(record["result"])
