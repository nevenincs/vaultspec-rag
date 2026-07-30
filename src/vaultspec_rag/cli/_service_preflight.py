"""``server preflight``: read the device-load admission verdict, nothing more.

This never loads a model. It answers one question - does the GPU currently
have room for a load - by reading the same predicate the loader itself
consults before bringing a model stack up.

Service-first: a running daemon is already a torch-bearing process, so it is
asked to report its own reading over its torch-free HTTP surface, and this
verb only reads that reading. A local guarded probe is attempted ONLY when no
daemon is running at all - at that point this CLI invocation is the process
that would load the model, so it is the one asking the question locally
instead of relaying someone else's answer. A daemon that is running but does
not answer, or answers without a reading, is reported as unavailable; it is
never papered over with a second, local probe run alongside a live one.
"""

from __future__ import annotations

from typing import cast

import typer

from .._gpu_admission import (
    DeviceAdmission,
    device_contended_message,
    device_load_wire,
)
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_health
from ._app import JsonMode, PortOption, server_app
from ._render import _emit_json, _emit_json_error_and_exit, _plain, address_line

_PREFLIGHT_COMMAND = "server.preflight"


def _local_admission() -> DeviceAdmission:
    """Take the local, guarded reading - this process's own GPU question.

    Function-local import: ``evaluate_device_admission`` is the torch-tolerant
    predicate, but the caller reaching this branch has already resolved that no
    daemon is running, so this CLI invocation IS the would-be GPU consumer.
    """
    from .._gpu_admission import evaluate_device_admission

    return evaluate_device_admission()


def _optional_int(value: object) -> int | None:
    """Coerce a JSON-decoded numeric field to ``int``, or ``None`` if unusable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _admission_from_block(block: dict[str, object]) -> DeviceAdmission:
    """Rebuild the verdict a daemon's health payload carried.

    A figure the health block should never actually take (missing or
    non-numeric) degrades to the same "unreadable" reading
    ``evaluate_device_admission`` itself reports for an unmeasurable device,
    rather than being raised.
    """
    floor = _optional_int(block.get("floor_mib"))
    return DeviceAdmission(
        admitted=bool(block.get("admitted")),
        free_mib=_optional_int(block.get("free_mib")),
        total_mib=_optional_int(block.get("total_mib")),
        own_mib=_optional_int(block.get("own_mib")),
        floor_mib=floor if floor is not None else 0,
        reason=str(block.get("reason") or ""),
    )


def _daemon_admission(port: int) -> DeviceAdmission | None:
    """Read the device-load reading from a running daemon's health, torch-free.

    ``None`` when the daemon does not answer, or answers without a
    ``device_load`` block (an older release, or its own probe was
    unreadable) - the caller must not fall back to a local probe in either
    case, because a live daemon already owns this question.

    That holds even though a local probe is right there and would answer the
    same question: an unverifiable observation - a daemon that answers but
    cannot confirm the card's condition - must never be treated as "safe to
    check again ourselves", or a version-skewed daemon quietly shortens the
    protection this verb exists to give. The cost is that a stale daemon
    blocks this diagnostic until it is upgraded or restarted; that is the
    safe direction to fail, not a defect to route around with a silent local
    fallback.
    """
    health = _try_http_health(port)
    if not isinstance(health, dict):
        return None
    block = health.get("device_load")
    if not isinstance(block, dict):
        return None
    return _admission_from_block(cast("dict[str, object]", block))


def _fail_unavailable(json_mode: bool, port: int) -> None:
    """Report a running daemon that could not answer the device-load question."""
    message = (
        f"The service on port {port} did not report a device-load reading. It "
        "may be unreachable, or running a release that predates this "
        "diagnostic. No local probe was attempted: a running daemon already "
        "owns this question, this CLI invocation does not."
    )
    if json_mode:
        _emit_json_error_and_exit(
            _PREFLIGHT_COMMAND,
            "device_load_unavailable",
            message,
            1,
            data={"source": "service", "port": port},
        )
        return
    _plain(address_line(port))
    _plain(message)
    raise typer.Exit(1)


def _render_human(admission: DeviceAdmission, source: str) -> None:
    """Print the reading legibly enough to show WHY a refusal happened."""
    _plain(f"Device-load reading ({source}):")
    free = "unreadable" if admission.free_mib is None else f"{admission.free_mib} MiB"
    total = (
        "" if admission.total_mib is None else f" of {admission.total_mib} MiB total"
    )
    _plain(f"  free: {free}{total}")
    if admission.own_mib is not None:
        _plain(f"  held by the reporting process: {admission.own_mib} MiB")
    _plain(f"  floor: {admission.floor_mib} MiB")
    _plain(f"  verdict: {'admitted' if admission.admitted else 'refused'}")
    if not admission.admitted:
        _plain(device_contended_message(admission))


def _report(admission: DeviceAdmission, source: str, json_mode: bool) -> None:
    """Emit exactly one outcome for *admission* and exit 0/1 on its verdict."""
    if json_mode:
        if admission.admitted:
            _emit_json(
                True,
                _PREFLIGHT_COMMAND,
                data={"source": source, **device_load_wire(admission)},
            )
            raise typer.Exit(0)
        _emit_json_error_and_exit(
            _PREFLIGHT_COMMAND,
            admission.reason or "not_admitted",
            device_contended_message(admission),
            1,
            data={"source": source, **device_load_wire(admission)},
        )
        return
    _render_human(admission, source)
    raise typer.Exit(0 if admission.admitted else 1)


@server_app.command(
    "preflight",
    help="Report whether the GPU device currently has room for a model load.",
)
def service_preflight(port: PortOption = None, json_mode: JsonMode = False) -> None:
    """Read the device-load admission verdict without loading anything.

    Exit 0 when the device admits a load right now, exit 1 when it does not -
    a torch-free or CUDA-less host is a refusal here, not a crash.
    """
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is not None:
        admission = _daemon_admission(resolved_port)
        if admission is None:
            _fail_unavailable(json_mode, resolved_port)
            return
        _report(admission, "service", json_mode)
        return
    _report(_local_admission(), "local", json_mode)
