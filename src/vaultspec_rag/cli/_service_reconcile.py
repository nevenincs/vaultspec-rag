"""``server reconcile``: wait for owner-published discovery to converge.

A thin adapter over the service-domain reconcile. It is deliberately
non-destructive: the singleton owner is the only process permitted to publish
or delete its discovery pointer, so the only correct repair is that owner's own
next heartbeat. This verb waits for it, bounded, and reports what it saw. It
never writes discovery, never deletes a record, and never stops or restarts a
process, which is what makes it safe to run against a healthy machine.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..serviceclient._discovery import resolve_machine_service
from ..serviceclient._status import (
    RECONCILE_INTERVAL_SECONDS,
    RECONCILE_TIMEOUT_SECONDS,
    ReconcileOutcome,
    reconcile_discovery,
)
from ._app import server_app
from ._http_search import _try_http_health
from ._render import _emit_json
from ._service_lifecycle import (
    _print_lifecycle_lines,
    _print_lifecycle_next_actions,
)
from ._status_render import _liveness_from_resolution

__all__ = ["service_reconcile"]

_RECONCILE_COMMAND = "service.reconcile"


@server_app.command(
    "reconcile",
    help=(
        "Wait for the running service to republish its discovery records. "
        "Non-destructive: nothing is written, deleted, stopped, or restarted. "
        "Exits 0 once discovery agrees, 1 if it does not converge in time."
    ),
)
def service_reconcile(
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            help="Seconds to wait for convergence before reporting unresolved.",
        ),
    ] = RECONCILE_TIMEOUT_SECONDS,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit JSON for scripts instead of human text. Preserves exit "
                "codes 0 (converged) and 1 (not converged)."
            ),
        ),
    ] = False,
) -> None:
    """Poll typed discovery until the owner's publication is trustworthy.

    Idempotent: running it against an already-agreeing machine reports
    ``already_converged`` and exits 0, so a supervising caller can invoke it
    speculatively without having to test first.
    """
    outcome = reconcile_discovery(
        resolve_machine_service,
        _liveness_from_resolution,
        _try_http_health,
        timeout_s=max(0.0, timeout),
        interval_s=RECONCILE_INTERVAL_SECONDS,
    )
    if json_mode:
        _emit_json(
            outcome.converged,
            _RECONCILE_COMMAND,
            data=outcome.as_dict(),
            **(
                {}
                if outcome.converged
                else {"error": outcome.status, "message": outcome.detail}
            ),
        )
    else:
        _render_human(outcome)
    if not outcome.converged:
        raise typer.Exit(code=1)


def _render_human(outcome: ReconcileOutcome) -> None:
    """Render the outcome plus the discovery evidence behind it."""
    _print_lifecycle_lines(
        "Service discovery reconcile",
        f"Result: {outcome.status}",
        f"Detail: {outcome.detail}",
        f"Evidence: {outcome.final.resolution.evidence()}",
        f"Attempts: {outcome.attempts} over {outcome.elapsed_s:.1f}s",
    )
    if not outcome.converged:
        _print_lifecycle_next_actions(
            "vaultspec-rag server status --verbose",
            "vaultspec-rag server logs",
        )
