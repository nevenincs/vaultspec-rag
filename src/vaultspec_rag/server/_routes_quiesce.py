"""The service-quiesce control pair and the borrower coordination it enforces.

``POST /pause`` and ``POST /resume`` are the only routes that change what the
whole daemon will admit, and they are the only ones a GPU borrower can hold
against an operator. That pairing - one envelope shape across every exit, and
one place deciding whether a capability may take or release the hold - is what
keeps this out of the general route module: a refusal here has to name an
owner, and every other route in the service answers for itself alone.

The handlers are registered onto the ``ROUTES`` table assembled in
:mod:`._routes`, on the same terms as every other sibling ``_routes_*`` module.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import TYPE_CHECKING, Final, TypeGuard, cast

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse

from ..config._settings import rag_default
from ..gpu_borrow_lease import is_borrower_capability
from ..logging_config import log_event
from ..service_quiesce import (
    QuiesceState,
    QuiesceTransitionCode,
    ServiceQuiesceTransitionConflictError,
    ServiceQuiesceTransitionWaitTimeoutError,
)
from ..serviceclient._transport import resolve_timeout
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..service import ServiceRegistry
    from ..service_quiesce import QuiesceSnapshot, QuiesceTransition

logger = logging.getLogger("vaultspec_rag.server")


def _quiesce_envelope(
    *,
    achieved: bool,
    status: str,
    snapshot: QuiesceSnapshot,
    registry: ServiceRegistry,
    message: str | None = None,
) -> JSONResponse:
    """Emit the one quiesce envelope, on the achieved and failed exits alike.

    Every exit carries the same ``ok``/``status``/``quiesce`` shape so an
    adapter branches on ``ok`` alone.  A failure adds ``error`` and
    ``message``: the operator asked for a state change and did not get it,
    and the reason is the whole content of that answer.  The daemon answered
    in every one of these cases, so the transport status stays 200 and the
    achieved/failed distinction lives in the body - a broker pausing
    speculatively must be able to tell a refused lifecycle request from a
    gateway that never reached the service.

    Ownership is stamped here rather than at each caller because a transition
    result carries the controller's own snapshot, which cannot know who owns the
    hold it describes.  Stamping once at the single exit means a refusal that
    exists precisely to talk about ownership cannot report none.
    """
    snapshot = registry.published_quiesce_snapshot(snapshot)
    log_event(
        logger,
        "service.quiesce",
        status,
        fields={
            "state": snapshot.state.value,
            "safe_to_borrow_gpu": snapshot.safe_to_borrow_gpu,
        },
    )
    payload: dict[str, object] = {
        "ok": achieved,
        "status": status,
        "quiesce": snapshot.as_envelope(),
    }
    if not achieved:
        payload["error"] = status
        payload["message"] = (
            message
            if message is not None
            else _quiesce_reason(
                status,
                snapshot,
            )
        )
        payload["retryable"] = True
    return JSONResponse(payload)


#: One sentence per borrower refusal, keyed by its structured code.  The code
#: names the condition for a machine; these say what happened and what the
#: caller may do next, which is the part an operator needs.  None of them names
#: a capability, a PID, or any other holder identity.
_BORROWER_REFUSAL_MESSAGES: Final = {
    "invalid_borrower_capability": (
        "The request body did not carry a single well-formed borrower "
        "capability, so it was not treated as a borrower request."
    ),
    "borrower_lease_not_held": (
        "No live borrower lease matches this capability, so borrower "
        "coordination cannot be established. Acquire the lease first."
    ),
    "borrower_capability_invalid": (
        "The supplied borrower capability does not match the live lease."
    ),
    "borrower_lease_unavailable": (
        "The borrower lease could not be verified, so this request was refused "
        "rather than assumed safe. Retry once the lease is observable."
    ),
    "borrower_lease_required": (
        "This pause is held by a GPU borrower and only that borrower can "
        "release it. It clears on its own when the borrower finishes or exits; "
        "no operator command ends it sooner."
    ),
    "borrower_lease_mismatch": (
        "A different borrower already holds this pause, so this capability "
        "cannot act on it."
    ),
    "borrower_pause_not_owned": (
        "The service was already paused by someone else when this borrower "
        "asked to pause it, so borrower ownership was not granted and the GPU "
        "must not be used. Wait for that pause to be released, then retry."
    ),
}


def _borrower_refusal_message(code: str) -> str:
    """Return the operator-facing sentence for one borrower refusal code."""
    return _BORROWER_REFUSAL_MESSAGES.get(
        code,
        f"The borrower lifecycle request was refused: {code}.",
    )


#: How long the pause route waits for compute admitted before the pause to
#: finish. Sized to sit inside the caller's shipped 30-second admin budget with
#: room for the rest of the request, so a drain that does not finish still
#: comes back as a refusal the operator can read, rather than as a client-side
#: timeout carrying no envelope and no remedy. Not derived from that budget:
#: it is the shipped default rather than the effective one, so an install that
#: lowers it would not be tracked anyway.
#:
#: It was five seconds, shorter than one encode slice under load. A pause of a
#: busy service therefore failed by construction, leaving admission closed each
#: time, and succeeded only on a retry that happened to arrive after the work
#: had drained on its own.
#: Read from the settings defaults rather than restated here, so the shipped
#: value has one home and the operator override below cannot drift from it.
_PAUSE_DRAIN_TIMEOUT_SECONDS: Final[float] = float(
    cast("float", rag_default("service_pause_drain_timeout_seconds"))
)


def _pause_drain_timeout() -> float:
    """Return the effective pause-drain bound for this call.

    Read per request rather than frozen at import, because what has to drain
    is the operator's own workload: a service running long indexing jobs needs
    a longer drain than one serving searches, and the two are the same binary.
    An unusable override degrades to the shipped default with a warning rather
    than raising, on the same terms as every other bound this client resolves -
    an operator typo must not turn a lifecycle call into a crash.
    """
    return resolve_timeout(
        None,
        setting="service_pause_drain_timeout_seconds",
        label="pause drain",
        default=_PAUSE_DRAIN_TIMEOUT_SECONDS,
    )


def _quiesce_reason(status: str, snapshot: QuiesceSnapshot) -> str:
    """Describe an unachieved transition from the controller's own evidence.

    An unachieved transition can leave admission closed, and that is the part
    an operator has to act on: the service then refuses every search and index
    update, and nothing reopens it on its own, because the transition is owned
    by the caller that started it. Reporting only which transition failed left
    a service silently serving nothing while its status said the pause had
    merely timed out.
    """
    failure_reason = snapshot.failure_reason
    detail = "" if failure_reason is None else f": {failure_reason}"
    outcome = (
        f"Quiesce transition {status!r} left the service in "
        f"{snapshot.state.value!r}{detail}."
    )
    if snapshot.admissions_open:
        return outcome
    return (
        f"{outcome} Admission stays closed in this state, so searches and index "
        "updates are refused until the transition finishes; retry pause to "
        "complete it, or resume to release it."
    )


async def _borrower_capability_from_request(
    request: Request,
) -> tuple[str | None, str | None]:
    """Read the optional single borrower capability without logging it."""
    body = await request.body()
    if not body:
        return (None, None)
    try:
        parsed: object = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return (None, "invalid_borrower_capability")
    if not _is_json_object(parsed):
        return (None, "invalid_borrower_capability")
    if not parsed:
        return (None, None)
    capability = _single_borrower_capability(parsed)
    if capability is not None:
        return (capability, None)
    return (None, "invalid_borrower_capability")


def _single_borrower_capability(payload: dict[str, object]) -> str | None:
    """Return the one structurally valid borrower capability from a body."""
    match payload:
        case {"borrower_capability": str() as capability} if len(payload) == 1:
            return capability if is_borrower_capability(capability) else None
        case _:
            return None


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow a decoded JSON value to the object surface this route reads."""
    return isinstance(value, dict)


async def _borrower_lifecycle_authorization(
    request: Request,
    registry: ServiceRegistry,
    *,
    pause: bool,
) -> tuple[str | None, JSONResponse | None]:
    """Return the parsed capability and any unchanged-state borrower refusal."""
    capability, capability_error = await _borrower_capability_from_request(request)
    if capability_error is not None:
        return (
            None,
            _quiesce_envelope(
                achieved=False,
                status=capability_error,
                snapshot=registry.quiesce_snapshot(),
                registry=registry,
                message=_borrower_refusal_message(capability_error),
            ),
        )
    lease_error = registry.validate_borrower_lifecycle_request(
        capability,
        pause=pause,
    )
    if lease_error is not None:
        return (
            None,
            _quiesce_envelope(
                achieved=False,
                status=lease_error,
                snapshot=registry.quiesce_snapshot(),
                registry=registry,
                message=_borrower_refusal_message(lease_error),
            ),
        )
    return (capability, None)


def _post_pause_binding_error(
    registry: ServiceRegistry,
    capability: str | None,
    transition: QuiesceTransition,
) -> str | None:
    """Bind a still-live borrower after safe quiescence, or name its refusal.

    Ownership follows the request that produced the state.  An already-quiesced
    outcome is an observation, not a pause: honouring it as a claim let a
    borrower inherit an operator's hold and leave that operator unable to
    release their own service for as long as the borrower ran.  A borrower
    repeating its own pause is the one case that still binds on an observation,
    because the binding it would be granted is the one it already holds, and
    refusing that would break retry after a lost response.
    """
    if capability is None or not transition.achieved:
        return None
    lease_error = registry.validate_borrower_lifecycle_request(capability, pause=True)
    if lease_error is not None:
        return lease_error
    if transition.snapshot.state is not QuiesceState.QUIESCED:
        return "borrower_lease_mismatch"
    if transition.code is QuiesceTransitionCode.ALREADY_QUIESCED and not (
        registry.borrower_capability_is_bound(capability)
    ):
        return "borrower_pause_not_owned"
    if not registry.bind_borrower_capability(capability):
        return "borrower_lease_mismatch"
    return None


async def _quiesce_route(request: Request, *, pause: bool) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    registry = get_request_runtime(request).registry
    capability, borrower_denied = await _borrower_lifecycle_authorization(
        request,
        registry,
        pause=pause,
    )
    if borrower_denied is not None:
        return borrower_denied
    try:
        if pause:
            transition = await _run_in_thread(
                partial(
                    registry.quiesce_resources,
                    timeout_seconds=_pause_drain_timeout(),
                ),
            )
        else:
            transition = await _run_in_thread(registry.resume_resources)
    except (
        ServiceQuiesceTransitionConflictError,
        ServiceQuiesceTransitionWaitTimeoutError,
    ) as exc:
        return _quiesce_envelope(
            achieved=False,
            status=exc.code,
            snapshot=exc.snapshot,
            registry=registry,
            message=str(exc),
        )
    except Exception as exc:
        return _quiesce_envelope(
            achieved=False,
            status="quiesce_transition_failed",
            snapshot=registry.quiesce_snapshot(),
            registry=registry,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    binding_error = _post_pause_binding_error(
        registry,
        capability if pause else None,
        transition,
    )
    if binding_error is not None:
        return _quiesce_envelope(
            achieved=False,
            status=binding_error,
            snapshot=transition.snapshot,
            registry=registry,
            message=_borrower_refusal_message(binding_error),
        )
    if not pause and capability is not None and transition.achieved:
        registry.clear_borrower_capability_after_resume(capability)
    return _quiesce_envelope(
        achieved=transition.achieved,
        status=transition.code.value,
        snapshot=transition.snapshot,
        registry=registry,
    )


async def pause_service_route(request: Request) -> JSONResponse:
    """Token-gated ``POST /pause`` holding the whole daemon at safe points.

    Idempotent: pausing an already-paused service reports
    ``already_paused`` with HTTP 200. Quiesce is a hold, never a stop -
    the daemon stays alive and ``POST /resume`` releases it.
    """
    return await _quiesce_route(request, pause=True)


async def resume_service_route(request: Request) -> JSONResponse:
    """Token-gated ``POST /resume`` releasing a held daemon.

    Idempotent: resuming an already-running service reports
    ``already_running`` with HTTP 200.
    """
    return await _quiesce_route(request, pause=False)
