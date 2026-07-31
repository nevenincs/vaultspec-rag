"""The indexed-frontmatter subset is a contract with the vault payloads.

Change detection digests a subset of what a vault point payload carries. A
field that enters a payload without entering the subset is refreshed by
nothing: no digest covers it, so no run ever classifies its change as a
change, and its stored value goes stale silently while every assertion that
does not compare payloads keeps passing.

These tests are the enforcement. The partition test fails the moment a payload
key exists that is neither body, nor structure, nor a member of the subset -
which is exactly the moment someone adds a payload field and forgets the
digest.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from .._store_models import (
    VAULT_BODY_PAYLOAD_KEYS,
    VAULT_STRUCTURAL_PAYLOAD_KEYS,
    VaultDocument,
    _vault_chunk_payload,
    _vault_doc_payload,
    vault_indexed_metadata,
    vault_metadata_digest,
)
from ..indexer._vault_prep import split_document

pytestmark = [pytest.mark.unit]


def _doc() -> VaultDocument:
    """Build a fully populated vault document.

    Variants are made with :func:`dataclasses.replace`, which type-checks the
    field name and its value against the real dataclass - a keyword-string map
    would let a renamed field go on being "mutated" by a key that no longer
    exists, silently testing nothing.
    """
    return VaultDocument(
        id="adr/2026-07-25-sample",
        path="adr/2026-07-25-sample.md",
        doc_type="adr",
        feature="sample-feature",
        date="2026-07-25",
        tags=["#adr", "#sample-feature"],
        related=["[[2026-07-25-sample-research]]"],
        title="sample adr",
        status="accepted",
        content="# sample adr\n\nA body that stays put.\n",
    )


class TestSubsetPartitionsThePayload:
    """Every vault payload key is body, structure, or an indexed subset field."""

    def test_document_payload_keys_are_all_accounted_for(self) -> None:
        doc = _doc()
        accounted = (
            set(vault_indexed_metadata(doc))
            | VAULT_BODY_PAYLOAD_KEYS
            | VAULT_STRUCTURAL_PAYLOAD_KEYS
        )
        unaccounted = set(_vault_doc_payload(doc)) - accounted
        assert unaccounted == set(), (
            "vault document payload fields outside the subset digest: "
            f"{sorted(unaccounted)} - add them to vault_indexed_metadata() or "
            "classify them as body/structural, or they will never refresh"
        )

    def test_chunk_payload_keys_are_all_accounted_for(self) -> None:
        doc = _doc()
        chunk = split_document(doc, chunk_chars=64)[0]
        accounted = (
            set(vault_indexed_metadata(doc))
            | VAULT_BODY_PAYLOAD_KEYS
            | VAULT_STRUCTURAL_PAYLOAD_KEYS
        )
        unaccounted = set(_vault_chunk_payload(chunk)) - accounted
        assert unaccounted == set(), (
            "vault chunk payload fields outside the subset digest: "
            f"{sorted(unaccounted)} - add them to vault_indexed_metadata() or "
            "classify them as body/structural, or they will never refresh"
        )

    def test_subset_names_no_field_the_payload_does_not_carry(self) -> None:
        """A subset field absent from every payload digests noise, not content."""
        doc = _doc()
        chunk = split_document(doc, chunk_chars=64)[0]
        carried = set(_vault_doc_payload(doc)) | set(_vault_chunk_payload(chunk))
        assert set(vault_indexed_metadata(doc)) <= carried

    def test_every_subset_field_moves_the_digest(self) -> None:
        """No subset member is inert - each one alone changes the digest.

        A field listed in the subset but folded away by canonicalisation would
        be indistinguishable from one that was never listed.
        """
        baseline = vault_metadata_digest(_doc())
        # Each entry mutates exactly one subset field. Spelled as calls rather
        # than a name-to-value map so the field names stay checkable against
        # the real signature instead of being strings nothing verifies.
        mutated: dict[str, VaultDocument] = {
            "path": replace(_doc(), path="adr/2026-07-25-moved.md"),
            "doc_type": replace(_doc(), doc_type="research"),
            "feature": replace(_doc(), feature="other-feature"),
            "date": replace(_doc(), date="2026-07-26"),
            "tags": replace(_doc(), tags=["#adr", "#other-feature"]),
            "related": replace(_doc(), related=[]),
            "title": replace(_doc(), title="renamed adr"),
            "status": replace(_doc(), status="superseded"),
        }
        assert set(mutated) == set(vault_indexed_metadata(_doc())), (
            "the subset gained or lost a field this test does not mutate"
        )
        for field, doc in mutated.items():
            assert vault_metadata_digest(doc) != baseline, (
                f"{field} is in the indexed subset but does not move its digest"
            )


class TestCanonicalisation:
    """The digest absorbs churn that changes no value, and nothing more."""

    def test_whitespace_churn_does_not_move_the_digest(self) -> None:
        baseline = vault_metadata_digest(_doc())
        churned = replace(
            _doc(),
            title="  sample adr  ",
            date="2026-07-25 ",
            tags=[" #adr", "#sample-feature\t"],
        )
        assert vault_metadata_digest(churned) == baseline

    def test_the_body_does_not_move_the_metadata_digest(self) -> None:
        """The body is the other digest's job; overlap would double-count it."""
        baseline = vault_metadata_digest(_doc())
        rewritten = replace(_doc(), content="entirely different")
        assert vault_metadata_digest(rewritten) == baseline

    def test_tag_order_moves_the_digest(self) -> None:
        """Order is payload-visible, so a reorder is a real metadata delta."""
        baseline = vault_metadata_digest(_doc())
        reordered = replace(_doc(), tags=["#sample-feature", "#adr"])
        assert vault_metadata_digest(reordered) != baseline
