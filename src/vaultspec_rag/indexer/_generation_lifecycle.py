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
from typing import TYPE_CHECKING

from .._index_breadth import PUBLISHED_POINTS_KEY, parse_reserved_count
from ._content_policy import ContentKind
from ._drift_owner import CodeDriftOwner
from ._route_migration import reconcile_generation_storage
from ._run_checkpoint import CodeRunCheckpoint
from ._run_ledger import (
    CommitUnitKind,
    FinalizationPhase,
    RunTerminalState,
)
from ._run_policy import RunPolicy

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Mapping

    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store import VaultStore
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_checkpoint import CodeRunConfiguration
    from ._run_ledger import RunOperation

logger = logging.getLogger(__name__)


class CodeGenerationLifecycle:
    """Own one root's code generation, its ledger authority, and its drift."""

    __slots__ = (
        "_data_root",
        "_drift_owner",
        "_last_checkpoint",
        "_load_meta",
        "_meta_path",
        "_read_meta_raw",
        "_root_dir",
        "_store",
    )

    def __init__(
        self,
        root_dir: pathlib.Path,
        *,
        data_root: pathlib.Path,
        meta_path: pathlib.Path,
        store: VaultStore,
        load_meta: Callable[[], Mapping[str, str]],
        read_meta_raw: Callable[[], Mapping[str, str]],
    ) -> None:
        """Bind the lifecycle to one root's ledger, storage, and metadata.

        Args:
            root_dir: Project root the generation indexes.
            data_root: Directory holding this root's durable run ledger.
            meta_path: Carried code-index metadata sidecar.
            store: Vector store the generation's evidence must describe.
            load_meta: Reader for the parsed sidecar, called at each use.
            read_meta_raw: Reader for the unparsed sidecar, called at each use.
        """
        self._root_dir = root_dir
        self._data_root = data_root
        self._meta_path = meta_path
        self._store = store
        self._load_meta = load_meta
        self._read_meta_raw = read_meta_raw
        self._last_checkpoint: CodeRunCheckpoint | None = None
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

    def forget_open_generation(self) -> None:
        """Drop the drift owner so a new run cannot inherit the prior one."""
        self._drift_owner = None

    def open_checkpoint(
        self,
        *,
        policy: ResolvedIndexPolicy,
        operation: RunOperation,
        clean: bool,
        configuration: CodeRunConfiguration,
        dense_dimensions: int,
        sparse_enabled: bool,
        run_control: RunControl,
    ) -> CodeRunCheckpoint:
        """Open one compatible storage-confirmed code generation."""
        from ..config import get_config

        config = get_config()
        model_identity = json.dumps(
            {
                "dense": str(config.embedding_model),
                "sparse": (str(config.sparse_model) if sparse_enabled else None),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        def _open() -> CodeRunCheckpoint:
            return CodeRunCheckpoint.open(
                data_root=self._data_root,
                root_dir=self._root_dir,
                policy=policy,
                run_policy=RunPolicy.from_config(run_control=run_control),
                operation=operation,
                clean=clean,
                model_identity=model_identity,
                dense_dimensions=dense_dimensions,
                configuration=configuration,
            )

        checkpoint = _open()
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
            checkpoint = _open()
        self._last_checkpoint = checkpoint
        self._drift_owner = CodeDriftOwner(checkpoint, self._store)
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
        return has_evidence and not self._store.code_collection_exists()

    def published_evidence_lost(self) -> bool:
        """Return whether the store fails to back the carried incremental evidence.

        Carried metadata and the run ledger outlive the points they describe.
        Destruction drops the collection or part of it and leaves the sidecar
        behind; an incremental diff against that metadata then classifies every
        surviving file as unchanged, skips all encoding, and publishes a
        "successful" result over points that are no longer there. Such evidence
        must escalate to full failure-safe reconciliation instead of being
        trusted.

        Destruction is rarely total. A clean rebuild drops the collection and
        then repopulates it incrementally, so an interrupted one leaves a
        fragment - present, non-empty, and describing itself as whole. Asking
        only whether the collection exists therefore misses the common case,
        which is why the point count published alongside the sidecar is compared
        as well: it is the only record of how much breadth the metadata claims.

        A shortfall is any deficit. Publication happens after storage
        reconciliation at every call site, so a complete index reads back
        exactly what it published, and a legitimate shrink travels the
        incremental path and republishes. Escalation is failure-safe and
        republishes the count, so even a spurious one self-corrects on the next
        run rather than latching.

        A sidecar with no published count, or a store that cannot be counted,
        yields "cannot tell" and keeps the existence-only behaviour: neither is
        evidence of loss, and escalating on ignorance would rebuild every root
        written by an older build.
        """
        if not self._load_meta():
            return False
        if not self._store.code_collection_exists():
            return True
        claimed = parse_reserved_count(self._read_meta_raw(), PUBLISHED_POINTS_KEY)
        if claimed is None:
            return False
        try:
            live = self._store.count_code()
        except (OSError, RuntimeError):
            logger.warning(
                "Could not count the code collection to verify published "
                "breadth; trusting the carried evidence for this run",
                exc_info=True,
            )
            return False
        if live >= claimed:
            return False
        logger.warning(
            "Code collection holds %d of the %d points its published metadata "
            "describes; escalating to a full failure-safe reconciliation "
            "instead of trusting the carried evidence",
            live,
            claimed,
        )
        return True

    def publish_pending_finalization(
        self,
        checkpoint: CodeRunCheckpoint,
        *,
        reporter: ProgressReporter,
    ) -> bool:
        """Finish an ingestion-complete generation without re-entering writes.

        Returns:
            ``True`` when the generation was published, ``False`` when it is
            still ingesting and the caller must run the ordinary path.
        """
        if checkpoint.generation.finalization_phase is FinalizationPhase.INGESTING:
            return False
        reporter.phase_start("resume publication", 1)
        try:
            reconcile_generation_storage(
                self._store,
                checkpoint,
                checkpoint.policy,
                ContentKind.CODE,
            )
            checkpoint.publish_metadata(
                self._meta_path,
                published_points=self._store.count_code(),
            )
            checkpoint.publish_generation()
            reporter.advance(1)
        finally:
            reporter.phase_end()
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
            for rel in rel_paths:
                result[rel].update(
                    checkpoint.ledger.iter_retained_point_ids(
                        checkpoint.generation_id,
                        rel_path=rel,
                    )
                )
            return result
        for unit in checkpoint.ledger.iter_units(checkpoint.generation_id):
            if unit.kind is CommitUnitKind.UPSERT and unit.rel_path in result:
                result[unit.rel_path].update(unit.point_ids)
        return result
