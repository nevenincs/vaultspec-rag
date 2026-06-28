"""Unit tests for the storage-schema contract module.

Exercises the wire descriptor and the consumer compatibility helper, and proves
the module stays a torch-free leaf so the process-wide ``/readiness`` report can
advertise the descriptor without loading a model.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from vaultspec_rag import store_schema as ss

pytestmark = [pytest.mark.unit]


class TestDescriptor:
    """describe_storage_schema builds the bounded wire descriptor."""

    def test_descriptor_carries_version_and_collections(self) -> None:
        desc = ss.describe_storage_schema()
        assert desc["version"] == ss.STORAGE_SCHEMA_VERSION
        assert desc["vault"]["collection"] == ss.VAULT_COLLECTION
        assert desc["code"]["collection"] == ss.CODE_COLLECTION

    def test_descriptor_dense_vector_is_effective(self) -> None:
        desc = ss.describe_storage_schema()
        dense = desc["vault"]["vectors"]["dense"]
        assert dense["name"] == ss.DENSE_VECTOR_NAME
        assert dense["distance"] == ss.DENSE_DISTANCE
        # The effective dim is an int and positive (default or config override).
        assert isinstance(dense["dim"], int) and dense["dim"] > 0
        # vault and code share the same dense vector.
        assert desc["code"]["vectors"]["dense"] == dense

    def test_descriptor_payload_fields_match_typeddicts(self) -> None:
        desc = ss.describe_storage_schema()
        assert desc["vault"]["payload_fields"]["document"] == list(
            ss.VaultDocPayload.__annotations__
        )
        assert desc["vault"]["payload_fields"]["chunk"] == list(
            ss.VaultChunkPayload.__annotations__
        )
        assert desc["code"]["payload_fields"]["chunk"] == list(
            ss.CodeChunkPayload.__annotations__
        )

    def test_descriptor_indexes_match_tuples(self) -> None:
        desc = ss.describe_storage_schema()
        assert desc["vault"]["indexes"]["keyword"] == list(ss.VAULT_KEYWORD_INDEXES)
        assert desc["vault"]["indexes"]["integer"] == list(ss.VAULT_INTEGER_INDEXES)
        assert desc["code"]["indexes"]["keyword"] == list(ss.CODE_KEYWORD_INDEXES)
        assert desc["code"]["indexes"]["integer"] == list(ss.CODE_INTEGER_INDEXES)

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
        verdict = ss.assert_compatible(
            {"version": 1, "vault": {"vectors": {}}},
            known_version=1,
            expected_dense_dim=1024,
        )
        assert verdict["compatible"] is False
        assert "dense" in verdict["reason"]

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
    code = (
        "import sys\n"
        "import vaultspec_rag.store_schema\n"
        "heavy = sorted(\n"
        "    m for m in sys.modules if m == 'torch' or m.startswith('torch.')\n"
        ")\n"
        "assert not heavy, heavy\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
