"""Behaviour of the run-checkpoint logic shared by both indexers.

These pin `classify_interrupted_generation`, which decides what an interrupted
run's terminal state becomes. It is shared by the code and document
checkpoints, so a change here moves both at once - which is the point, but it
also means a silent regression moves both at once.

The branch coverage matters more than it looks. Before this file existed the
destructive branch was exercised by exactly one code-path integration test, the
non-destructive branch by none, and the already-terminal guard by none; the
document checkpoint had four production call sites and no coverage at all. A
green suite therefore said nothing about this decision.

Real `RunLedger` against a real SQLite file throughout - no mocks, patches, or
fakes - so the assertions are about persisted state, not about call recording.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..indexer._checkpoint_common import (
    classify_interrupted_generation,
    configuration_fingerprint,
)
from ..indexer._content_policy import ContentKind
from ..indexer._document_checkpoint import DocumentRunConfiguration
from ..indexer._run_checkpoint import CodeRunConfiguration
from ..indexer._run_ledger import (
    RunLedger,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _signature(root: Path, *, clean: bool) -> RunSignature:
    """A run signature whose ``clean`` flag drives destructive intent."""
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="source-v1",
        source_type=ContentKind.CODE,
        operation=RunOperation.FULL,
        clean=clean,
        model_identity="model-v1",
        dense_dimensions=8,
        embedding_schema=2,
        payload_schema=3,
        content_epoch="content-v1",
        membership_epoch="membership-v1",
        preprocessing_identity="preprocessing-v1",
        configuration_fingerprint="configuration-v1",
        policy_fingerprint="policy-v1",
    )


def _open_ledger(tmp_path: Path, *, clean: bool):
    ledger = RunLedger(index_run_ledger_path(tmp_path))
    return ledger, ledger.start_generation(_signature(tmp_path, clean=clean))


class TestClassifyInterruptedGeneration:
    """An interruption's terminal state follows the run's destructive intent."""

    def test_interrupted_rebuild_is_rebuild_incomplete(self, tmp_path: Path) -> None:
        # A clean run has already dropped data it did not finish replacing, so
        # a later run must not treat it as a usable parent.
        ledger, generation = _open_ledger(tmp_path, clean=True)
        assert generation.destructive_intent

        finished = classify_interrupted_generation(
            ledger, generation, RuntimeError("disk went away")
        )

        assert finished.terminal_state is RunTerminalState.REBUILD_INCOMPLETE
        assert ledger.generation(generation.generation_id).terminal_state is (
            RunTerminalState.REBUILD_INCOMPLETE
        )

    def test_interrupted_incremental_is_merely_failed(self, tmp_path: Path) -> None:
        # This is the branch the suite never covered. A non-destructive run
        # left published data intact, so calling it REBUILD_INCOMPLETE would
        # wrongly bar a later run from resuming against a valid parent.
        ledger, generation = _open_ledger(tmp_path, clean=False)
        assert not generation.destructive_intent

        finished = classify_interrupted_generation(
            ledger, generation, RuntimeError("disk went away")
        )

        assert finished.terminal_state is RunTerminalState.FAILED

    def test_detail_names_the_exception_type_and_message(self, tmp_path: Path) -> None:
        ledger, generation = _open_ledger(tmp_path, clean=False)

        finished = classify_interrupted_generation(
            ledger, generation, ValueError("segment 7 was short")
        )

        assert finished.terminal_detail == "ValueError: segment 7 was short"

    def test_an_already_terminal_generation_is_left_untouched(
        self, tmp_path: Path
    ) -> None:
        # Guard: a failure raised AFTER the run finished must not overwrite the
        # outcome already recorded. Break-and-watch - dropping the RUNNING
        # check in classify_interrupted_generation flips this to FAILED, and
        # `finish_generation` rejects re-finishing a published generation, so
        # the regression surfaces as an error rather than silent corruption.
        ledger, generation = _open_ledger(tmp_path, clean=False)
        cancelled = ledger.finish_generation(
            generation.generation_id,
            RunTerminalState.CANCELLED,
            detail="operator requested cancellation",
        )

        result = classify_interrupted_generation(
            ledger, cancelled, RuntimeError("late failure")
        )

        assert result.terminal_state is RunTerminalState.CANCELLED
        assert result.terminal_detail == "operator requested cancellation"


class TestConfigurationFingerprint:
    """The fingerprint identifies a configuration's values, nothing else."""

    def test_same_values_fingerprint_identically(self) -> None:
        left = CodeRunConfiguration(
            segment_max_chunks=1,
            segment_max_bytes=2,
            queue_max_chunks=3,
            queue_max_bytes=4,
            slice_max_chunks=5,
            slice_max_bytes=6,
            sparse_enabled=True,
            sparse_dimension=7,
            encode_batch_size=8,
            flush_slices=9,
        )
        right = CodeRunConfiguration(
            segment_max_chunks=1,
            segment_max_bytes=2,
            queue_max_chunks=3,
            queue_max_bytes=4,
            slice_max_chunks=5,
            slice_max_bytes=6,
            sparse_enabled=True,
            sparse_dimension=7,
            encode_batch_size=8,
            flush_slices=9,
        )
        assert configuration_fingerprint(left) == configuration_fingerprint(right)

    def test_one_changed_field_changes_the_fingerprint(self) -> None:
        # The compatibility check that decides whether a resumed run may reuse
        # a parent generation reads this digest, so an insensitive fingerprint
        # would let an incompatible configuration resume someone else's work.
        base = DocumentRunConfiguration(
            slice_max_chunks=1,
            source_bytes=2,
            generated_chunks=3,
            weighted_bytes=4,
            sparse_enabled=True,
            sparse_dimension=5,
            encode_batch_size=6,
        )
        changed = DocumentRunConfiguration(
            slice_max_chunks=1,
            source_bytes=2,
            generated_chunks=3,
            weighted_bytes=4,
            sparse_enabled=True,
            sparse_dimension=5,
            encode_batch_size=7,
        )
        assert configuration_fingerprint(base) != configuration_fingerprint(changed)

    def test_both_indexer_configurations_share_one_implementation(self) -> None:
        # Each indexer previously carried its own copy of this function. They
        # are one now, so both configuration types must flow through it.
        code = CodeRunConfiguration(
            segment_max_chunks=1,
            segment_max_bytes=1,
            queue_max_chunks=1,
            queue_max_bytes=1,
            slice_max_chunks=1,
            slice_max_bytes=1,
            sparse_enabled=False,
            sparse_dimension=1,
            encode_batch_size=1,
            flush_slices=1,
        )
        document = DocumentRunConfiguration(
            slice_max_chunks=1,
            source_bytes=1,
            generated_chunks=1,
            weighted_bytes=1,
            sparse_enabled=False,
            sparse_dimension=1,
            encode_batch_size=1,
        )
        for configuration in (code, document):
            digest = configuration_fingerprint(configuration)
            assert len(digest) == 128  # blake2b default hex digest
