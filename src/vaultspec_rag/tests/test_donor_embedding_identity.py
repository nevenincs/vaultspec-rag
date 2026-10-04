"""Stored donor evidence must identify the actual canonical embedding input."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest
from tree_sitter_language_pack import get_parser

from .._store_models import (
    CodeChunk,
    DocumentChunk,
    DocumentPayload,
    VaultChunk,
    _code_chunk_payload,
    _vault_chunk_payload,
)
from ..indexer._chunk_worker import chunk_with_ast
from ..indexer._reuse import DonorReuseContext
from ..indexer._slicing import code_embed_input, code_embed_text
from ..store_runtime import DonorPoint

if TYPE_CHECKING:
    from ..store_runtime import VaultStore

pytestmark = pytest.mark.unit


@dataclass
class _Transport:
    points: dict[str, DonorPoint]

    def retrieve_donor_points(
        self, collection: str, point_ids: list[str]
    ) -> dict[str, DonorPoint]:
        assert collection == "donor"
        return {
            point_id: self.points[point_id]
            for point_id in point_ids
            if point_id in self.points
        }


def _context(point_id: str, payload: dict[str, object]) -> DonorReuseContext:
    point = DonorPoint(
        dense=[0.125] * 1024,
        sparse_indices=[7],
        sparse_values=[1.0],
        payload=payload,
    )
    return DonorReuseContext(
        cast("VaultStore", _Transport({point_id: point})), ("donor",)
    )


def _code_chunk() -> CodeChunk:
    return CodeChunk("id", "src/sample.py", "python", "return 1", 2, 2)


def _code_payload(chunk: CodeChunk) -> dict[str, object]:
    return dict(_code_chunk_payload(chunk))


@pytest.fixture
def python_grammar() -> None:
    """Load the real grammar before chunking; an unavailable prerequisite fails."""
    get_parser("python")


@pytest.mark.usefixtures("python_grammar")
def test_actual_ast_same_id_body_changed_class_refuses_reuse() -> None:
    # Bypassing donor-evidence equality failed the refusal; byte restoration passed.
    methods = "".join(
        f"    def method_{index}(self):\n"
        f"        value = '{'x' * 1000}'\n        return value\n"
        for index in range(6)
    )
    donor_chunks = chunk_with_ast(
        "class Alpha:\n" + methods, "src/context.py", "python", "python"
    )
    target_chunks = chunk_with_ast(
        "class Bravo:\n" + methods, "src/context.py", "python", "python"
    )
    donor_methods = {chunk.id: chunk for chunk in donor_chunks if chunk.function_name}
    target_methods = [chunk for chunk in target_chunks if chunk.function_name]
    assert len(target_methods) == len(donor_methods) == 6, (
        "fixture must use six actual AST methods"
    )
    for target in target_methods:
        donor = donor_methods[target.id]
        assert donor.content == target.content and donor.id == target.id
        assert donor.class_name == "Alpha" and target.class_name == "Bravo"
        assert code_embed_text(donor) != code_embed_text(target)
        context = _context(donor.id, _code_payload(donor))
        assert context.adopt_verified_vectors([target], sparse_required=True) == [
            False
        ], "same-ID method with changed enclosing class adopted incompatible vectors"
        assert (
            not target.vector and not target.sparse_indices and not target.sparse_values
        )
        identical = replace(donor, vector=[], sparse_indices=[], sparse_values=[])
        assert context.adopt_verified_vectors([identical], sparse_required=True) == [
            True
        ], "identical complete CODE input stopped reusing donor vectors"
        assert identical.vector == [0.125] * 1024
        assert identical.sparse_indices == [7] and identical.sparse_values == [1.0]


@pytest.mark.parametrize("field", ["path", "class_name", "function_name", "content"])
def test_each_canonical_code_input_component_refuses_mismatch(field: str) -> None:
    target = replace(_code_chunk(), class_name="Alpha", function_name="method")
    payload = _code_payload(target)
    payload[field] = str(payload[field]) + "-changed"
    context = _context(target.id, payload)
    assert context.adopt_verified_vectors([target], sparse_required=True) == [False], (
        f"changed CODE {field} was accepted as identical embedding input"
    )
    assert not target.vector


@pytest.mark.parametrize("field", ["path", "class_name", "function_name", "content"])
def test_missing_code_input_fields_fail_closed(field: str) -> None:
    target = _code_chunk()
    payload = _code_payload(target)
    del payload[field]
    context = _context(target.id, payload)
    assert context.adopt_verified_vectors([target], sparse_required=True) == [False], (
        f"unknown CODE {field} was inferred instead of refusing reuse"
    )
    assert not target.vector


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", None),
        ("path", 9),
        ("class_name", False),
        ("class_name", []),
        ("function_name", 9),
        ("function_name", {}),
        ("content", None),
        ("content", 9),
    ],
)
def test_malformed_code_input_fields_fail_closed(field: str, value: object) -> None:
    target = _code_chunk()
    payload = _code_payload(target)
    payload[field] = value
    context = _context(target.id, payload)
    assert context.adopt_verified_vectors([target], sparse_required=True) == [False], (
        f"malformed CODE {field} was accepted instead of refusing reuse"
    )
    assert not target.vector


@pytest.mark.parametrize(
    ("class_name", "function_name"),
    [(None, None), ("Alpha", None), (None, "method"), ("Alpha", "method")],
)
def test_explicit_optional_context_and_shared_encoder_recipe_reuse(
    class_name: str | None, function_name: str | None
) -> None:
    target = replace(_code_chunk(), class_name=class_name, function_name=function_name)
    expected_header = " :: ".join(
        value for value in (target.path, class_name, function_name) if value
    )
    assert code_embed_text(target) == expected_header + "\n" + target.content, (
        "shared CODE assembler changed the canonical encoder recipe"
    )
    assert code_embed_text(target) == code_embed_input(
        target.path, class_name, function_name, target.content
    )
    context = _context(target.id, _code_payload(target))
    assert context.adopt_verified_vectors([target], sparse_required=True) == [True], (
        "explicit optional CODE context was rejected despite identical input"
    )
    assert target.vector == [0.125] * 1024


def test_vault_title_body_and_document_content_contracts_remain() -> None:
    vault = VaultChunk(
        "doc", 0, 1, "body", "note.md", "adr", "feature", "2026-10-03", [], [], "Title"
    )
    context = _context(vault.point_key, dict(_vault_chunk_payload(vault)))
    assert context.adopt_verified_vectors(
        [replace(vault, title="Other")], sparse_required=True
    ) == [False]
    assert context.adopt_verified_vectors([vault], sparse_required=True) == [True]
    doc = DocumentChunk(
        "doc-id", DocumentPayload("report.pdf", 0, "fingerprint", "body", title="Title")
    )
    context = _context(doc.id, {"content": "body"})
    assert context.adopt_verified_vectors([doc], sparse_required=True) == [True]
    changed = replace(doc, payload=replace(doc.payload, content="different"), vector=[])
    assert context.adopt_verified_vectors([changed], sparse_required=True) == [False]
    assert not changed.vector
