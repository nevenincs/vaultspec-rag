"""Unit tests for storage-namespace survey classification.

Pure logic: no GPU, no Qdrant, no service. Exercises grouping by prefix
and live/orphaned/unknown classification against a synthetic manifest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..storage_manifest import ManifestEntry
from ..storage_survey import classify_namespaces

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _entry(prefix: str, root: str) -> ManifestEntry:
    return ManifestEntry(prefix=prefix, root=root, backend="server")


def test_live_orphaned_unknown(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    gone_root = tmp_path / "gone"  # never created -> orphaned

    manifest = {
        "raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(live_root)),
        "rbbbbbbbbbbbb_": _entry("rbbbbbbbbbbbb_", str(gone_root)),
    }
    names = [
        "raaaaaaaaaaaa_vault_docs",
        "raaaaaaaaaaaa_codebase_docs",
        "rbbbbbbbbbbbb_vault_docs",
        "rcccccccccccc_codebase_docs",  # not in manifest -> unknown
    ]
    surveys = classify_namespaces(names, manifest)
    by_prefix = {s.prefix: s for s in surveys}

    assert by_prefix["raaaaaaaaaaaa_"].status == "live"
    assert by_prefix["raaaaaaaaaaaa_"].root == str(live_root)
    assert by_prefix["raaaaaaaaaaaa_"].collections == [
        "raaaaaaaaaaaa_codebase_docs",
        "raaaaaaaaaaaa_vault_docs",
    ]
    assert by_prefix["rbbbbbbbbbbbb_"].status == "orphaned"
    assert by_prefix["rcccccccccccc_"].status == "unknown"
    assert by_prefix["rcccccccccccc_"].root is None


def test_actionable_states_sort_first(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    manifest = {"raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(live_root))}
    names = [
        "raaaaaaaaaaaa_vault_docs",  # live
        "rdddddddddddd_vault_docs",  # unknown
    ]
    surveys = classify_namespaces(names, manifest)
    # Unknown (actionable) must come before live.
    assert surveys[0].status == "unknown"
    assert surveys[-1].status == "live"


def test_counts_and_footprint_aggregate(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    manifest = {"raaaaaaaaaaaa_": _entry("raaaaaaaaaaaa_", str(root))}
    names = ["raaaaaaaaaaaa_vault_docs", "raaaaaaaaaaaa_codebase_docs"]
    counts = {"raaaaaaaaaaaa_vault_docs": 10, "raaaaaaaaaaaa_codebase_docs": 32}
    sizes = {"raaaaaaaaaaaa_vault_docs": 1000, "raaaaaaaaaaaa_codebase_docs": 2048}
    survey = classify_namespaces(
        names, manifest, point_counts=counts, footprints=sizes
    )[0]
    assert survey.points == 42
    assert survey.footprint_bytes == 3048


def test_non_namespaced_name_is_unknown() -> None:
    # A bare (non-prefixed) name surfaces as its own unknown entry, never dropped.
    surveys = classify_namespaces(["vault_docs"], {})
    assert len(surveys) == 1
    assert surveys[0].status == "unknown"
    assert surveys[0].prefix == "vault_docs"


def test_empty_input() -> None:
    assert classify_namespaces([], {}) == []


# -- extended-length alias normalization and temp-root flagging --


def test_extended_length_alias_hashes_to_same_prefix(tmp_path: Path) -> None:
    r"""A ``\\?\``-prefixed spelling of a root must not mint a second namespace."""
    import sys

    from .._store_models import root_collection_prefix

    if sys.platform != "win32":
        pytest.skip("extended-length path prefixes are Windows-only")
    plain = root_collection_prefix(tmp_path)
    aliased = root_collection_prefix("\\\\?\\" + str(tmp_path))
    assert aliased == plain


def test_unc_extended_length_alias_normalizes() -> None:
    r"""The ``\\?\UNC\`` form reduces to the plain UNC spelling before hashing."""
    import sys

    from .._store_models import root_collection_prefix

    if sys.platform != "win32":
        pytest.skip("extended-length path prefixes are Windows-only")
    plain = root_collection_prefix(r"\\server\share\proj")
    aliased = root_collection_prefix(r"\\?\UNC\server\share\proj")
    assert aliased == plain


def test_temp_rooted_flags_tempdir_descendants(tmp_path: Path) -> None:
    import pathlib
    import tempfile

    from ..storage_survey import is_temp_rooted

    inside = pathlib.Path(tempfile.gettempdir()) / "vaultspec-livetest-xyz"
    assert is_temp_rooted(str(inside)) is True
    assert is_temp_rooted(str(inside / "nested" / "deeper")) is True
    # tmp_path is pytest's basetemp, itself under the OS temp dir.
    assert is_temp_rooted(str(tmp_path)) is True


def test_temp_rooted_false_for_project_roots_and_none() -> None:
    from ..storage_survey import is_temp_rooted

    assert is_temp_rooted(None) is False
    assert is_temp_rooted(r"Y:\code\real-project") is False
