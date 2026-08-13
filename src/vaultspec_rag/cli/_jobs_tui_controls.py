"""Issuing a control against one job, and settling the row that asked for it.

Every control goes out through the same typed transport the singular job verbs
use, carrying the same expected-revision guard, and comes back to the row that
requested it - including a refusal. That round trip is a concern of its own:
nothing here renders a header, reads a payload, or decides a layout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work

from ..serviceclient._transport import (
    _try_http_delete_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._jobs_tui_cells import Pending, capability_flag, job_id_of
from ._jobs_tui_constants import CONTROL_GROUP, STATE_ACTIONS
from ._jobs_tui_payload import action_capability, is_gone
from ._service_jobs_query import job_revision

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..job_models import DesiredJobState
    from ._jobs_tui_state import LaneStamps

if TYPE_CHECKING:
    from textual.app import App

    _MixinBase = App[None]
else:
    _MixinBase = object


class JobControlMixin(_MixinBase):
    """Sends one job control and reconciles the row it was issued from."""

    _job_stamps: LaneStamps
    _last_outcome: tuple[str, str] | None
    _pending: dict[str, Pending]
    _port: int

    if TYPE_CHECKING:
        # Provided by the application this mixes into.
        def selected_job(self) -> dict[str, object] | None: ...

        def _refusal(self, action: str) -> str: ...

        def _job_action_context_available(self) -> bool: ...

        def _render_rows(self) -> None: ...

        def refresh_jobs(self) -> None: ...

    def action_job_pause(self) -> None:
        self._request_state("pause")

    def action_job_resume(self) -> None:
        self._request_state("resume")

    def action_job_stop(self) -> None:
        self._request_state("stop")

    def _request_state(self, action: str) -> None:
        job = self._actionable(action)
        if job is None:
            return
        revision = job_revision(job)
        if revision is None:
            self.notify("The service reported no revision for this job.")
            return
        flag, desired = STATE_ACTIONS[action]
        del flag
        self._mark_pending(job, action, expected=desired.value)
        self._send_state(job_id_of(job), desired, revision, action)

    @work(thread=True, group=CONTROL_GROUP)
    def _send_state(
        self,
        job_id: str,
        desired: DesiredJobState,
        revision: int,
        action: str,
    ) -> None:
        result = _try_http_set_job_desired_state(
            job_id,
            desired,
            self._port,
            expected_revision=revision,
            mode="graceful",
        )
        self.call_from_thread(self._after_control, job_id, action, result)

    def action_job_retry(self) -> None:
        self._request_send("retry", self._send_retry)

    @work(thread=True, group=CONTROL_GROUP)
    def _send_retry(self, job_id: str) -> None:
        result = _try_http_retry_job(
            job_id,
            self._port,
            initiator_kind="cli",
            command="server_job_retry",
        )
        self.call_from_thread(self._after_control, job_id, "retry", result)

    def action_job_delete(self) -> None:
        self._request_send("delete", self._send_delete)

    @work(thread=True, group=CONTROL_GROUP)
    def _send_delete(self, job_id: str) -> None:
        result = _try_http_delete_job(job_id, self._port)
        self.call_from_thread(self._after_control, job_id, "delete", result)

    def _request_send(self, action: str, send: Callable[[str], object]) -> None:
        """Mark the selected job pending for *action*, then hand it to *send*.

        The state transitions go through ``_request_state`` instead: they carry
        a revision and an expected state, which this shape has no place for.
        """
        job = self._actionable(action)
        if job is not None:
            self._mark_pending(job, action)
            send(job_id_of(job))

    def _actionable(self, action: str) -> dict[str, object] | None:
        """Return the selected job when it permits *action*, else ``None``.

        The footer already greys a disallowed key, but a binding can still
        fire; this is the check that makes the refusal real rather than
        cosmetic, so no request is sent for a capability the service denies.

        The refusal is reported here as well as at the key, because this is the
        gate an action reaching the method by any other route still meets - and
        a refused request that says nothing is indistinguishable from one that
        was sent and lost.
        """
        flag = action_capability(f"job_{action}")
        if not self._job_action_context_available():
            self.notify(self._refusal(f"job_{action}"), severity="warning")
            return None
        job = self.selected_job()
        if job is None or flag is None or not capability_flag(job, flag):
            self.notify(self._refusal(f"job_{action}"), severity="warning")
            return None
        return job

    def _mark_pending(
        self,
        job: dict[str, object],
        action: str,
        expected: str | None = None,
    ) -> None:
        """Put the request on the row before it leaves the interface.

        The row changes on the keystroke, not on the answer. The gap between
        the two is the whole window in which an operator decides whether
        anything is wired up at all.
        """
        self._pending[job_id_of(job)] = Pending(
            action, expected, "requested", "", self._job_stamps.issued
        )
        self._render_rows()

    def _after_control(
        self,
        job_id: str,
        action: str,
        result: dict[str, object] | None,
    ) -> None:
        short = job_id[:8] or "job"
        if result is None:
            self._settle(
                job_id, "refused", f"{action} failed: the service is not reachable."
            )
        elif is_gone(result):
            # Not a generic failure: the view was addressing a job the service
            # has dropped. The answer is a corrected list and a plain sentence,
            # never a raw error.
            self._settle(
                job_id,
                "gone",
                f"{action}: {short} is no longer on the service - list refreshed.",
            )
        elif result.get("ok") is not True:
            message = result.get("message")
            self._settle(
                job_id,
                "refused",
                f"{action} refused: {message}"
                if isinstance(message, str)
                else f"{action} was refused by the service.",
            )
        else:
            # Accepted is not yet done. The row keeps saying so until the
            # service's own payload carries the transition, because a control
            # that reports success and leaves the row unchanged is exactly what
            # reads as nothing having been wired up.
            self._settle(
                job_id, "sent", f"{action} accepted for {short}; awaiting the service."
            )
        self._render_rows()
        self.refresh_jobs()

    def _settle(self, job_id: str, outcome: str, detail: str) -> None:
        """Record where a control got to, on the row and in the header."""
        marker = self._pending.get(job_id)
        self._pending[job_id] = Pending(
            marker.action if marker is not None else "control",
            marker.expected if marker is not None else None,
            outcome,
            detail,
            # Only a fetch issued after this point can carry the mutation, and
            # ``refresh_jobs`` below takes the next stamp.
            self._job_stamps.issued,
        )
        failed = outcome in {"refused", "gone"}
        # The tone token, not a resolved style: the outcome outlives theme
        # flips, so its colour is resolved at each render, never stored.
        self._last_outcome = (detail, "bad" if failed else "good")
        self.notify(detail, severity="error" if failed else "information")
