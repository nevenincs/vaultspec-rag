"""``server preflight``: observe a quiesced service; never authorize a borrower.

The service owns GPU residency and the controller's quiescence truth.  This
command only reads the discovered service's authenticated service-state and
health documents; it never starts a service and never makes a local CUDA or
Torch probe.  A successful observation is deliberately not permission to use
the GPU: a borrower must still hold the distinct borrower lease.
"""

from __future__ import annotations

import hmac
from collections.abc import Sized
from math import isfinite
from typing import Final, NoReturn

import typer

from .._timestamps import age_seconds
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS, QuiesceState
from ..serviceclient._compat import SERVICE_VERSION_FIELD, classify_service_version
from ..serviceclient._discovery import MachineResolution, resolve_machine_service
from ..serviceclient._transport import (
    _get_admin_timeout,
    _try_http_admin,
    _try_http_health,
    health_probe_timed_out,
)
from ._app import JsonMode, PortOption, server_app
from ._render import _emit_json, _emit_json_error_and_exit, _plain, address_line

_PREFLIGHT_COMMAND: Final = "server.preflight"
_LEASE_REQUIRED: Final = "A borrower lease is required before GPU work may begin."


def _finite_number(value: object) -> bool:
    """Whether a JSON value is a finite numeric observation, excluding bool."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _positive_finite_number(value: object) -> float | None:
    """Return a positive finite JSON number, excluding bool, or ``None``."""
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not isfinite(float(value))
    ):
        return None
    number = float(value)
    return number if number > 0 else None


def _has_expected_mapping_size(value: object, expected: int) -> bool:
    """Whether an untyped JSON value is a mapping with exactly *expected* fields."""
    return isinstance(value, Sized) and len(value) == expected


def _strict_quiesce(value: object) -> dict[str, object] | None:
    """Accept exactly the controller's published quiesce vocabulary.

    Current production routes always generate this block from
    ``QuiesceSnapshot.as_envelope``.  The checks therefore remain static
    defense-in-depth for a proxy, an older service, or future wire drift; this
    module intentionally has no fabricated malformed-success test seam.
    """
    match value:
        case {
            "state": str() as state,
            "admission_epoch": int() as epoch,
            "admissions_open": bool() as admissions_open,
            "active_compute_tickets": int() as tickets,
            "drain_complete": bool() as drain_complete,
            "vram_released": bool() as vram_released,
            "safe_to_borrow_gpu": bool() as safe_to_borrow_gpu,
            "pause_requested_at": (int() | float() | None) as pause_requested_at,
            "drain_acknowledged_at": (int() | float() | None) as drain_acknowledged_at,
            "quiesced_at": (int() | float() | None) as quiesced_at,
            "warming_started_at": (int() | float() | None) as warming_started_at,
            "failure_reason": (str() | None) as failure_reason,
        } if _has_expected_mapping_size(value, len(QUIESCE_ENVELOPE_FIELDS)):
            timestamps = (
                pause_requested_at,
                drain_acknowledged_at,
                quiesced_at,
                warming_started_at,
            )
            if (
                state not in {item.value for item in QuiesceState}
                or isinstance(epoch, bool)
                or epoch < 0
                or isinstance(tickets, bool)
                or tickets < 0
                or any(isinstance(timestamp, bool) for timestamp in timestamps)
                or any(
                    timestamp is not None and not _finite_number(timestamp)
                    for timestamp in timestamps
                )
                or (
                    safe_to_borrow_gpu
                    and (
                        pause_requested_at is None
                        or drain_acknowledged_at is None
                        or quiesced_at is None
                    )
                )
            ):
                return None
            return {
                "state": state,
                "admission_epoch": epoch,
                "admissions_open": admissions_open,
                "active_compute_tickets": tickets,
                "drain_complete": drain_complete,
                "vram_released": vram_released,
                "safe_to_borrow_gpu": safe_to_borrow_gpu,
                "pause_requested_at": pause_requested_at,
                "drain_acknowledged_at": drain_acknowledged_at,
                "quiesced_at": quiesced_at,
                "warming_started_at": warming_started_at,
                "failure_reason": failure_reason,
            }
        case _:
            return None


def _strict_capacity(value: object) -> dict[str, object] | None:
    """Accept the service's device-capacity observation without granting it power."""
    match value:
        case {
            "free_mib": (int() | None) as free_mib,
            "total_mib": (int() | None) as total_mib,
            "own_mib": (int() | None) as own_mib,
            "floor_mib": int() as floor_mib,
            "admitted": bool() as admitted,
            "reason": str() as reason,
        } if _has_expected_mapping_size(value, 6):
            readings = (free_mib, total_mib, own_mib, floor_mib)
            if any(
                isinstance(reading, bool) or (reading is not None and reading < 0)
                for reading in readings
            ):
                return None
            return {
                "free_mib": free_mib,
                "total_mib": total_mib,
                "own_mib": own_mib,
                "floor_mib": floor_mib,
                "admitted": admitted,
                "reason": reason,
            }
        case _:
            return None


def _discovery_failure(resolution: MachineResolution) -> tuple[str, str] | None:
    """Return the reason a discovered service cannot be trusted for observation."""
    if not resolution.is_ready or resolution.port is None:
        evidence = resolution.evidence()
        return (
            "service_discovery_unavailable",
            f"No usable service discovery is available: {evidence}.",
        )
    payload = resolution.payload
    heartbeat_age = age_seconds(payload, "last_heartbeat") if payload else None
    stale_after = _positive_finite_number(
        payload.get("stale_after_s") if payload else None
    )
    if heartbeat_age is None or stale_after is None:
        return (
            "service_discovery_incomplete",
            "The discovered service did not publish a usable heartbeat window.",
        )
    if heartbeat_age < 0:
        return (
            "service_discovery_unknown",
            "The discovered service heartbeat is in the future, so freshness is "
            "unknown.",
        )
    if heartbeat_age > stale_after:
        return (
            "service_discovery_stale",
            "The discovered service heartbeat is stale; no GPU work is authorized.",
        )
    return None


def _observation_data(
    *,
    port: int | None,
    quiesce: dict[str, object] | None = None,
    capacity: dict[str, object] | None = None,
    version: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the uniform observation data with authorization explicitly denied."""
    data: dict[str, object] = {
        "source": "service",
        "authorized": False,
        "lease_required": True,
        "authorization": _LEASE_REQUIRED,
    }
    if port is not None:
        data["port"] = port
    if version is not None:
        data["version"] = version
    if quiesce is not None:
        data["quiesce"] = quiesce
    if capacity is not None:
        data["capacity"] = capacity
    return data


def _fail(
    *,
    json_mode: bool,
    error: str,
    message: str,
    data: dict[str, object],
) -> NoReturn:
    """Report one fail-closed preflight outcome."""
    if json_mode:
        _emit_json_error_and_exit(
            _PREFLIGHT_COMMAND,
            error,
            message,
            1,
            data=data,
        )
        raise AssertionError("the JSON preflight failure did not exit")
    port = data.get("port")
    if isinstance(port, int) and not isinstance(port, bool):
        _plain(address_line(port))
    _plain(message)
    _plain(f"GPU authorization: denied. {_LEASE_REQUIRED}")
    raise typer.Exit(1)


def _observed_health(
    *,
    port: int,
    json_mode: bool,
    version_data: dict[str, object],
) -> dict[str, object]:
    """Take the health evidence read, failing closed on absence or on silence.

    The read shares the authenticated read's operator-governed bound: it is one
    of this verb's two evidence reads over the same wire, and the probe's
    shorter default belongs to readiness polls, where a fast "not up yet"
    answer is the point. Here that short bound turned a busy service into a
    false "unreachable" verdict.
    """
    health = _try_http_health(port, timeout=_get_admin_timeout())
    if health is None:
        _fail(
            json_mode=json_mode,
            error="service_unreachable",
            message=f"The discovered service on port {port} is unreachable.",
            data=_observation_data(port=port),
        )
    if health_probe_timed_out(health):
        # An unanswered probe is not absence: the connection was accepted, so
        # something holds the port and simply did not answer within the bound.
        _fail(
            json_mode=json_mode,
            error="service_health_timeout",
            message=(
                f"The discovered service on port {port} accepted a "
                "connection but did not answer the health probe in time."
            ),
            data=_observation_data(port=port, version=version_data),
        )
    return health


def _quiesce_is_safe(quiesce: dict[str, object]) -> bool:
    """Whether the observed controller snapshot meets the exact safe handoff."""
    return (
        quiesce["state"] == QuiesceState.QUIESCED.value
        and quiesce["admissions_open"] is False
        and quiesce["active_compute_tickets"] == 0
        and quiesce["drain_complete"] is True
        and quiesce["vram_released"] is True
        and quiesce["safe_to_borrow_gpu"] is True
        and quiesce["failure_reason"] is None
    )


def _health_matches_discovery(
    health: dict[str, object],
    *,
    pid: int | None,
    port: int,
    service_token: str | None,
    package_version: str | None,
) -> bool:
    """Require health to confirm every identity fact published by discovery."""
    health_pid = health.get("pid")
    health_port = health.get("port")
    health_token = health.get("service_token")
    health_version = health.get(SERVICE_VERSION_FIELD)
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and pid > 0
        and isinstance(service_token, str)
        and bool(service_token)
        and isinstance(package_version, str)
        and isinstance(health_pid, int)
        and not isinstance(health_pid, bool)
        and health_pid > 0
        and health_pid == pid
        and isinstance(health_port, int)
        and not isinstance(health_port, bool)
        and health_port == port
        and isinstance(health_token, str)
        and hmac.compare_digest(health_token, service_token)
        and isinstance(health_version, str)
        and health_version == package_version
    )


@server_app.command(
    "preflight",
    help="Observe service quiescence and device capacity without authorizing GPU work.",
)
def service_preflight(port: PortOption = None, json_mode: JsonMode = False) -> None:
    """Read strict remote service evidence; a borrower lease remains mandatory."""
    resolution = resolve_machine_service()
    discovery_failure = _discovery_failure(resolution)
    if discovery_failure is not None:
        error, message = discovery_failure
        _fail(
            json_mode=json_mode,
            error=error,
            message=message,
            data=_observation_data(port=resolution.port),
        )
    resolved_port = resolution.port
    if port is not None and port != resolved_port:
        _fail(
            json_mode=json_mode,
            error="service_port_mismatch",
            message=(
                f"The requested port {port} is not the discovered service port "
                f"{resolved_port}."
            ),
            data=_observation_data(port=resolved_port),
        )
    if resolved_port is None:
        _fail(
            json_mode=json_mode,
            error="service_discovery_unavailable",
            message="No usable service discovery is available.",
            data=_observation_data(port=None),
        )

    version = classify_service_version(resolution.payload)
    version_data = version.to_dict()
    if not version.is_compatible:
        _fail(
            json_mode=json_mode,
            error=version.error_code() or "service_version_unreported",
            message=f"The discovered service is not compatible: {version.reason()}.",
            data=_observation_data(port=resolved_port, version=version_data),
        )

    health = _observed_health(
        port=resolved_port,
        json_mode=json_mode,
        version_data=version_data,
    )
    service_token = resolution.service_token
    if not _health_matches_discovery(
        health,
        pid=resolution.pointer_pid,
        port=resolved_port,
        service_token=service_token,
        package_version=version.service_version,
    ):
        _fail(
            json_mode=json_mode,
            error="service_identity_mismatch",
            message=(
                "The health response does not confirm the discovered service identity."
            ),
            data=_observation_data(port=resolved_port, version=version_data),
        )
    if service_token is None:
        raise AssertionError("matching discovery identity did not provide a token")

    capacity = _strict_capacity(health.get("device_load"))
    if capacity is None:
        _fail(
            json_mode=json_mode,
            error="device_capacity_unavailable",
            message=(
                "The discovered service did not provide a complete device-capacity "
                "observation."
            ),
            data=_observation_data(port=resolved_port, version=version_data),
        )
    service_state = _try_http_admin(
        "get_service_state",
        {},
        resolved_port,
        initial_bearer_token=service_token,
    )
    if service_state is None or not service_state or service_state.get("ok") is False:
        _fail(
            json_mode=json_mode,
            error="service_state_unavailable",
            message=(
                "The discovered service did not provide authenticated service-state "
                "evidence."
            ),
            data=_observation_data(
                port=resolved_port,
                capacity=capacity,
                version=version_data,
            ),
        )
    quiesce = _strict_quiesce(service_state.get("quiesce"))
    if quiesce is None:
        _fail(
            json_mode=json_mode,
            error="service_state_incomplete",
            message=(
                "The discovered service did not provide the complete quiesce "
                "vocabulary."
            ),
            data=_observation_data(
                port=resolved_port,
                capacity=capacity,
                version=version_data,
            ),
        )
    data = _observation_data(
        port=resolved_port,
        quiesce=quiesce,
        capacity=capacity,
        version=version_data,
    )
    if not _quiesce_is_safe(quiesce):
        _fail(
            json_mode=json_mode,
            error="service_not_safe_to_borrow_gpu",
            message=(
                "The discovered service is not in an acknowledged safe-to-borrow state."
            ),
            data=data,
        )
    if json_mode:
        _emit_json(True, _PREFLIGHT_COMMAND, data=data)
        raise typer.Exit(0)
    _plain(address_line(resolved_port))
    _plain("Service quiesce observation: acknowledged safe handoff.")
    _plain("GPU authorization: denied. " + _LEASE_REQUIRED)
    raise typer.Exit(0)
