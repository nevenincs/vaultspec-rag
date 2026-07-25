"""Client/server release compatibility: the published datum and the two gates.

Two separate contracts are proven here, and they deliberately have different
strengths.

The discovery file's ``(schema, version)`` discriminator is a hard gate: the
published contract instructs a consumer to pin on the pair and refuse a file it
does not understand, and these tests drive the real readers against real files
on disk to prove the refusal actually happens. Those are guard tests.

The package release is a published signal, not a gate: it must reach every wire
surface that identifies the daemon, and a pairing that cannot be confirmed must
report as unconfirmed rather than as agreement.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from ..serviceclient._discovery import (
    DISCOVERY_REASON_POINTER_INCOMPATIBLE,
    DISCOVERY_STATE_DEGRADED,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _read_service_status,
    _status_file,
    discovery_payload_supported,
)
from ..serviceclient._release import (
    RELEASE_FIELD,
    RELEASE_MATCH,
    RELEASE_MISMATCH,
    RELEASE_UNKNOWN,
    compare_release,
    local_release,
    payload_release,
    payload_release_compatibility,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_pointer(path: Path, **overrides: object) -> Path:
    """Write a discovery file carrying the real constants, plus overrides."""
    payload: dict[str, object] = {
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        "pid": os.getpid(),
        "port": 8766,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestDiscoveryDiscriminatorIsEnforced:
    """The documented ``(schema, version)`` pin is a real refusal, not prose."""

    def test_matching_pair_is_supported(self) -> None:
        assert discovery_payload_supported(
            {
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
            }
        )

    def test_absent_pair_is_the_pre_discriminator_case(self) -> None:
        # A file written before the discriminator existed carries neither half.
        # The next daemon heartbeat upgrades it in place, so refusing it would
        # turn an ordinary upgrade into a foreign-build report.
        assert discovery_payload_supported({"pid": 1, "port": 2})

    def test_a_foreign_schema_is_refused(self) -> None:
        assert not discovery_payload_supported(
            {"schema": "some.other.product", "version": SERVICE_DISCOVERY_VERSION}
        )

    def test_an_unknown_version_is_refused(self) -> None:
        assert not discovery_payload_supported(
            {
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION + 1,
            }
        )

    def test_half_a_pair_is_refused(self) -> None:
        # A partial or truncated write declares one half without the other.
        assert not discovery_payload_supported({"schema": SERVICE_DISCOVERY_SCHEMA})
        assert not discovery_payload_supported({"version": SERVICE_DISCOVERY_VERSION})

    def test_a_boolean_version_does_not_satisfy_a_version_one_pin(self) -> None:
        # `True == 1`, so an `isinstance` check would accept this.
        assert not discovery_payload_supported(
            {"schema": SERVICE_DISCOVERY_SCHEMA, "version": True}
        )


class TestStatusFileReaderRefusesForeignShapes:
    """``_read_service_status`` refuses a file it cannot claim to understand."""

    def test_a_supported_file_is_read(self, isolated_status_dir: Path) -> None:
        _write_pointer(_status_file())

        assert _read_service_status() is not None

    def test_an_unversioned_file_is_still_read(
        self, isolated_status_dir: Path
    ) -> None:
        sf = _status_file()
        sf.write_text(json.dumps({"pid": os.getpid(), "port": 8766}), encoding="utf-8")

        assert _read_service_status() is not None

    def test_a_future_version_file_is_refused(
        self, isolated_status_dir: Path
    ) -> None:
        # Guard: mutation-proved by deleting the `discovery_payload_supported`
        # check in `_read_service_status`, which makes this assertion fail with
        # the parsed dict in place of None. The pid and port of a file written
        # to a shape this build does not know are not this build's pid and
        # port, so acting on them would drive or kill a foreign process.
        _write_pointer(_status_file(), version=SERVICE_DISCOVERY_VERSION + 1)

        assert _read_service_status() is None

    def test_a_foreign_schema_file_is_refused(
        self, isolated_status_dir: Path
    ) -> None:
        _write_pointer(_status_file(), schema="some.other.product")

        assert _read_service_status() is None


class TestMachinePointerResolutionRefusesForeignShapes:
    """A live holder with an unreadable-shape pointer is degraded, not ready."""

    def test_incompatible_pointer_resolves_degraded_with_its_own_reason(
        self, isolated_singleton_dirs: Path
    ) -> None:
        # Guard: mutation-proved by deleting the `discovery_payload_supported`
        # branch in `resolve_machine_service`, which makes the state assertion
        # fail with `ready` in place of `degraded`. Driven through the real
        # resolver against a real OS lock holder and a real pointer file.
        from .._machine_lock import (
            acquire_machine_lock_lease,
            machine_discovery_path,
            publish_machine_discovery,
            release_machine_lock_lease,
        )
        from ..serviceclient._discovery import resolve_machine_service

        lease, _holder = acquire_machine_lock_lease()
        assert lease is not None, "the test must own the machine singleton"
        try:
            publish_machine_discovery(
                lease,
                {
                    "schema": SERVICE_DISCOVERY_SCHEMA,
                    "version": SERVICE_DISCOVERY_VERSION + 1,
                    "pid": lease.pid,
                    "port": 8766,
                },
            )
            resolution = resolve_machine_service()
        finally:
            machine_discovery_path().unlink(missing_ok=True)
            release_machine_lock_lease(lease)

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.reason == DISCOVERY_REASON_POINTER_INCOMPATIBLE
        # None of the foreign payload's fields are carried forward as though
        # this build knew what they meant.
        assert resolution.port is None
        assert not resolution.is_ready


class TestReleaseVerdict:
    """An unconfirmed pairing is never reported as agreement."""

    def test_equal_releases_match(self) -> None:
        verdict = compare_release("1.2.3", client="1.2.3")

        assert verdict.verdict == RELEASE_MATCH
        assert verdict.confirmed
        assert not verdict.is_mismatch

    def test_different_releases_mismatch_and_name_both_sides(self) -> None:
        verdict = compare_release("0.3.9", client="0.4.0")

        assert verdict.verdict == RELEASE_MISMATCH
        assert verdict.is_mismatch
        assert "0.4.0" in verdict.summary()
        assert "0.3.9" in verdict.summary()

    def test_an_unreported_release_is_unknown_not_a_match(self) -> None:
        # Guard: mutation-proved by making `compare_release` fall through to
        # RELEASE_MATCH when the service release is absent, which makes the
        # verdict assertion fail with `match` in place of `unknown`. A daemon
        # predating the field cannot be confirmed compatible, and reporting an
        # unconfirmed pairing as agreement is the failure being removed.
        for absent in (None, "", 17, {"nested": "thing"}):
            verdict = compare_release(absent, client="0.4.0")

            assert verdict.verdict == RELEASE_UNKNOWN
            assert not verdict.confirmed
            assert not verdict.is_mismatch
            assert verdict.service is None

    def test_local_release_is_the_running_package_release(self) -> None:
        from vaultspec_rag import __version__

        assert local_release() == __version__

    def test_payload_release_reads_the_declared_field(self) -> None:
        assert payload_release({RELEASE_FIELD: "9.9.9"}) == "9.9.9"
        assert payload_release({RELEASE_FIELD: 9}) is None
        assert payload_release({}) is None
        assert payload_release("not a payload") is None

    def test_payload_compatibility_uses_the_declared_field(self) -> None:
        verdict = payload_release_compatibility(
            {RELEASE_FIELD: "0.0.1"}, client="0.0.2"
        )

        assert verdict.verdict == RELEASE_MISMATCH
        assert verdict.service == "0.0.1"


class TestReleaseReachesEveryWireSurface:
    """The datum a client compares must actually cross the process boundary."""

    def test_health_route_publishes_the_release_ungated(self) -> None:
        # /health is the ungated route, so it is the one surface where a client
        # can establish which build it is about to drive before it holds a
        # token. Driven through the real route, not the handler's return value.
        from typing import Any, cast

        import httpx
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from ..server._lifespan import health_handler
        from .test_server import _empty_lifespan

        app = Starlette(
            routes=[Route("/health", health_handler)], lifespan=_empty_lifespan
        )
        client = cast("httpx.Client", TestClient(app))
        data = cast("dict[str, Any]", client.get("/health").json())

        assert data[RELEASE_FIELD] == local_release()
        # The storage-schema version already on this route is a different fact.
        assert RELEASE_FIELD != "schema_version"
        assert data[RELEASE_FIELD] != data["schema_version"]

    def test_readiness_report_publishes_the_release(self) -> None:
        from .._readiness import compute_readiness

        report = json.loads(json.dumps(compute_readiness().to_dict()))

        assert report[RELEASE_FIELD] == local_release()

    def test_cli_parent_status_write_publishes_the_release(
        self, isolated_status_dir: Path
    ) -> None:
        from ..cli._service_status import _write_service_status

        _write_service_status(pid=os.getpid(), port=8766)
        data = json.loads(_status_file().read_text(encoding="utf-8"))

        assert data[RELEASE_FIELD] == local_release()

    def test_daemon_discovery_snapshot_publishes_the_release(self) -> None:
        # The daemon's snapshot builder reads live module state, so the port and
        # identity token are set on the real module for the length of the call
        # rather than the builder being stubbed out.
        import vaultspec_rag.server as _m
        from ..server._lifecycle import _daemon_discovery_snapshot
        from ..serviceclient._discovery import SERVICE_PHASE_RUNNING

        prior_port, prior_token = _m._service_port, _m._SERVICE_TOKEN
        _m._service_port, _m._SERVICE_TOKEN = 8766, "tok-test"
        try:
            snapshot = _daemon_discovery_snapshot(
                phase=SERVICE_PHASE_RUNNING,
                started_at="2026-01-01T00:00:00+00:00",
            )
        finally:
            _m._service_port, _m._SERVICE_TOKEN = prior_port, prior_token

        assert snapshot[RELEASE_FIELD] == local_release()
        # The interpreter version is a different fact and both are published.
        assert snapshot["python_version"] != snapshot[RELEASE_FIELD]

    def test_a_published_snapshot_round_trips_through_the_reader(
        self, isolated_status_dir: Path
    ) -> None:
        # The writer's own discriminator must satisfy the reader's pin, or the
        # gate above would refuse this project's own files.
        from ..cli._service_status import _write_service_status

        _write_service_status(pid=os.getpid(), port=8766)
        data = _read_service_status()

        assert data is not None
        assert payload_release_compatibility(data).verdict == RELEASE_MATCH
