"""Exact algebra and validation for publication completeness proofs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._publication_proof import (
    AggregateDelta,
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofIncompatibleError,
    ProofReadConflictError,
    ProofReadToken,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [pytest.mark.unit]


def _evidence(path: str, *point_ids: str, content: str = "content-v1") -> ProofEvidence:
    return ProofEvidence(
        rel_path=path,
        content_identity=content,
        point_ids=tuple(point_ids),
    )


def _compatibility(*, policy: str = "policy-v1") -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType.CODE,
        root_identity="root-v1",
        backend_identity="backend-v1",
        collection_identity="collection-v1",
        storage_schema=1,
        payload_schema=2,
        embedding_schema_identity="embedding-v1",
        chunking_schema_identity="chunking-v1",
        membership_identity="membership-v1",
        content_identity="content-v1",
        policy_identity=policy,
    )


@pytest.mark.parametrize(
    ("delta", "expected_delta", "expected_aggregate"),
    [
        pytest.param(
            PathDelta(
                outcome=PathOutcome.ADD,
                expected_parent_revision=4,
                rel_path="src/new.py",
                new=_evidence("src/new.py", "new:0", "new:1"),
            ),
            AggregateDelta(indexed_identities=1, retained_points=2),
            ProofAggregate(indexed_identities=4, retained_points=8),
            id="add",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.MODIFY,
                expected_parent_revision=4,
                rel_path="src/changed.py",
                old=_evidence("src/changed.py", "old:0"),
                new=_evidence(
                    "src/changed.py", "new:0", "new:1", "new:2", content="content-v2"
                ),
            ),
            AggregateDelta(indexed_identities=0, retained_points=2),
            ProofAggregate(indexed_identities=3, retained_points=8),
            id="modify",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.DELETE,
                expected_parent_revision=4,
                rel_path="src/deleted.py",
                old=_evidence("src/deleted.py", "deleted:0", "deleted:1"),
            ),
            AggregateDelta(indexed_identities=-1, retained_points=-2),
            ProofAggregate(indexed_identities=2, retained_points=4),
            id="delete",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.RENAME,
                expected_parent_revision=4,
                rel_path="src/old.py",
                target_rel_path="src/new.py",
                old=_evidence("src/old.py", "old:0", "old:1"),
                new=_evidence(
                    "src/new.py", "new:0", "new:1", "new:2", content="content-v2"
                ),
            ),
            AggregateDelta(indexed_identities=0, retained_points=1),
            ProofAggregate(indexed_identities=3, retained_points=7),
            id="rename",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.EMPTY,
                expected_parent_revision=4,
                rel_path="src/empty.py",
                old=_evidence("src/empty.py", "empty:0"),
            ),
            AggregateDelta(indexed_identities=-1, retained_points=-1),
            ProofAggregate(indexed_identities=2, retained_points=5),
            id="empty-removes-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.EMPTY,
                expected_parent_revision=4,
                rel_path="src/empty.py",
            ),
            AggregateDelta(),
            ProofAggregate(indexed_identities=3, retained_points=6),
            id="empty-without-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.IGNORED,
                expected_parent_revision=4,
                rel_path="src/ignored.py",
            ),
            AggregateDelta(),
            ProofAggregate(indexed_identities=3, retained_points=6),
            id="ignored-without-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.IGNORED,
                expected_parent_revision=4,
                rel_path="src/ignored.py",
                old=_evidence("src/ignored.py", "ignored:0"),
            ),
            AggregateDelta(indexed_identities=-1, retained_points=-1),
            ProofAggregate(indexed_identities=2, retained_points=5),
            id="ignored-removes-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.REJECTED,
                expected_parent_revision=4,
                rel_path="src/rejected.py",
                old=_evidence("src/rejected.py", "rejected:0"),
            ),
            AggregateDelta(indexed_identities=-1, retained_points=-1),
            ProofAggregate(indexed_identities=2, retained_points=5),
            id="rejected-removes-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.REJECTED,
                expected_parent_revision=4,
                rel_path="src/rejected.py",
            ),
            AggregateDelta(),
            ProofAggregate(indexed_identities=3, retained_points=6),
            id="rejected-without-old",
        ),
        pytest.param(
            PathDelta(
                outcome=PathOutcome.NOOP,
                expected_parent_revision=4,
                rel_path="src/same.py",
                old=_evidence("src/same.py", "same:0", "same:1"),
                new=_evidence("src/same.py", "same:0", "same:1"),
            ),
            AggregateDelta(),
            ProofAggregate(indexed_identities=3, retained_points=6),
            id="noop",
        ),
    ],
)
def test_path_outcome_applies_exact_aggregate_delta(
    delta: PathDelta,
    expected_delta: AggregateDelta,
    expected_aggregate: ProofAggregate,
) -> None:
    parent = ProofAggregate(indexed_identities=3, retained_points=6)

    assert delta.aggregate_delta == expected_delta
    assert parent.apply(delta) == expected_aggregate


def test_modify_requires_changed_evidence_and_noop_requires_exact_evidence() -> None:
    """Mutation proving this can fail: allow equal MODIFY or absent NOOP evidence."""
    evidence = _evidence("src/item.py", "point:0")

    with pytest.raises(ValueError, match="invalid modify"):
        PathDelta(
            outcome=PathOutcome.MODIFY,
            expected_parent_revision=4,
            rel_path=evidence.rel_path,
            old=evidence,
            new=evidence,
        )
    with pytest.raises(ValueError, match="invalid noop"):
        PathDelta(
            outcome=PathOutcome.NOOP,
            expected_parent_revision=4,
            rel_path=evidence.rel_path,
        )
    for changed in (
        _evidence("src/item.py", "point:0", content="content-v2"),
        _evidence("src/item.py", "point:1"),
    ):
        with pytest.raises(ValueError, match="invalid noop"):
            PathDelta(
                outcome=PathOutcome.NOOP,
                expected_parent_revision=4,
                rel_path=evidence.rel_path,
                old=evidence,
                new=changed,
            )

    exact_noop = PathDelta(
        outcome=PathOutcome.NOOP,
        expected_parent_revision=4,
        rel_path=evidence.rel_path,
        old=evidence,
        new=evidence,
    )
    assert exact_noop.aggregate_delta == AggregateDelta()
    assert not exact_noop.changes_proof

    changed = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=4,
        rel_path=evidence.rel_path,
        old=evidence,
        new=_evidence("src/item.py", "point:1"),
    )
    assert changed.changes_proof


def test_read_token_fences_open_or_changed_receipt_snapshots() -> None:
    """Mutation proving this can fail: omit the receipt flag or reservation sequence."""
    key = _compatibility()
    token = ProofReadToken.from_snapshot(
        compatibility_key=key,
        revision=7,
        reservation_sequence=11,
        has_open_receipt=False,
    )

    token.validate(
        compatibility_key=key,
        revision=7,
        reservation_sequence=11,
        has_open_receipt=False,
    )
    with pytest.raises(ProofReadConflictError):
        token.validate(
            compatibility_key=key,
            revision=8,
            reservation_sequence=11,
            has_open_receipt=False,
        )
    with pytest.raises(ProofReadConflictError):
        token.validate(
            compatibility_key=key,
            revision=7,
            reservation_sequence=12,
            has_open_receipt=False,
        )
    with pytest.raises(ProofReadConflictError):
        token.validate(
            compatibility_key=key,
            revision=7,
            reservation_sequence=11,
            has_open_receipt=True,
        )

    with pytest.raises(ProofReadConflictError, match="open receipt"):
        ProofReadToken.from_snapshot(
            compatibility_key=key,
            revision=7,
            reservation_sequence=11,
            has_open_receipt=True,
        )
    with pytest.raises(ProofIncompatibleError):
        token.validate(
            compatibility_key=_compatibility(policy="policy-v2"),
            revision=7,
            reservation_sequence=11,
            has_open_receipt=False,
        )


@pytest.mark.parametrize(
    ("make_delta", "message"),
    [
        (
            lambda: PathDelta(
                outcome=PathOutcome.ADD,
                expected_parent_revision=4,
                rel_path="src/item.py",
            ),
            "invalid add",
        ),
        (
            lambda: PathDelta(
                outcome=PathOutcome.MODIFY,
                expected_parent_revision=4,
                rel_path="src/item.py",
            ),
            "invalid modify",
        ),
        (
            lambda: PathDelta(
                outcome=PathOutcome.DELETE,
                expected_parent_revision=4,
                rel_path="src/item.py",
            ),
            "invalid delete",
        ),
        (
            lambda: PathDelta(
                outcome=PathOutcome.RENAME,
                expected_parent_revision=4,
                rel_path="src/item.py",
            ),
            "rename must name",
        ),
        (
            lambda: PathDelta(
                outcome=PathOutcome.RENAME,
                expected_parent_revision=4,
                rel_path="src/item.py",
                old=_evidence("src/item.py", "old:0"),
                new=_evidence("src/item.py", "new:0"),
                target_rel_path="src/item.py",
            ),
            "rename must change",
        ),
        (
            lambda: PathDelta(
                outcome=PathOutcome.NOOP,
                expected_parent_revision=4,
                rel_path="src/item.py",
                new=_evidence("src/item.py", "new:0"),
            ),
            "invalid noop",
        ),
    ],
)
def test_invalid_outcome_shapes_are_rejected(
    make_delta: Callable[[], PathDelta], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        make_delta()


def test_rename_requires_evidence_for_distinct_endpoints() -> None:
    with pytest.raises(ValueError, match="new evidence must match"):
        PathDelta(
            outcome=PathOutcome.RENAME,
            expected_parent_revision=4,
            rel_path="src/old.py",
            target_rel_path="src/new.py",
            old=_evidence("src/old.py", "old:0"),
            new=_evidence("src/other.py", "new:0"),
        )


@pytest.mark.parametrize(
    "point_ids",
    [("point:1", "point:0"), ("point:0", "point:0")],
    ids=["not-canonical", "duplicate"],
)
def test_evidence_requires_unique_canonically_ordered_point_ids(
    point_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        _evidence("src/item.py", *point_ids)


@pytest.mark.parametrize(
    ("aggregate", "delta"),
    [
        (
            ProofAggregate(indexed_identities=1, retained_points=1),
            AggregateDelta(indexed_identities=-2),
        ),
        (
            ProofAggregate(indexed_identities=1, retained_points=1),
            AggregateDelta(retained_points=-2),
        ),
        (
            ProofAggregate(indexed_identities=1, retained_points=2),
            AggregateDelta(indexed_identities=1, retained_points=-1),
        ),
        (
            ProofAggregate(indexed_identities=1, retained_points=2),
            AggregateDelta(indexed_identities=-1, retained_points=-1),
        ),
    ],
    ids=[
        "identity-underflow",
        "point-underflow",
        "fewer-points-than-identities",
        "points-without-identities",
    ],
)
def test_aggregate_refuses_impossible_results(
    aggregate: ProofAggregate, delta: AggregateDelta
) -> None:
    with pytest.raises(ValueError):
        aggregate.apply(delta)
