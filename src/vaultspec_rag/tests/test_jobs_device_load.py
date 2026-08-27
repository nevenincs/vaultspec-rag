"""The device-load admission reading on the jobs listing.

Two properties are load-bearing: the reading is cached the same few seconds
the GPU pressure block is, so a poll inside the window never pays a second
device probe; and a probe that cannot answer is reported absent (``None``)
rather than raised, so an older reader missing the key is unaffected and a
daemon that cannot measure the device never turns ``/jobs`` into an error.
Each guard names the mutation that would make it fail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

_DEVICE_LOAD_KEYS = {
    "free_mib",
    "total_mib",
    "own_mib",
    "floor_mib",
    "admitted",
    "reason",
}
_T0 = 200_000.0


@pytest.fixture(autouse=True)
def clear_device_load_cache() -> Iterator[None]:
    """Isolate the module-level snapshot cache across tests.

    The cache is a bare module global, so a reading left over from one test
    would otherwise answer the next one's poll instead of the substituted
    reading it installed.
    """
    import vaultspec_rag._job_evidence as jobs_module

    jobs_module._device_load_snapshot_cache = None
    yield
    jobs_module._device_load_snapshot_cache = None


def _reading(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "free_mib": 9000,
        "total_mib": 16376,
        "own_mib": 0,
        "floor_mib": 6400,
        "admitted": True,
        "reason": "",
    }
    base.update(overrides)
    return base


class TestDeviceLoadSnapshotCaching:
    def test_a_poll_inside_the_window_reuses_the_cached_reading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proven able to fail: dropping the freshness check so every call
        re-reads. Observed this assertion fail on ``calls == [1]`` (two calls
        recorded instead of one).
        """
        import vaultspec_rag._gpu_admission as admission_module

        from .._job_evidence import device_load_snapshot

        calls: list[int] = []

        def _tracked() -> dict[str, object]:
            calls.append(1)
            return _reading()

        monkeypatch.setattr(admission_module, "device_load_reading", _tracked)

        first = device_load_snapshot(now=_T0)
        second = device_load_snapshot(now=_T0 + 1.0)

        assert first == second
        assert len(calls) == 1, calls

    def test_a_poll_past_the_window_takes_a_fresh_reading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proven able to fail: widening the cache window so a poll five
        seconds later still hits the stale entry. Observed this assertion
        fail on ``len(calls) == 2`` (only one call recorded).
        """
        import vaultspec_rag._gpu_admission as admission_module

        from .._job_evidence import (
            _DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS,
            device_load_snapshot,
        )

        calls: list[int] = []

        def _tracked() -> dict[str, object]:
            calls.append(1)
            return _reading()

        monkeypatch.setattr(admission_module, "device_load_reading", _tracked)

        device_load_snapshot(now=_T0)
        device_load_snapshot(now=_T0 + _DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS + 1.0)

        assert len(calls) == 2, calls

    def test_mutating_the_returned_reading_cannot_poison_the_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vaultspec_rag._gpu_admission as admission_module

        from .._job_evidence import device_load_snapshot

        monkeypatch.setattr(admission_module, "device_load_reading", lambda: _reading())

        first = device_load_snapshot(now=_T0)
        assert first is not None
        first["free_mib"] = -1

        second = device_load_snapshot(now=_T0 + 1.0)
        assert second is not None
        assert second["free_mib"] == 9000


class TestDeviceLoadSnapshotAbsence:
    def test_an_absent_reading_is_returned_as_none_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The underlying reading is itself never-raising, but the snapshot
        must pass ``None`` through rather than treating it as cache-empty and
        looping, or coercing it into an error.

        Mutation: made the cache-hit branch raise on a cached ``None`` value
        instead of returning it. Observed this assertion fail with the
        injected exception instead of a clean ``None``.
        """
        import vaultspec_rag._gpu_admission as admission_module

        from .._job_evidence import device_load_snapshot

        monkeypatch.setattr(admission_module, "device_load_reading", lambda: None)

        assert device_load_snapshot(now=_T0) is None
        assert device_load_snapshot(now=_T0 + 1.0) is None

    def test_an_absent_reading_is_cached_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A torch-free host's ``None`` reading must not be re-probed every
        poll either - the whole point of caching is to bound the read rate
        regardless of what the read comes back as.
        """
        import vaultspec_rag._gpu_admission as admission_module

        from .._job_evidence import device_load_snapshot

        calls: list[int] = []

        def _tracked() -> None:
            calls.append(1)
            return None

        monkeypatch.setattr(admission_module, "device_load_reading", _tracked)

        device_load_snapshot(now=_T0)
        device_load_snapshot(now=_T0 + 1.0)

        assert len(calls) == 1, calls


class TestJobsRouteDeviceLoadExposure:
    """GET /jobs carries the device-load block beside the GPU/pressure ones."""

    def test_the_listing_envelope_carries_the_device_load_block(self) -> None:
        from starlette.testclient import TestClient

        from ..server import ServerRouteRuntime, create_http_app
        from ..service import ServiceRegistry

        token = "device-load-exposure-test-token"
        app = create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=8765),
            lifespan=None,
        )
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        response: httpx.Response = client.get(
            "/jobs", headers={"Authorization": f"Bearer {token}"}
        )
        payload = cast("dict[str, object]", response.json())
        assert "device_load" in payload
        device_load = payload["device_load"]
        if device_load is not None:
            assert set(cast("dict[str, object]", device_load)) == _DEVICE_LOAD_KEYS
