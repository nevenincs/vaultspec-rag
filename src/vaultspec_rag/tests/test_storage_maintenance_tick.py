"""A scheduled storage-maintenance cycle closes every job record it opens."""

from __future__ import annotations

import pytest

from .. import jobs as _jobs
from ..config._types import EnvVar
from ..job_models import JobSource
from ..server._lifecycle import _storage_maintenance_tick_sync
from .conftest import managed_env

pytestmark = pytest.mark.unit


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_cycle_whose_client_cannot_be_built_still_closes_its_record() -> None:
    # Building the Qdrant client can fail outright - the incident was a CA
    # bundle deleted from under the running service, and a malformed address
    # fails the same constructor the same way. That construction sat outside
    # the guard, leaving a record running with no thread behind it, and each
    # hourly cycle added another. Mutation: moving the construction back above
    # the guard fails the phase assertion.
    _jobs.reset()

    with (
        managed_env(**{EnvVar.QDRANT_URL.value: "http://127.0.0.1:notaport"}),
        pytest.raises(ValueError, match="notaport"),
    ):
        _storage_maintenance_tick_sync()

    [record] = [
        record
        for record in _jobs.snapshot()
        if record.get("source") == JobSource.MAINTENANCE.value
    ]
    assert record["phase"] == "error"
    assert "notaport" in str(record["result"])
