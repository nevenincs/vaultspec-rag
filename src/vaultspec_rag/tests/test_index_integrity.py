"""Unit coverage for the serve-time index-integrity reconciliation.

Every claim here is written by the production sidecar writers into a temp
root, so the check is exercised against the exact bytes a real publication
leaves behind - no hand-rolled stand-ins for the manifest shape.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from .._index_breadth import index_meta_path, shortfall_warnings
from .._index_integrity import (
    REASON_COUNT_UNAVAILABLE,
    REASON_FILE_COVERAGE_SHORTFALL,
    REASON_MANIFEST_INCOMPLETE,
    REASON_NO_CLAIM,
    REASON_NO_MANIFEST,
    REASON_ZERO_CLAIM_OVER_NAMED_FILES,
    VERDICT_CONSISTENT,
    VERDICT_SHRUNKEN,
    VERDICT_UNVERIFIABLE,
    evaluate_index_integrity,
)
from .._source_types import PublicSourceType
from ..indexer._code_meta import publish_meta_from_file_states
from ..indexer._content_policy import ContentKind
from ..indexer._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_metadata_path,
    write_document_meta,
)
from ..indexer._file_state import FileState

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _indexed_states(count: int) -> list[FileState]:
    """Return *count* real converged indexed code states for the prod writer."""
    return [
        FileState.indexed(
            f"src/named{index:05d}.py",
            ContentKind.CODE,
            hashlib.blake2b(f"named{index}".encode()).hexdigest(),
        )
        for index in range(count)
    ]


def _publish_code_claim(
    root: Path,
    *,
    points: int,
    generation_id: str = "generation-test",
    named_files: int = 0,
    covered_files: int | None = None,
) -> None:
    """Publish a real code sidecar claiming *points* through the prod writer."""
    meta_path = index_meta_path(root, PublicSourceType.CODE)
    publish_meta_from_file_states(
        meta_path,
        _indexed_states(named_files),
        generation_id=generation_id,
        membership_epoch="membership-epoch",
        content_epoch="content-epoch",
        published_points_count=points,
        published_files_count=covered_files,
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

    def test_a_zero_claim_over_named_files_is_shrunken(self, tmp_path: Path) -> None:
        """The latched shape: zero points and zero coverage over named files.

        A publication counts the collection after storage reconciliation, so
        this pair cannot come from a complete one. Left to the count
        comparison it satisfies ``live >= claimed`` at every live count there
        is, most of all at zero, and stays satisfied forever.
        """
        _publish_code_claim(tmp_path, points=0, named_files=589, covered_files=0)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 0, claim_ttl_seconds=0.0
        )
        # Catches the self-contradiction branch being removed: without it the
        # surviving ``live_count >= claim.claimed`` test passes at 0 >= 0 and
        # the verdict comes back "consistent", which is what this fires on.
        assert verdict.verdict == VERDICT_SHRUNKEN
        assert verdict.reason == REASON_ZERO_CLAIM_OVER_NAMED_FILES
        assert verdict.named_files == 589
        assert verdict.covered_files == 0
        block = verdict.as_block()
        assert block["named_files"] == 589
        assert block["covered_files"] == 0
        # Catches a point deficit being invented from figures that never
        # described one: claimed minus live is zero here, and negative
        # whenever the collection holds anything at all.
        assert "missing_count" not in block

    def test_a_contradicted_manifest_names_no_point_deficit(
        self, tmp_path: Path
    ) -> None:
        _publish_code_claim(tmp_path, points=0, named_files=4, covered_files=0)
        block = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 900, claim_ttl_seconds=0.0
        ).as_block()
        assert "missing_count" not in block

    def test_a_zero_claim_is_shrunken_against_a_populated_collection(
        self, tmp_path: Path
    ) -> None:
        # The contradiction is inside the manifest, so no live count can
        # settle it - catches the branch being gated on an empty collection.
        _publish_code_claim(tmp_path, points=0, named_files=4, covered_files=0)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 900, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_SHRUNKEN
        assert verdict.reason == REASON_ZERO_CLAIM_OVER_NAMED_FILES

    def test_recorded_coverage_below_the_named_files_is_shrunken(
        self, tmp_path: Path
    ) -> None:
        # A publication covering a fraction of its named files still stamps a
        # self-consistent point total, so only the file figures disagree.
        _publish_code_claim(tmp_path, points=7, named_files=5, covered_files=2)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 7, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_SHRUNKEN
        assert verdict.reason == REASON_FILE_COVERAGE_SHORTFALL

    def test_an_unrecorded_coverage_figure_is_not_a_claim_of_zero(
        self, tmp_path: Path
    ) -> None:
        """An absent coverage key is ignorance and must never escalate.

        This is the distinction the recorded zero above turns on: a build that
        never wrote the key has said nothing about coverage, and escalating
        there would rebuild every root written before it existed.
        """
        _publish_code_claim(tmp_path, points=7, named_files=5, covered_files=None)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 7, claim_ttl_seconds=0.0
        )
        # Catches the absent figure being defaulted to zero anywhere between
        # the sidecar parse and the verdict: it would read shrunken here.
        assert verdict.verdict == VERDICT_CONSISTENT
        assert verdict.covered_files is None

    def test_a_zero_claim_over_no_named_files_is_consistent(
        self, tmp_path: Path
    ) -> None:
        # A genuinely empty index claims zero over zero files and is whole.
        _publish_code_claim(tmp_path, points=0, named_files=0, covered_files=0)
        verdict = evaluate_index_integrity(
            tmp_path, PublicSourceType.CODE, 0, claim_ttl_seconds=0.0
        )
        assert verdict.verdict == VERDICT_CONSISTENT

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
        meta_path = index_meta_path(tmp_path, PublicSourceType.CODE)
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


from .._search_state import (  # noqa: E402
    COLLAPSE_MINIMUM_RESULTS,
    BreadthFindings,
    result_collapse,
    search_index_state,
)


class TestACollapsedResultPageIsReported:
    """The signal for the collapse no count can see.

    An interrupted rebuild that got as far as writing metadata republishes the
    fragment's own figures, so the collection is self-consistent: live points
    equal published points, named files equal covered files, and every
    comparison the service can make agrees. The only thing left that disagrees
    is the answer, where a broad query resolves every rank to one surviving
    file and reads as a genuine "this does not exist here".

    Proved able to fail. Removing the ``len(distinct) != 1`` test fails 2 of
    the 9 cells on their ``is None`` assertions -
    ``test_a_diverse_page_is_not_reported`` and
    ``test_a_healthy_page_raises_no_warning`` - because a diverse page then
    reports a collapse naming whichever path the set happened to yield.
    Removing the ``COLLAPSE_MINIMUM_RESULTS`` test instead fails 4, the
    ``test_a_page_too_small_to_judge_stays_silent`` cells for 1 through 4
    results; the zero-result cell still passes, because an empty page has no
    single distinct path either. Restoring each returns all 9 to green.
    """

    def test_a_collapsed_page_reports_its_figures(self) -> None:
        collapse = result_collapse(("a.py",) * 10)
        assert collapse == {
            "result_count": 10,
            "distinct_paths": 1,
            "path": "a.py",
        }

    def test_a_diverse_page_is_not_reported(self) -> None:
        assert result_collapse(("a.py", "b.py", "c.py", "d.py", "e.py")) is None
        # One dissenting row is enough: the failure this names is total.
        assert result_collapse(("a.py", "a.py", "a.py", "a.py", "b.py")) is None

    @pytest.mark.parametrize("count", range(COLLAPSE_MINIMUM_RESULTS))
    def test_a_page_too_small_to_judge_stays_silent(self, count: int) -> None:
        # A narrow query legitimately answers from one file. Absence of the
        # signal is "no evidence", never "diverse".
        assert result_collapse(("a.py",) * count) is None

    def test_the_block_carries_the_figures_to_both_surfaces(self) -> None:
        state = search_index_state(
            indexed_count=784,
            requested_root="/root",
            search_type=PublicSourceType.CODE,
            findings=BreadthFindings(
                collapse=result_collapse(("_run_ledger.py",) * 10)
            ),
        )
        assert state["result_collapse"] == {
            "result_count": 10,
            "distinct_paths": 1,
            "path": "_run_ledger.py",
        }
        # The count is healthy and no breadth deficit exists, so this is the
        # only warning the walker can raise - which is the whole point.
        assert "shortfall" not in state
        assert "file_shortfall" not in state
        warnings = shortfall_warnings(state)
        assert len(warnings) == 1
        assert "all 10 results resolve to a single file" in warnings[0].deficit
        assert "_run_ledger.py" in warnings[0].deficit

    def test_a_healthy_page_raises_no_warning(self) -> None:
        state = search_index_state(
            indexed_count=784,
            requested_root="/root",
            search_type=PublicSourceType.CODE,
            findings=BreadthFindings(
                collapse=result_collapse(("a.py", "b.py", "c.py", "d.py", "e.py"))
            ),
        )
        assert "result_collapse" not in state
        assert shortfall_warnings(state) == []
