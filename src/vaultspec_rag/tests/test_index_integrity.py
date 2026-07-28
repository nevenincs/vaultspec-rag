"""Unit coverage for the serve-time index-integrity reconciliation.

Every claim here is written by the production sidecar writers into a temp
root, so the check is exercised against the exact bytes a real publication
leaves behind - no hand-rolled stand-ins for the manifest shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._index_breadth import code_meta_path
from .._index_integrity import (
    REASON_COUNT_UNAVAILABLE,
    REASON_MANIFEST_INCOMPLETE,
    REASON_NO_CLAIM,
    REASON_NO_MANIFEST,
    VERDICT_CONSISTENT,
    VERDICT_SHRUNKEN,
    VERDICT_UNVERIFIABLE,
    evaluate_index_integrity,
)
from .._source_types import PublicSourceType
from ..indexer._code_meta import publish_meta_from_file_states
from ..indexer._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_metadata_path,
    write_document_meta,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _publish_code_claim(
    root: Path,
    *,
    points: int,
    generation_id: str = "generation-test",
) -> None:
    """Publish a real code sidecar claiming *points* through the prod writer."""
    meta_path = code_meta_path(root)
    publish_meta_from_file_states(
        meta_path,
        [],
        generation_id=generation_id,
        membership_epoch="membership-epoch",
        content_epoch="content-epoch",
        published_points_count=points,
    )


def _publish_document_claim(
    root: Path,
    *,
    point_ids: tuple[tuple[str, tuple[str, ...]], ...],
    complete: bool = True,
) -> None:
    """Publish a real document manifest through the production writer."""
    files = tuple(
        DocumentFileMetadata(path, "fingerprint", ids)
        for path, ids in sorted(point_ids)
    )
    write_document_meta(
        document_metadata_path(root),
        DocumentIndexMetadata(
            membership_fingerprint="membership",
            content_fingerprint="content",
            policy_snapshot="policy",
            files=files,
            generation_id="generation-doc",
            complete=complete,
        ),
    )


class TestCodeClassification:
    def test_exact_match_is_consistent(self, tmp_path: Path) -> None:
        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 5, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_CONSISTENT
        assert verdict.claimed_count == 5
        assert verdict.live_count == 5
        assert verdict.generation_id == "generation-test"
        assert verdict.reason is None

    def test_surplus_is_consistent(self, tmp_path: Path) -> None:
        # An in-flight incremental upserts ahead of its republication, so a
        # count above the claim is legitimate motion, never loss.
        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 8, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_CONSISTENT

    def test_deficit_is_shrunken_with_the_figures(self, tmp_path: Path) -> None:
        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 2, claim_ttl_seconds=0.0
        )
        # Catches the comparison being widened or removed: with the guard
        # neutered (e.g. any tolerance below the three-point deficit, or a
        # comparison that always passes), the verdict comes back "consistent"
        # and this assertion is the one that fires.
        assert verdict.verdict == VERDICT_SHRUNKEN
        block = verdict.as_block()
        # Catches the evidence being dropped from the envelope block: an
        # operator must see claimed-vs-live and the claiming generation.
        assert block["claimed_count"] == 5
        assert block["live_count"] == 2
        assert block["missing_count"] == 3
        assert block["generation_id"] == "generation-test"

    def test_a_single_point_deficit_is_shrunken(self, tmp_path: Path) -> None:
        # Catches any tolerance wider than zero: the smallest possible real
        # loss must already flip the verdict, because a tolerance of N points
        # masks exactly a loss of N points.
        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 4, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_SHRUNKEN

    def test_no_sidecar_is_unverifiable(self, tmp_path: Path) -> None:
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 7, claim_ttl_seconds=0.0
        )
        # Catches ignorance being escalated: a root with no manifest has
        # nothing to fall short of and must not read as shrunken.
        assert verdict.verdict == VERDICT_UNVERIFIABLE
        assert verdict.reason == REASON_NO_MANIFEST
        assert verdict.claimed_count is None
        assert verdict.live_count == 7

    def test_legacy_sidecar_without_a_claim_is_unverifiable(
        self, tmp_path: Path
    ) -> None:
        # A sidecar written by a build that predates the breadth keys: file
        # entries and the embed-schema marker, no published figure. This is a
        # data shape, written verbatim because no current writer produces it.
        meta_path = code_meta_path(tmp_path)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            '{"__code_embed_schema__": "2", "src/app.py": "abc123"}',
            encoding="utf-8",
        )
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 7, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_UNVERIFIABLE
        assert verdict.reason == REASON_NO_CLAIM

    def test_missing_live_count_is_unverifiable_not_fatal(self, tmp_path: Path) -> None:
        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, None, claim_ttl_seconds=0.0
        )
        # Catches a failed count being read as a zero count: live None must
        # never compare as 0 < 5 and report loss the store never demonstrated.
        assert verdict.verdict == VERDICT_UNVERIFIABLE
        assert verdict.reason == REASON_COUNT_UNAVAILABLE
        # The claim is still attached as evidence for the operator.
        assert verdict.claimed_count == 5
        assert verdict.live_count is None


class TestDocumentClassification:
    def test_claim_is_the_sum_of_published_point_ids(self, tmp_path: Path) -> None:
        _publish_document_claim(
            tmp_path,
            point_ids=(("docs/a.pdf", ("p1", "p2")), ("docs/b.pdf", ("p3",))),
        )
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.DOCUMENT, 3, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_CONSISTENT
        assert verdict.claimed_count == 3
        assert verdict.generation_id == "generation-doc"

    def test_deficit_is_shrunken(self, tmp_path: Path) -> None:
        _publish_document_claim(
            tmp_path,
            point_ids=(("docs/a.pdf", ("p1", "p2")), ("docs/b.pdf", ("p3",))),
        )
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.DOCUMENT, 1, claim_ttl_seconds=0.0
        )
        # Catches the document domain being quietly excluded from the guard:
        # its manifest names every published point, so a deficit against that
        # sum is as demonstrated as the code domain's.
        assert verdict.verdict == VERDICT_SHRUNKEN
        assert verdict.as_block()["missing_count"] == 2

    def test_incomplete_manifest_claims_nothing(self, tmp_path: Path) -> None:
        _publish_document_claim(
            tmp_path,
            point_ids=(("docs/a.pdf", ("p1", "p2")),),
            complete=False,
        )
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.DOCUMENT, 0, claim_ttl_seconds=0.0
        )
        # Catches an admitted-partial manifest being held against the
        # collection: its figures do not describe a whole publication.
        assert verdict.verdict == VERDICT_UNVERIFIABLE
        assert verdict.reason == REASON_MANIFEST_INCOMPLETE


class TestVaultClassification:
    def test_vault_is_honestly_unverifiable(self, tmp_path: Path) -> None:
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.VAULT, 12, claim_ttl_seconds=0.0
        )
        # Catches a claim being invented for a domain that publishes none:
        # the vault sidecar records hashes and epochs, no point figure.
        assert verdict.verdict == VERDICT_UNVERIFIABLE
        assert verdict.reason == REASON_NO_CLAIM
        assert verdict.claimed_count is None

    def test_combined_is_not_a_claim_domain(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no per-domain breadth claim"):
            evaluate_index_integrity(
                tmp_path, PublicSourceType.COMBINED, 1, claim_ttl_seconds=0.0
            )


class TestClaimCache:
    def test_claim_reads_are_bounded_by_the_ttl(self, tmp_path: Path) -> None:
        _publish_code_claim(tmp_path, points=5)
        first = evaluate_index_integrity(tmp_path, PublicSourceType.CODE, 5)
        assert first.verdict == VERDICT_CONSISTENT
        # Republish a larger claim. Within the TTL the cached claim answers,
        # so the verdict stays consistent against the old figure - which is
        # what proves the sidecar is not re-parsed on every query.
        _publish_code_claim(tmp_path, points=100)
        cached = evaluate_index_integrity(tmp_path, PublicSourceType.CODE, 5)
        assert cached.verdict == VERDICT_CONSISTENT
        assert cached.claimed_count == 5
        # A zero TTL forces a fresh parse, so the new claim takes effect and
        # the same live count now reads as shrunken.
        fresh = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 5, claim_ttl_seconds=0.0
        )
        assert fresh.verdict == VERDICT_SHRUNKEN
        assert fresh.claimed_count == 100


class TestShrunkenLogging:
    def test_error_names_the_figures_and_is_rate_limited(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _publish_code_claim(tmp_path, points=5, generation_id="generation-log")
        with caplog.at_level("ERROR", logger="vaultspec_rag._index_integrity"):
            evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, 2, claim_ttl_seconds=0.0
            )
            evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, 2, claim_ttl_seconds=0.0
            )
        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        # Catches the ERROR being dropped entirely (zero records - a silent
        # degradation) and the rate limit being removed (two records - one
        # line per query on a busy surface).
        assert len(errors) == 1
        message = errors[0].getMessage()
        # Catches the evidence being dropped from the log line: the operator
        # needs claimed-vs-live and the claiming generation to act.
        assert "2" in message
        assert "5" in message
        assert "generation-log" in message

    def test_unverifiable_never_logs_an_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("ERROR", logger="vaultspec_rag._index_integrity"):
            evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, 7, claim_ttl_seconds=0.0
            )
        # Catches ignorance being escalated to the operator channel: every
        # root written by an older build would otherwise ERROR on every
        # search window.
        assert not [r for r in caplog.records if r.levelname == "ERROR"]


class TestEnvelopeBlock:
    def test_index_state_carries_the_block_when_evaluated(self, tmp_path: Path) -> None:
        from .._search_state import BreadthFindings, search_index_state

        _publish_code_claim(tmp_path, points=5)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 5, claim_ttl_seconds=0.0
        )
        state = search_index_state(
            indexed_count=5,
            requested_root=tmp_path,
            search_type=PublicSourceType.CODE,
            findings=BreadthFindings(integrity=verdict),
        )
        # "Checked and fine" must be distinguishable from "never checked":
        # the block is present even for a consistent verdict.
        assert state["index_integrity"] == {
            "verdict": "consistent",
            "source": "code",
            "claimed_count": 5,
            "live_count": 5,
            "generation_id": "generation-test",
            "reason": None,
        }

    def test_index_state_omits_the_block_when_not_evaluated(self) -> None:
        from .._search_state import search_index_state

        state = search_index_state(
            indexed_count=5,
            requested_root="C:/work/project",
            search_type=PublicSourceType.CODE,
        )
        # Absent means "this surface predates the check" - an old daemon's
        # envelope shape must be reproducible exactly.
        assert "index_integrity" not in state
