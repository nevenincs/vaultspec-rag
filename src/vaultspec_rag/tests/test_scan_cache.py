"""Discovery scan cache: fingerprint keying, TTL, and honest invalidation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._scan_cache import MembershipScanCache

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestMembershipScanCache:
    def test_hit_requires_matching_fingerprint(self) -> None:
        cache: MembershipScanCache[str] = MembershipScanCache()
        cache.put("fp-1", "walk-1")
        assert cache.get("fp-1") == "walk-1"
        # A membership-affecting config change produces a new fingerprint,
        # which must miss rather than serve the other policy's walk.
        assert cache.get("fp-2") is None

    def test_ttl_expiry_defers_but_never_hides(self) -> None:
        cache: MembershipScanCache[str] = MembershipScanCache(ttl_seconds=0.05)
        cache.put("fp", "walk")
        assert cache.get("fp") == "walk"
        time.sleep(0.06)
        # Past the TTL the slot must miss - a cache that never expired could
        # hide an unreported create or delete forever.
        assert cache.get("fp") is None

    def test_invalidate_clears_the_slot(self) -> None:
        cache: MembershipScanCache[str] = MembershipScanCache()
        cache.put("fp", "walk")
        cache.invalidate()
        assert cache.get("fp") is None

    def test_put_replaces_the_previous_fingerprint(self) -> None:
        cache: MembershipScanCache[str] = MembershipScanCache()
        cache.put("fp-1", "walk-1")
        cache.put("fp-2", "walk-2")
        assert cache.get("fp-1") is None
        assert cache.get("fp-2") == "walk-2"


class TestCodeDiscoveryScanCache:
    """The real walk is cached, bounded-stale, and re-observed on demand."""

    def test_repeat_scan_is_served_and_invalidate_reobserves(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        discovery = CodeContentDiscovery(tmp_path)
        policy = discovery.resolve_policy()

        first = discovery.scan_content(policy, sample_limit=100)
        assert [p.name for p in first.files] == ["a.py"]

        # A file created after the walk is hidden by the cached result -
        # the bounded staleness the TTL and invalidation exist to limit.
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        cached = discovery.scan_content(policy, sample_limit=100)
        assert [p.name for p in cached.files] == ["a.py"]

        # Invalidation (what a scoped run does on a create or delete)
        # re-observes membership immediately.
        discovery.invalidate_scan_cache()
        fresh = discovery.scan_content(policy, sample_limit=100)
        assert sorted(p.name for p in fresh.files) == ["a.py", "b.py"]

    def test_execution_preflight_reobserves_membership(
        self,
        tmp_path: Path,
    ) -> None:
        """A fresh execution preflight must see a create since the last walk.

        The preflight is the membership observation the run it authorizes
        diffs and publishes claims from; served from a cached walk, an
        unscoped incremental after a create diffs clean against the manifest
        and reports "no changes" over a file it never saw.
        """
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        discovery = CodeContentDiscovery(tmp_path)

        first = discovery.preflight_content(sample_limit=100)
        assert [p.name for p in first.scan.files] == ["a.py"]

        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        fresh = discovery.preflight_content(sample_limit=100)
        assert sorted(p.name for p in fresh.scan.files) == ["a.py", "b.py"]

    def test_document_execution_preflight_reobserves_membership(
        self,
        tmp_path: Path,
    ) -> None:
        """The document preflight walks fresh for the same reason as code."""
        from typing import Any, cast

        from ..indexer._content_policy import (
            ContentKind,
            ContentRoute,
            RootContentPolicy,
            SourceProfileVersion,
        )
        from ..indexer._document_indexer import DocumentIndexer

        manuals = tmp_path / "manuals"
        manuals.mkdir()
        (manuals / "a.txt").write_text("first\n", encoding="utf-8")
        indexer = DocumentIndexer(
            tmp_path,
            cast("Any", None),
            cast("Any", None),
            content_policy=RootContentPolicy(
                SourceProfileVersion.CONVENTIONAL_V1,
                (ContentRoute("manuals/**", ContentKind.DOCUMENT),),
            ),
        )

        first = indexer.preflight_content()
        assert [p.name for p in first.files] == ["a.txt"]

        (manuals / "b.txt").write_text("second\n", encoding="utf-8")
        fresh = indexer.preflight_content()
        assert sorted(p.name for p in fresh.files) == ["a.txt", "b.txt"]

    def test_narrower_sample_budget_is_served_from_the_wide_walk(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        discovery = CodeContentDiscovery(tmp_path)
        policy = discovery.resolve_policy()

        wide = discovery.scan_content(policy, sample_limit=100)
        narrow = discovery.scan_content(policy, sample_limit=0)
        assert narrow.files == wide.files
        assert narrow.samples == ()

    def test_wider_sample_budget_rescans_when_samples_were_truncated(
        self,
        tmp_path: Path,
    ) -> None:
        for i in range(3):
            (tmp_path / f"m{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        discovery = CodeContentDiscovery(tmp_path)
        policy = discovery.resolve_policy()

        narrow = discovery.scan_content(policy, sample_limit=1)
        assert len(narrow.samples) == 1
        # One retained sample cannot honestly serve a wider budget; the
        # wider request must walk again rather than under-report samples.
        wide = discovery.scan_content(policy, sample_limit=100)
        assert len(wide.samples) > 1
        assert wide.files == narrow.files
