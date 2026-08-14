"""``server reconcile``: wait for owner-published discovery to converge.

A thin adapter over the service-domain reconcile. It is deliberately
non-destructive: the singleton owner is the only process permitted to publish
or delete its discovery pointer, so the only correct repair is that owner's own
next heartbeat. This verb waits for it, bounded, and reports what it saw. It
never writes discovery, never deletes a record, and never stops or restarts a
process, which is what makes it safe to run against a healthy machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

from .._operator_commands import server_status_command
from ..serviceclient._discovery import resolve_machine_service
from ..serviceclient._status import (
    RECONCILE_INTERVAL_SECONDS,
    RECONCILE_TIMEOUT_SECONDS,
    ReconcileOutcome,
    reconcile_discovery,
)
from ..serviceclient._transport import _try_http_health
from ._app import JSON_OPTION_HELP, server_root_app
from ._progress import StartupStatusReporter
from ._render import _emit_json
from ._service_lifecycle import (
    _print_lifecycle_lines,
    _print_lifecycle_next_actions,
)
from ._status_render import _liveness_from_resolution

if TYPE_CHECKING:
    from ..serviceclient._status import DiscoveryStatus

__all__ = ["service_reconcile"]

_RECONCILE_COMMAND = "service.reconcile"


@server_root_app.command(
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
                f"{JSON_OPTION_HELP} Preserves exit "
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
    # The wait runs to tens of seconds against a machine that has not converged
    # yet, and every poll knows what it is still waiting for. The reporter turns
    # that into a visible tick; ``--json`` keeps it silent so the envelope below
    # is the only thing on stdout.
    with StartupStatusReporter(json_mode=json_mode) as progress:
        progress.announce("Waiting for service discovery to converge...")

        def _report(attempt: int, verdict: DiscoveryStatus) -> None:
            progress.heartbeat(
                f"Waiting for discovery: {verdict.label} (poll {attempt})"
            )

        from ..serviceclient._status import ReconcileRequest

        outcome = reconcile_discovery(
            ReconcileRequest(
                resolve=resolve_machine_service,
                probe_liveness=_liveness_from_resolution,
                probe_health=_try_http_health,
                timeout_s=max(0.0, timeout),
                interval_s=RECONCILE_INTERVAL_SECONDS,
                on_attempt=_report,
            )
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
            server_status_command(verbose=True),
            "vaultspec-rag server logs",
        )
