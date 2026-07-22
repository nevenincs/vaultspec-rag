"""Unit tests for the preprocess output cache (no GPU).

Exercises D7: content-addressed hit/miss, command-change (version-bump)
invalidation, corrupt-entry tolerance, and clean-rebuild clearing. Real files
under ``tmp_path``; no mocks.
"""

from pathlib import Path

import pytest

from ..indexer._preprocess_cache import (
    PreprocessCacheIdentity,
    clear_preprocess_cache,
    preprocess_cache_dir,
    read_cached_output,
    write_cached_output,
)
from ..indexer._preprocess_schema import PreprocOutput

pytestmark = [pytest.mark.unit]


def _output(text: str = "extracted") -> PreprocOutput:
    return PreprocOutput.model_validate(
        {
            "schema_version": 1,
            "preprocessor_id": "pdf",
            "preprocessor_version": "1.0",
            "source_path": "docs/a.pdf",
            "text": text,
        }
    )


def _identity(
    source_hash: str = "hash1",
    execution_fingerprint: str = "extract-v1",
    source_path: str = "docs/a.pdf",
    *,
    path_independent: bool = False,
) -> PreprocessCacheIdentity:
    return PreprocessCacheIdentity(
        source_path=source_path,
        source_hash=source_hash,
        execution_fingerprint=execution_fingerprint,
        path_independent=path_independent,
    )


def test_miss_on_empty_cache(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    assert read_cached_output(root, _identity()) is None


def test_write_then_hit(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    identity = _identity()
    write_cached_output(root, identity, _output("hello"))
    hit = read_cached_output(root, identity)
    assert hit is not None
    assert hit.text == "hello"


def test_different_source_hash_misses(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    write_cached_output(root, _identity(), _output())
    assert read_cached_output(root, _identity(source_hash="hash2")) is None


def test_path_dependent_cache_does_not_alias_identical_files(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    write_cached_output(root, _identity(), _output())
    assert read_cached_output(
        root,
        _identity(source_path="docs/b.pdf"),
    ) is None


def test_path_independent_cache_reuse_requires_explicit_identity(
    tmp_path: Path,
) -> None:
    root = preprocess_cache_dir(tmp_path)
    first = _identity(path_independent=True)
    second = _identity(source_path="docs/b.pdf", path_independent=True)
    write_cached_output(root, first, _output())
    assert read_cached_output(root, second) is not None


def test_command_change_invalidates(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    original = _identity(execution_fingerprint="extract-v1")
    write_cached_output(root, original, _output("old"))
    # Same source, bumped extractor command -> a fresh key -> a miss.
    assert (
        read_cached_output(root, _identity(execution_fingerprint="extract-v2"))
        is None
    )
    # The original entry still hits on its own command.
    assert read_cached_output(root, original) is not None


def test_corrupt_entry_is_a_miss(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    identity = _identity()
    write_cached_output(root, identity, _output())
    # Corrupt every cached json file in place.
    for json_file in root.rglob("*.json"):
        json_file.write_text("{ not valid", encoding="utf-8")
    assert read_cached_output(root, identity) is None


def test_clear_removes_subtree(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    write_cached_output(root, _identity(), _output())
    assert root.exists()
    clear_preprocess_cache(root)
    assert not root.exists()
    # Clearing an already-absent cache is a no-op.
    clear_preprocess_cache(root)


def test_units_output_round_trips(tmp_path: Path) -> None:
    root = preprocess_cache_dir(tmp_path)
    output = PreprocOutput.model_validate(
        {
            "schema_version": 1,
            "preprocessor_id": "xlsx",
            "preprocessor_version": "2.0",
            "source_path": "book.xlsx",
            "units": [
                {
                    "text": "A1 B1",
                    "anchor": "book.xlsx#Sheet1!1",
                    "locator": {"kind": "sheet", "value": "Sheet1"},
                }
            ],
        }
    )
    identity = _identity(
        source_hash="h",
        execution_fingerprint="xlsx-v2",
        source_path="book.xlsx",
    )
    write_cached_output(root, identity, output)
    hit = read_cached_output(root, identity)
    assert hit is not None
    assert hit.units is not None
    assert hit.units[0].locator is not None
    assert hit.units[0].locator.value == "Sheet1"
