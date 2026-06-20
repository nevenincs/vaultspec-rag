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
