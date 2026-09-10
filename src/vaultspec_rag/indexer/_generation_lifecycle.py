"""Generation and ledger lifecycle for one code-indexing root.

Opening a generation, deciding whether resumed evidence still describes
anything, and publishing a finished one are the same authority: each answer
depends on what the ledger claims measured against what storage actually
holds. Holding them together is what lets an opened generation be retired and
reopened in one place, rather than a caller remembering to check first.

The lifecycle owns the open generation, so it also owns the drift owner bound
to it - superseding evidence is meaningless without a generation to supersede
it in, and binding the two at the same instant is why neither can outlive the
other.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._store_models import generation_code_collection, publish_generation_as_served
from ._content_policy import ContentKind
from ._drift_owner import CodeDriftOwner
from ._route_migration import (
    RouteScanOptions,
    purge_unpublished_rows,
    reconcile_generation_storage,
    reconcile_scoped_routes,
)
from ._run_checkpoint import CodeRunCheckpoint, CodeRunOpenRequest
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnitKind,
    FinalizationPhase,
    RunTerminalState,
)
from ._run_policy import RunPolicy

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_checkpoint import CodeRunConfiguration
    from ._run_ledger_models import RunAuthority, RunOperation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CodeGenerationBindings:
    root_dir: pathlib.Path
    data_root: pathlib.Path
    store: VaultStore
    publish_readiness: Callable[[pathlib.Path, str], object] | None = None


@dataclass(frozen=True, slots=True)
class CodeGenerationOpenRequest:
    """All compatibility inputs for opening one code generation.

    One grouped shape rather than a spread of keywords, so a field added
    here is declared once and every call site is re-checked against its
    real type.
    """

    policy: ResolvedIndexPolicy
    operation: RunOperation
    clean: bool
    configuration: CodeRunConfiguration
    dense_dimensions: int
    sparse_enabled: bool
    run_control: RunControl
    authority: RunAuthority


class CodeGenerationLifecycle:
    """Own one root's code generation, its ledger authority, and its drift."""

    __slots__ = (
        "_active_build_target",
        "_data_root",
        "_drift_owner",
        "_last_checkpoint",
        "_publish_readiness",
        "_root_dir",
        "_store",
    )

    def __init__(
        self,
        bindings: CodeGenerationBindings,
    ) -> None:
        """Bind the lifecycle to one root's ledger and storage.

        Args:
            root_dir: Project root the generation indexes.
            data_root: Directory holding this root's durable run ledger.
            store: Vector store the generation's evidence must describe.
        """
        self._root_dir = bindings.root_dir
        self._data_root = bindings.data_root
        self._store = bindings.store
        self._publish_readiness = bindings.publish_readiness
        self._last_checkpoint: CodeRunCheckpoint | None = None
        self._active_build_target: str | None = None
        # Bound to the generation once a run opens its checkpoint, because
        # superseding evidence is meaningless without one to supersede in.
        self._drift_owner: CodeDriftOwner | None = None

    @property
    def last_checkpoint(self) -> CodeRunCheckpoint | None:
        """Return the latest run authority for service-domain projection."""
        return self._last_checkpoint

    @property
    def drift_owner(self) -> CodeDriftOwner:
        """Return the open generation's drift owner.

        Reaching this before a checkpoint is open means a caller is trying to
        supersede evidence in a generation that does not exist yet.
        """
        owner = self._drift_owner
        if owner is None:
            raise RuntimeError("code drift ownership requires an open run checkpoint")
        return owner

    def drift_snapshot(self) -> dict[str, object] | None:
        """Return this run's drift telemetry, or ``None`` before a generation.

        Unlike :attr:`drift_owner` this tolerates the absence of a generation,
        because a result is assembled on paths that never opened one.
        """
        owner = self._drift_owner
        return owner.snapshot() if owner is not None else None

    @property
    def active_build_target(self) -> str | None:
        """Return the open generation's derived build collection."""
        return self._active_build_target

    def forget_open_generation(self) -> None:
        """Drop the drift owner so a new run cannot inherit the prior one."""
        self._drift_owner = None
        self._active_build_target = None

    def open_checkpoint(
        self, request: CodeGenerationOpenRequest, /
    ) -> CodeRunCheckpoint:
        """Open one compatible storage-confirmed code generation."""
        from ..config._settings import get_config

        config = get_config()
        model_identity = json.dumps(
            {
                "dense": str(config.embedding_model),
                "sparse": (
                    str(config.sparse_model) if request.sparse_enabled else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        def _open(spec: CodeGenerationOpenRequest) -> CodeRunCheckpoint:
            return CodeRunCheckpoint.open_generation(
                CodeRunOpenRequest(
                    data_root=self._data_root,
                    root_dir=self._root_dir,
                    policy=spec.policy,
                    run_policy=RunPolicy.from_config(run_control=spec.run_control),
                    operation=spec.operation,
                    clean=spec.clean,
                    model_identity=model_identity,
                    dense_dimensions=spec.dense_dimensions,
                    configuration=spec.configuration,
                    backend_identity=self._store.backend_identity,
                    authority=spec.authority,
                )
            )

        checkpoint = _open(request)
        if self.evidence_lost(checkpoint):
            logger.warning(
                "code collection is missing from storage but the run ledger "
                "claims storage-confirmed progress; retiring generation %s "
                "and re-encoding from scratch",
                checkpoint.generation_id,
            )
            checkpoint.ledger.finish_generation(
                checkpoint.generation_id,
                RunTerminalState.INVALIDATED,
                detail=(
                    "code collection is missing from storage; the "
                    "storage-confirmed evidence no longer describes anything"
                ),
            )
            checkpoint = _open(request)
        self._last_checkpoint = checkpoint
        self._active_build_target = self.build_collection(checkpoint)
        self._drift_owner = CodeDriftOwner(
            checkpoint,
            self._store,
            collection=self._active_build_target,
        )
        return checkpoint

    def evidence_lost(self, checkpoint: CodeRunCheckpoint) -> bool:
        """Return whether resumed storage-confirmed evidence points at nothing.

        External destruction (a storage delete) drops the code collection but
        leaves the per-root run ledger behind. Resuming such a generation
        would skip its committed units with zero encoding and publish an
        index whose committed portion no longer exists anywhere, so a
        generation carrying commit evidence for an absent collection must be
        retired rather than resumed.
        """
        has_evidence = (
            checkpoint.ingestion_complete
            or checkpoint.ledger.committed_unit_count(checkpoint.generation_id) > 0
        )
        return has_evidence and not self._store.code_collection_exists(
            self.build_collection(checkpoint)
        )

    def published_evidence_lost(self) -> bool:
        """Return whether canonical code proof is absent or storage is short."""
        from .._publication_state import acquire_publication_snapshot
        from .._source_types import PublicSourceType
        from ._publication_proof import ProofMissingError

        try:
            snapshot = acquire_publication_snapshot(
                self._root_dir,
                PublicSourceType.CODE,
            )
        except ProofMissingError:
            return True
        if not self._store.code_collection_exists():
            return True
        live = self._store.count_code()
        snapshot.validate()
        claimed = snapshot.proof.aggregate.retained_points
        if live >= claimed:
            return False
        logger.warning(
            "Code collection holds %d of the %d points its canonical proof "
            "describes; an explicit rebuild is required",
            live,
            claimed,
        )
        return True

    def build_collection(self, checkpoint: CodeRunCheckpoint) -> str | None:
        """Return the collection *checkpoint* populates, or ``None`` for in-place.

        A generation opened ``clean`` builds beside the served collection under
        a name minted from this root's DERIVED name and its own identifier, so
        the name is a pure function of two things a resuming run still has.
        Every other generation writes into the served collection and has no
        build target at all.

        Deriving it here rather than remembering it is what lets a run that
        died before publication finish the generation it left behind: the
        derived name is a function of the root alone, so the same input yields
        the same name no matter what the pointer did meanwhile.

        Minting from the derived name rather than the served one is what keeps
        the name bounded. Publication makes the new collection the served one,
        so a served-derived name accumulates one suffix per clean generation
        and grows without limit - collections whose names carry a dozen
        generations of history, each rebuild widening the next.
        """
        if not checkpoint.generation.signature.clean:
            return None
        return generation_code_collection(
            self._store.DERIVED_CODE_TABLE_NAME,
            checkpoint.generation_id,
        )

    def publish(
        self,
        checkpoint: CodeRunCheckpoint,
        *,
        build_target: str | None,
        reporter: ProgressReporter,
        phase_label: str,
        affected_paths: set[str] | None = None,
    ) -> None:
        """Publish one finished code generation, breadth first and pointer second.

        The single publication for every code run - a rebuild into a
        generation collection, an in-place incremental, and a run resuming a
        generation whose ingestion already finished. A second copy of this is
        what let a resumed publication count one collection while claiming
        another, so the ordering, the counted target, and the pointer move all
        live here and nowhere else.

        ``build_target`` is the collection the generation actually populated.
        BOTH published figures are counted from it, never from whatever the
        served pointer currently resolves to: a claim measured against a
        different collection than the one it describes is not a claim about
        anything.

        The pointer moves only after the breadth of that same collection is on
        disk, and the store is rebound to it in the same step, so no reader can
        resolve a generation whose published figure is missing and no later run
        inherits a served name the publication never certified.
        """
        reporter.phase_start(phase_label, 1)
        try:
            policy = checkpoint.policy
            if policy is None:
                raise RuntimeError("code checkpoint has no resolved policy")

            def _record_breadth() -> None:
                checkpoint.publish_proof_transition()

            if build_target is None:
                if affected_paths is None:
                    reconcile_generation_storage(
                        self._store,
                        checkpoint,
                        policy,
                        ContentKind.CODE,
                    )
                else:
                    reconcile_scoped_routes(
                        self._store,
                        checkpoint,
                        ContentKind.CODE,
                        affected_paths,
                    )
                _record_breadth()
            else:
                # The complete replacement remains private until its own
                # stale rows are gone and its breadth has been recorded. This
                # explicit collection keeps that mutation out of the old
                # served generation while making the published count exact.
                purge_unpublished_rows(
                    self._store,
                    checkpoint,
                    policy,
                    ContentKind.CODE,
                    options=RouteScanOptions(code_collection=build_target),
                )
                # Breadth first, pointer second - a reader must never resolve a
                # generation whose published figure is missing.
                publish_generation_as_served(
                    self._root_dir,
                    collection=build_target,
                    record_breadth=_record_breadth,
                )
                # Both collections are complete at this instant: the old one
                # served throughout and the new one has just reconciled. A
                # reader mid-flight sees one or the other, never a partial
                # index, which is what makes this assignment the swap rather
                # than a race.
                self._store.CODE_TABLE_NAME = build_target
                # Route reconciliation evaluates destination evidence and
                # deletes code points through the store's selected collection.
                # It therefore cannot run while that selection still names the
                # old served generation: its completed replacement is now
                # published and bound, so every code operation names the build
                # collection that this checkpoint actually populated.
                reconcile_generation_storage(
                    self._store,
                    checkpoint,
                    policy,
                    ContentKind.CODE,
                    include_same_kind=False,
                )
            published = checkpoint.publish_generation()
            if self._publish_readiness is not None:
                self._publish_readiness(self._root_dir, published.generation_id)
            reporter.advance(1)
        finally:
            reporter.phase_end()

    def publish_pending_finalization(
        self,
        checkpoint: CodeRunCheckpoint,
        *,
        reporter: ProgressReporter,
    ) -> bool:
        """Finish an ingestion-complete generation without re-entering writes.

        A generation that built beside the served collection is publishable
        only while that collection is still there. Absent, it has nothing left
        to publish - certifying it anyway would stamp its identifier over
        whatever the served pointer happens to name and claim breadth measured
        from a collection the generation never wrote - so it is retired and the
        caller re-encodes from scratch.

        Returns:
            ``True`` when the generation was published, ``False`` when it is
            still ingesting or was retired, and the caller must run the
            ordinary path.
        """
        if checkpoint.generation.finalization_phase is FinalizationPhase.INGESTING:
            return False
        build_target = self.build_collection(checkpoint)
        if build_target is not None and not self._store.code_collection_exists(
            build_target
        ):
            logger.warning(
                "generation %s finished ingesting into a collection that is no "
                "longer in storage; retiring it rather than publishing a claim "
                "over an index that does not exist",
                checkpoint.generation_id,
            )
            checkpoint.ledger.finish_generation(
                checkpoint.generation_id,
                RunTerminalState.INVALIDATED,
                detail=(
                    "the generation's own code collection is missing from "
                    "storage; its finished ingestion no longer describes "
                    "anything to publish"
                ),
            )
            return False
        self.publish(
            checkpoint,
            build_target=build_target,
            reporter=reporter,
            phase_label="resume publication",
        )
        return True

    @staticmethod
    def checkpoint_content_hash(content_hash: str) -> str | None:
        """Return a content hash only when it has the checkpoint wire shape."""
        if len(content_hash) == 128 and all(
            char in "0123456789abcdef" for char in content_hash
        ):
            return content_hash
        return None

    @staticmethod
    def checkpoint_ids_by_path(
        checkpoint: CodeRunCheckpoint,
        rel_paths: set[str],
        *,
        retained: bool,
    ) -> dict[str, set[str]]:
        """Return bounded deterministic point evidence grouped by path."""
        result: dict[str, set[str]] = {rel: set() for rel in rel_paths}
        if retained:
            from ._run_ledger_publication import compatibility_for_signature

            key = (
                checkpoint.receipt.compatibility_key
                if checkpoint.receipt is not None
                else compatibility_for_signature(checkpoint.generation.signature)
            )
            ordered = tuple(sorted(rel_paths))
            for start in range(0, len(ordered), FETCH_BATCH):
                evidence = checkpoint.ledger.publication_evidence_for_paths(
                    key,
                    ordered[start : start + FETCH_BATCH],
                )
                for rel, item in evidence.items():
                    result[rel].update(item.point_ids)
            return result
        for unit in checkpoint.ledger.iter_units(checkpoint.generation_id):
            if unit.kind is CommitUnitKind.UPSERT and unit.rel_path in result:
                result[unit.rel_path].update(unit.point_ids)
        return result
