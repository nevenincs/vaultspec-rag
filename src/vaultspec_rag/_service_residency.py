"""Pausing and resuming the registry's GPU residency.

The transition is owned by whoever started it: one caller drains compute,
detaches the model and reranker, and later rebuilds them, while every other
caller waits on the result rather than racing it. That ownership is the whole
subject here, which is why it is not spread through the registry that holds
the slots.
"""

from __future__ import annotations

import gc
import time
from typing import TYPE_CHECKING, Literal

from ._service_types import (
    GPURebuildEvidence,
    GPUReleaseEvidence,
    GPUResidencyRecipe,
    GPUResidencyTransitionError,
    ProjectSlot,
    QuiesceInvariantError,
    ResourceTransitionOperation,
    validate_resource_transition_timeout,
)
from .service_quiesce import (
    QuiesceSnapshot,
    QuiesceState,
    QuiesceTransition,
    QuiesceTransitionCode,
    ServiceQuiesceController,
    ServiceQuiesceTransitionConflictError,
    ServiceQuiesceTransitionWaitTimeoutError,
)

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from pathlib import Path

    from sentence_transformers import CrossEncoder

    from .embeddings import EmbeddingModel
    from .job_manager.manager import JobManager


class GPUResidencyMixin:
    """Drives the registry's pause, resume, and GPU residency lifecycle."""

    _gpu_lock: threading.Lock
    _gpu_residency_recipe: GPUResidencyRecipe | None
    _model: EmbeddingModel | None
    _reranker: CrossEncoder | None
    _lock: threading.RLock
    _quiesce_controller: ServiceQuiesceController
    _resource_transition: ResourceTransitionOperation | None
    _resource_transition_condition: threading.Condition
    _projects: dict[Path, ProjectSlot]

    if TYPE_CHECKING:
        # Provided by the registry this mixes into.
        def create_job_manager(self) -> JobManager: ...

        def _load_model(self, model_name: str | None = None) -> None: ...

        def _get_reranker(self) -> CrossEncoder: ...

    def quiesce_resources(self, *, timeout_seconds: float) -> QuiesceTransition:
        """Drain and detach GPU residency through the registry's one façade."""
        return self._run_resource_transition(
            direction="pause",
            timeout_seconds=timeout_seconds,
            run=lambda: self._quiesce_resources_once(timeout_seconds),
        )

    def _quiesce_resources_once(self, timeout_seconds: float) -> QuiesceTransition:
        """Perform the one pause owner's drain and residency-release effects."""
        started = self._quiesce_controller.begin_pause()
        if started.snapshot.state is QuiesceState.QUIESCED:
            return started
        if started.snapshot.state is not QuiesceState.PAUSING:
            return started
        self.create_job_manager().request_quiesce_attempts()
        drained = self._quiesce_controller.wait_for_drain(timeout_seconds)
        if not drained.achieved:
            return drained
        try:
            self._detach_gpu_dependencies(
                admission_epoch=drained.snapshot.admission_epoch,
            )
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.QUIESCE_FAILED,
                reason="gpu_dependency_release_failed",
            )
        return self._quiesce_controller.acknowledge_vram_released()

    def resume_resources(self, *, timeout_seconds: float = 5.0) -> QuiesceTransition:
        """Rebuild shared GPU residency before reopening compute admission.

        Resume is the single operator-facing way back to ``running``, from a
        completed quiesce and from a pause that failed alike.  An operator
        whose pause was stranded has no way to know which of the two they are
        looking at, so the verb - not the operator - picks the recovery.
        """
        return self._run_resource_transition(
            direction="resume",
            timeout_seconds=timeout_seconds,
            run=self._resume_resources_once,
        )

    def _resume_resources_once(self) -> QuiesceTransition:
        """Recover a failed pause or rebuild, prepare recovery, and reopen admission."""
        observed = self._quiesce_controller.snapshot()
        if observed.state is QuiesceState.PAUSING:
            return self._abort_pause_once(observed.admission_epoch)
        warming = self._quiesce_controller.begin_warming()
        if warming.snapshot.state is not QuiesceState.WARMING:
            return warming
        try:
            self._rebuild_gpu_dependencies(
                admission_epoch=warming.snapshot.admission_epoch,
            )
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.WARMUP_FAILED,
                reason="gpu_dependency_rebuild_failed",
            )
        from .job_manager.models import QuiescedResumeStatus

        manager = self.create_job_manager()
        prepared = manager.prepare_quiesced_resume()
        match prepared.status:
            case QuiescedResumeStatus.PREPARED | QuiescedResumeStatus.NO_WORK:
                pass
            case QuiescedResumeStatus.PERSISTENCE_UNPUBLISHED:
                return self._quiesce_controller.fail_transition(
                    code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
                    reason="job_resume_persistence_unpublished",
                )
            case QuiescedResumeStatus.PERSISTENCE_PUBLISHED_NOT_DURABLE:
                return self._quiesce_controller.fail_transition(
                    code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
                    reason="job_resume_persistence_published_not_durable",
                )
        completed = self._quiesce_controller.complete_warming()
        if completed.achieved and completed.snapshot.state is QuiesceState.RUNNING:
            manager.dispatch_prepared_quiesced_resume(prepared)
        return completed

    def _recover_already_running_resources(
        self,
        snapshot: QuiesceSnapshot,
    ) -> QuiesceTransition:
        """Reconcile retained durable work before reporting an idempotent resume."""
        self.create_job_manager().recover_running_quiesced_resume()
        return QuiesceTransition(
            code=QuiesceTransitionCode.RUNNING,
            achieved=True,
            snapshot=snapshot,
        )

    def _abort_pause_once(self, admission_epoch: int) -> QuiesceTransition:
        """Return a failed pause to running, rebuilding what it already released.

        A resume aimed at ``pausing`` is aimed at a pause that stopped without
        quiescing, so there is no ``warming`` to enter and no quiesced
        evidence to rebuild against.  Restoring residency first is what makes
        the reopening honest: the residency-release failure path detaches the
        shared model and reranker before it reports, so flipping admission
        open without rebuilding them would readmit compute against a stack
        that is no longer there.
        """
        try:
            self._restore_paused_gpu_dependencies(admission_epoch=admission_epoch)
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.QUIESCE_FAILED,
                reason="gpu_dependency_rebuild_failed",
            )
        aborted = self._quiesce_controller.abort_pause()
        if aborted.achieved and aborted.snapshot.state is QuiesceState.RUNNING:
            self.create_job_manager().recover_running_quiesced_resume()
        return aborted

    def _run_resource_transition(
        self,
        *,
        direction: Literal["pause", "resume"],
        timeout_seconds: float,
        run: Callable[[], QuiesceTransition],
    ) -> QuiesceTransition:
        """Claim or join one registry side-effect transition without lock nesting."""
        validate_resource_transition_timeout(timeout_seconds)
        conflict_direction: Literal["pause", "resume"] | None = None
        operation: ResourceTransitionOperation | None = None
        owner = False
        with self._resource_transition_condition:
            active = self._resource_transition
            if active is not None:
                if active.direction != direction:
                    conflict_direction = active.direction
                else:
                    operation = active
                    owner = False
            else:
                operation = ResourceTransitionOperation(direction=direction)
                self._resource_transition = operation
                owner = True
        if conflict_direction is not None:
            raise ServiceQuiesceTransitionConflictError(
                requested_direction=direction,
                active_direction=conflict_direction,
                snapshot=self._quiesce_controller.snapshot(),
            )
        if operation is None:
            raise RuntimeError("resource transition claim did not select an operation")
        if not owner:
            return self._wait_for_resource_transition(
                operation,
                direction=direction,
                timeout_seconds=timeout_seconds,
            )
        observed = self._quiesce_controller.snapshot()
        if direction == "pause" and observed.state is QuiesceState.QUIESCED:
            return self._complete_owned_resource_transition(
                operation,
                lambda: QuiesceTransition(
                    code=QuiesceTransitionCode.ALREADY_QUIESCED,
                    achieved=True,
                    snapshot=observed,
                ),
            )
        if direction == "resume" and observed.state is QuiesceState.RUNNING:
            return self._complete_owned_resource_transition(
                operation,
                lambda: self._recover_already_running_resources(observed),
            )
        return self._complete_owned_resource_transition(operation, run)

    def _wait_for_resource_transition(
        self,
        operation: ResourceTransitionOperation,
        *,
        direction: Literal["pause", "resume"],
        timeout_seconds: float,
    ) -> QuiesceTransition:
        """Wait boundedly for the owner without taking registry or GPU locks."""
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        with self._resource_transition_condition:
            while not operation.completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._resource_transition_condition.wait(
                    timeout=remaining
                ):
                    timed_out = not operation.completed
                    break
            if operation.completed:
                if operation.failure is not None:
                    raise operation.failure
                if operation.outcome is None:
                    raise RuntimeError("completed resource transition has no outcome")
                return operation.outcome
        if timed_out:
            raise ServiceQuiesceTransitionWaitTimeoutError(
                direction=direction,
                snapshot=self._quiesce_controller.snapshot(),
            )
        raise RuntimeError("resource transition waiter left without an outcome")

    def _complete_owned_resource_transition(
        self,
        operation: ResourceTransitionOperation,
        run: Callable[[], QuiesceTransition],
    ) -> QuiesceTransition:
        """Run owner effects once, then publish their exact terminal truth."""
        outcome: QuiesceTransition | None = None
        failure: BaseException | None = None
        try:
            outcome = run()
            return outcome
        except BaseException as exc:
            failure = exc
            raise
        finally:
            with self._resource_transition_condition:
                operation.outcome = outcome
                operation.failure = failure
                operation.completed = True
                if self._resource_transition is operation:
                    self._resource_transition = None
                self._resource_transition_condition.notify_all()

    def _detach_gpu_dependencies(
        self,
        *,
        admission_epoch: int,
    ) -> GPUReleaseEvidence:
        """Detach GPU objects only after the current epoch has fully drained."""
        snapshot = self._quiesce_controller.snapshot()
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.PAUSING,
            operation="detach",
        )
        with self._gpu_lock, self._lock:
            detached_slot_count = len(self._projects)
            model_detached = self._model is not None
            reranker_detached = self._reranker is not None
            recipe = self._gpu_residency_recipe
            self._gpu_residency_recipe = GPUResidencyRecipe(
                model_name=recipe.model_name if recipe is not None else None,
                restore_model=model_detached,
                restore_reranker=reranker_detached,
            )
            for slot in self._projects.values():
                slot.compute_runtime = None
            self._model = None
            self._reranker = None
        self._release_gpu_residency()
        return GPUReleaseEvidence(
            admission_epoch=admission_epoch,
            detached_slot_count=detached_slot_count,
            model_detached=model_detached,
            reranker_detached=reranker_detached,
        )

    def _rebuild_gpu_dependencies(
        self,
        *,
        admission_epoch: int,
    ) -> GPURebuildEvidence:
        """Rebuild shared dependencies while the controller keeps admission closed."""
        snapshot = self._quiesce_controller.snapshot()
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.WARMING,
            operation="rebuild",
        )
        return self._restore_gpu_residency(admission_epoch=admission_epoch)

    def _restore_paused_gpu_dependencies(self, *, admission_epoch: int) -> None:
        """Rebuild the residency a failed pause released, before it reopens.

        A pause that never got past its drain released nothing, so this must
        not reach for the GPU lock the unfinished slice is still holding -
        doing so would make the way out of a stranded pause wait on exactly
        the work that stranded it.  Only a pause that already detached
        residency has anything to rebuild, and detaching is reachable only
        from a drained closed epoch, so every restore that actually allocates
        is still guarded by the full drained-epoch invariant.
        """
        snapshot = self._quiesce_controller.snapshot()
        if (
            snapshot.state is not QuiesceState.PAUSING
            or snapshot.admission_epoch != admission_epoch
            or snapshot.admissions_open
        ):
            raise QuiesceInvariantError(
                "GPU restore requires the closed epoch its failed pause left behind"
            )
        if not self._gpu_residency_detached():
            return
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.PAUSING,
            operation="restore",
        )
        self._restore_gpu_residency(admission_epoch=admission_epoch)

    def _gpu_residency_detached(self) -> bool:
        """Report whether the recipe names residency the registry no longer holds."""
        with self._lock:
            recipe = self._gpu_residency_recipe
            if recipe is None:
                return False
            return (recipe.restore_model and self._model is None) or (
                recipe.restore_reranker and self._reranker is None
            )

    def _restore_gpu_residency(self, *, admission_epoch: int) -> GPURebuildEvidence:
        """Reconstruct the recipe's shared GPU stack, failing closed on any error."""
        recipe = self._gpu_residency_recipe
        try:
            with self._gpu_lock:
                if recipe is not None and recipe.restore_model:
                    self._load_model(recipe.model_name)
                    if recipe.restore_reranker:
                        self._get_reranker()
            with self._lock:
                lazy_slot_count = len(self._projects)
                model_rebuilt = self._model is not None
                reranker_rebuilt = self._reranker is not None
        except Exception as exc:
            self._clear_partial_gpu_dependencies()
            raise GPUResidencyTransitionError("GPU dependency rebuild failed") from exc
        return GPURebuildEvidence(
            admission_epoch=admission_epoch,
            model_rebuilt=model_rebuilt,
            reranker_rebuilt=reranker_rebuilt,
            lazy_slot_count=lazy_slot_count,
        )

    def _require_drained_closed_epoch(
        self,
        snapshot: QuiesceSnapshot,
        admission_epoch: int,
        *,
        expected_state: QuiesceState,
        operation: str,
    ) -> None:
        """Reject ``operation`` unless its own closed epoch has drained."""
        if (
            snapshot.state is not expected_state
            or snapshot.admission_epoch != admission_epoch
            or snapshot.admissions_open
            or snapshot.active_compute_tickets != 0
            or not snapshot.drain_complete
            or snapshot.drain_acknowledged_at is None
        ):
            raise QuiesceInvariantError(
                f"GPU {operation} requires a drained closed epoch"
            )

    def _release_gpu_residency(self) -> None:
        """Collect detached references and release allocator cache outside locks."""
        from .memory_probe import (
            rebase_resident_cuda_baseline,
            reset_cuda_peak_memory_stats,
        )

        try:
            gc.collect()
            reset_cuda_peak_memory_stats()
            rebase_resident_cuda_baseline()
        except Exception as exc:
            raise GPUResidencyTransitionError(
                "GPU dependency release cleanup failed"
            ) from exc

    def _clear_partial_gpu_dependencies(self) -> None:
        """Fail closed after rebuild failure while retaining the object-free recipe."""
        with self._gpu_lock, self._lock:
            for slot in self._projects.values():
                slot.compute_runtime = None
            self._model = None
            self._reranker = None
        self._release_gpu_residency()

    # -- per-project slots -------------------------------------------------
