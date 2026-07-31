"""Unit tests for the storage-schema contract module.

Exercises the wire descriptor and the consumer compatibility helper, and proves
the module stays a torch-free leaf so the process-wide ``/readiness`` report can
advertise the descriptor without loading a model.
"""

from __future__ import annotations

import pytest

from vaultspec_rag import store_schema as ss

from .._store_models import (
    CodeChunk,
    VaultChunk,
    VaultDocument,
    _code_chunk_payload,
    _vault_chunk_payload,
    _vault_doc_payload,
)
from ._import_probe import assert_fresh_import_excludes, import_probe_source

pytestmark = [pytest.mark.unit]


class TestDescriptor:
    """describe_storage_schema builds the bounded wire descriptor."""

    def test_descriptor_carries_the_pinned_version_and_collection_names(self) -> None:
        """The version and collection names are pinned to explicit literals.

        Comparing the descriptor against ``STORAGE_SCHEMA_VERSION`` and the
        ``*_COLLECTION`` constants only restates the values the descriptor is
        built from, so it passes for any value either takes. Both are wire
        facts an out-of-process consumer matches on - the version gates whether
        it reads at all, the collection suffix is what it opens - and both
        change only as a declared breaking change, so the literals here are the
        independent statement a change has to be mirrored into deliberately.
        """
        desc = ss.describe_storage_schema()
        assert desc["version"] == 2
        assert desc["vault"]["collection"] == "vault_docs"
        assert desc["code"]["collection"] == "codebase_docs"
        assert desc["document"]["collection"] == "document_docs"

    def test_descriptor_dense_vector_is_effective(self) -> None:
        desc = ss.describe_storage_schema()
        dense = desc["vault"]["vectors"]["dense"]
        assert dense["name"] == ss.DENSE_VECTOR_NAME
        assert dense["distance"] == ss.DENSE_DISTANCE
        # The effective dim is an int and positive (default or config override).
        assert isinstance(dense["dim"], int) and dense["dim"] > 0
        # vault and code share the same dense vector.
        assert desc["code"]["vectors"]["dense"] == dense

    def test_descriptor_payload_fields_match_the_persisted_payloads(self) -> None:
        """The advertised field list equals what the writer actually persists.

        Compared against the payloads the production builders produce, not
        against the TypedDicts: ``payload_fields`` is itself derived from those
        same ``__annotations__``, so a TypedDict-vs-descriptor comparison
        restates one source against itself and passes for any field added to
        it. The builders are an independent statement of the same contract -
        they are what a reader actually finds on a point - so a field declared
        but never written, or written but never advertised, fails here.

        Sorted rather than positional: field ORDER is not part of the wire
        contract (a consumer reads by key), so pinning it would fail on a
        cosmetic reorder while proving nothing extra.
        """
        desc = ss.describe_storage_schema()
        doc = VaultDocument(
            id="adr/overview",
            path="adr/overview.md",
            doc_type="adr",
            feature="demo",
            date="2026-06-27",
            tags=["#adr"],
            related=["[[x]]"],
            title="Overview",
            content="body",
            status="accepted",
        )
        # Ordinal 0 carrying a doc_content is the only chunk shape that writes
        # the NotRequired ``doc_content``, so it is the one shape that
        # exercises the whole advertised chunk field set.
        chunk = VaultChunk(
            doc_id=doc.id,
            ordinal=0,
            chunk_count=1,
            text="chunk text",
            path=doc.path,
            doc_type=doc.doc_type,
            feature=doc.feature,
            date=doc.date,
            tags=doc.tags,
            related=doc.related,
            title=doc.title,
            status=doc.status,
            doc_content=doc.content,
        )
        code = CodeChunk(
            id="src/main.py:1-2",
            path="src/main.py",
            language="python",
            content="x = 1",
            line_start=1,
            line_end=2,
        )
        assert sorted(desc["vault"]["payload_fields"]["document"]) == sorted(
            _vault_doc_payload(doc)
        )
        assert sorted(desc["vault"]["payload_fields"]["chunk"]) == sorted(
            _vault_chunk_payload(chunk)
        )
        assert sorted(desc["code"]["payload_fields"]["chunk"]) == sorted(
            _code_chunk_payload(code)
        )

    def test_descriptor_advertises_the_pinned_index_sets(self) -> None:
        """The advertised index sets are pinned to explicit literals.

        The module tuples are what the descriptor is built from, so comparing
        the two restates one source against itself and admits any field added
        to either. The index set is a wire contract a consumer plans its
        queries against, and a change to it that alters query semantics is a
        declared breaking change, so it is mirrored here deliberately rather
        than absorbed silently.
        """
        desc = ss.describe_storage_schema()
        assert desc["vault"]["indexes"] == {
            "keyword": ["doc_type", "feature", "date", "tags", "doc_id"],
            "integer": ["chunk_ordinal"],
        }
        assert desc["code"]["indexes"] == {
            "keyword": [
                "path",
                "language",
                "function_name",
                "class_name",
                "node_type",
                "preprocessor_id",
                "locator_kind",
                "locator_value_str",
                "domain",
            ],
            "integer": ["line_start", "locator_value_int"],
        }
        assert desc["document"]["indexes"] == {
            "keyword": [
                "source_path",
                "content_fingerprint",
                "extractor_id",
                "extractor_version",
                "locator_kind",
                "locator_value_str",
            ],
            "integer": ["unit_ordinal", "locator_value_int"],
        }

    def test_descriptor_is_json_serialisable(self) -> None:
        import json

        json.dumps(ss.describe_storage_schema())


class TestAssertCompatible:
    """assert_compatible applies the version/dimension/vector-name rules."""

    def _descriptor(self, *, version: int = 1, dim: int = 1024) -> dict[str, object]:
        return {
            "version": version,
            "vault": {"vectors": {"dense": {"name": "dense", "dim": dim}}},
        }

    def test_matching_descriptor_is_compatible(self) -> None:
        verdict = ss.assert_compatible(
            self._descriptor(version=1, dim=1024),
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is True
        assert verdict["reason"] == ""

    def test_older_version_is_compatible(self) -> None:
        # A consumer built against v2 reads a v1 store fine (additive fields).
        verdict = ss.assert_compatible(
            self._descriptor(version=1, dim=1024),
            known_version=2,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is True

    def test_newer_version_degrades(self) -> None:
        verdict = ss.assert_compatible(
            self._descriptor(version=2, dim=1024),
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is False
        assert "newer" in verdict["reason"]

    def test_dimension_mismatch_refuses(self) -> None:
        verdict = ss.assert_compatible(
            self._descriptor(version=1, dim=768),
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is False
        assert "dimension" in verdict["reason"]

    def test_missing_dense_vector_refuses(self) -> None:
        """The refusal comes from the dense-NAME branch, not its neighbour.

        A descriptor with no dense vector at all reaches the dimension check
        too if the name check is skipped, and BOTH messages contain the word
        "dense" - so matching a bare "dense" passes whichever branch fires and
        a deleted name check falls through unnoticed. The name fragment below
        is emitted only by the name branch, and the negative pins that control
        never reached the dimension branch. Do not loosen either: matching only
        "dense" is what made this test vacuous.
        """
        verdict = ss.assert_compatible(
            {"version": 1, "vault": {"vectors": {}}},
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is False
        assert "no dense vector named 'dense'" in verdict["reason"]
        assert "dimension" not in verdict["reason"]

    def test_non_integer_version_refuses(self) -> None:
        verdict = ss.assert_compatible(
            {
                "version": "1",
                "vault": {"vectors": {"dense": {"name": "dense", "dim": 1024}}},
            },
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is False

    def test_live_descriptor_is_self_compatible(self) -> None:
        # The descriptor rag emits must validate against its own version + dim.
        desc = ss.describe_storage_schema()
        verdict = ss.assert_compatible(
            desc,
            known_version=ss.STORAGE_SCHEMA_VERSION,
            expected_dense_dim=desc["vault"]["vectors"]["dense"]["dim"],
        )
        assert verdict["compatible"] is True


class TestSchemaConsistency:
    """Internal invariants of the declared schema (CI-gated drift guards).

    A local-mode Qdrant ignores payload indexes, so the live-collection drift
    test can only read the vector config; these pure invariants are the
    CI-gated guard that an indexed field always names a real payload field and
    that the index tuples carry no accidental duplicate.
    """

    def test_vault_indexes_are_real_payload_fields(self) -> None:
        fields = set(ss.VaultDocPayload.__annotations__) | set(
            ss.VaultChunkPayload.__annotations__
        )
        indexed = set(ss.VAULT_KEYWORD_INDEXES) | set(ss.VAULT_INTEGER_INDEXES)
        assert indexed <= fields, indexed - fields

    def test_code_indexes_are_real_payload_fields(self) -> None:
        fields = set(ss.CodeChunkPayload.__annotations__)
        indexed = set(ss.CODE_KEYWORD_INDEXES) | set(ss.CODE_INTEGER_INDEXES)
        assert indexed <= fields, indexed - fields

    def test_index_tuples_have_no_duplicates(self) -> None:
        for tup in (
            ss.VAULT_KEYWORD_INDEXES,
            ss.VAULT_INTEGER_INDEXES,
            ss.CODE_KEYWORD_INDEXES,
            ss.CODE_INTEGER_INDEXES,
        ):
            assert len(tup) == len(set(tup)), tup

    def test_keyword_and_integer_index_sets_are_disjoint(self) -> None:
        assert not (set(ss.VAULT_KEYWORD_INDEXES) & set(ss.VAULT_INTEGER_INDEXES))
        assert not (set(ss.CODE_KEYWORD_INDEXES) & set(ss.CODE_INTEGER_INDEXES))


def test_store_schema_imports_no_torch() -> None:
    """``import vaultspec_rag.store_schema`` must load no Torch.

    The descriptor is advertised on the torch-free ``/readiness`` path, so the
    module must stay a neutral leaf. Checked in a *fresh* interpreter subprocess
    so a torch-loading test elsewhere in the session cannot leave torch resident
    in ``sys.modules`` and mask a regression (mirrors the index-worker and MCP
    lazy-import guards).
    """
    assert_fresh_import_excludes(import_probe_source("vaultspec_rag.store_schema"))
