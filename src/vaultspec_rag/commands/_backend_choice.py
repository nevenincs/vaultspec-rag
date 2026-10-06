"""Saving the backend an ``install`` run chose, for a later ``server start``.

A start with no backend flag reads the choice saved here, so what is written
has to be a choice somebody made: an explicit ``--local-only``, or a run that
provisioned for server mode and finished. Anything else leaves the record
alone and says why.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..operator_state._service_environment import ServiceEnvironment
    from ._models import InstallReport
    from ._provision import ProvisionOutcome, SavedBackend

__all__ = ["save_backend_choice"]

logger = logging.getLogger(__name__)


class _Run(Protocol):
    """What one install run asked for, as far as the backend choice goes."""

    @property
    def report(self) -> InstallReport: ...
    @property
    def dry_run(self) -> bool: ...
    @property
    def host(self) -> bool: ...
    @property
    def local_only(self) -> bool: ...


def _persist_runtime_selection(report: InstallReport, local_only: bool) -> bool:
    """Write the local-only runtime marker, degrading to a warning on error.

    A persisted runtime hint must never crash setup, so an OSError on the
    write is logged and surfaced as a recoverable warning naming the
    runtime escape hatches, rather than raised.

    Returns:
        Whether the marker was written.
    """
    from ..config._paths import persist_local_only

    try:
        persist_local_only(local_only)
    except OSError as exc:
        logger.error("failed to persist local-only selection: %s", exc)
        report.warnings.append(
            f"could not persist the local-only selection: {exc}; "
            f"pass --local-only on `server start` or set "
            f"VAULTSPEC_RAG_LOCAL_ONLY to select the local backend."
        )
        return False
    return True


def _plain_start_backend() -> str:
    """Say which backend a ``server start`` with no flags would select now.

    Asked of the decision a start itself makes, after anything this run saved,
    so the sentence cannot describe a start other than the one that would
    happen.
    """
    from ._provision import decide_backend

    unneeded = decide_backend(local_only=False).server_unneeded
    if unneeded is None:
        return "A plain `vaultspec-rag server start` runs the managed Qdrant server."
    return f"A plain `vaultspec-rag server start` runs no Qdrant server: {unneeded}."


def save_backend_choice(
    run: _Run,
    outcome: ProvisionOutcome,
    environment: ServiceEnvironment,
) -> SavedBackend:
    """Save the backend choice this run is entitled to save, and say what it did.

    Two different things reach here and they are not treated alike. An
    explicit ``--local-only`` is the operator naming the backend, and is saved
    for any host installation, whether or not its accelerator stack is usable
    yet and whatever happened to the fetches: the usual project flow is this
    command, then a sync, then a plain start, and that start must not download
    a server the operator already declined. The absence of the flag names
    nothing. It is recorded as server mode only when this environment can run
    the service and nothing failed, because a run that could not provision has
    not chosen server mode and must not leave a record saying it did.

    A client never writes the choice: it is read by the host installation's
    start, and a client writing it would override the host's. A preview
    writes nothing.
    """
    from ._provision import SavedBackend

    if run.dry_run:
        reason = "not saved: this run is a preview."
    elif not run.host:
        return SavedBackend(
            saved=False,
            local_only=None,
            detail="not saved: a client installation does not choose the "
            "backend of the service; the host installation that runs it does.",
        )
    elif run.local_only:
        if _persist_runtime_selection(run.report, True):
            return SavedBackend(
                saved=True,
                local_only=True,
                detail=f"saved: local-only. {_plain_start_backend()}",
            )
        reason = "not saved: the choice could not be written (see the warning)."
    elif not environment.can_run_service:
        reason = (
            "not saved: this environment cannot run the service yet "
            f"({environment.reason}), so no backend was chosen for it."
        )
    elif not outcome.ok:
        reason = (
            "not saved: provisioning did not finish, so server mode was not "
            "recorded as chosen."
        )
    elif _persist_runtime_selection(run.report, False):
        return SavedBackend(
            saved=True,
            local_only=False,
            detail=f"saved: server mode. {_plain_start_backend()}",
        )
    else:
        reason = "not saved: the choice could not be written (see the warning)."
    return SavedBackend(
        saved=False, local_only=None, detail=f"{reason} {_plain_start_backend()}"
    )
