"""Integration coverage for policy-driven code-content discovery parity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ...indexer import CodebaseIndexer
from ...indexer._content_policy import (
    AdmissionReason,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def test_full_and_scoped_discovery_share_code_admission(tmp_path: Path) -> None:
    (tmp_path / ".vault").mkdir()
    sources = {
        "p0/alpha.py": "def alpha() -> str:\n    return 'alpha'\n",
        "p1/beta.ts": "export const beta: string = 'beta';\n",
        "p2/options.toml": "enabled = true\n",
        "p3/notes.md": "# Notes\n",
        "p4/schema.xsd": "<schema/>\n",
        "p5/table.xlsx": "not a source workbook\n",
    }
    paths: dict[str, Path] = {}
    for relative, content in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths[relative] = path

    policy = RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("p4/schema.xsd", ContentKind.DOCUMENT),),
    )
    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
        content_policy=policy,
    )
    resolved = indexer._resolve_operation_policy()

    full_scan = indexer.scan_content(sample_limit=len(sources))
    full = {
        path.relative_to(tmp_path).as_posix() for path in full_scan.files
    }
    scoped, rejected = indexer._scan_changed_paths(
        paths.values(),
        NullProgressReporter(),
        resolved,
    )

    admitted = {"p0/alpha.py", "p1/beta.ts"}
    assert full == admitted
    assert set(indexer.scan_files()) == set(full_scan.files)
    assert set(scoped) == admitted
    assert rejected == set(sources) - admitted
    assert full_scan.policy_fingerprint == resolved.fingerprints.snapshot
    assert sum(item.count for item in full_scan.counts) == len(sources)

    dispositions = {
        item.path: item for item in full_scan.samples
    }
    assert dispositions["p0/alpha.py"].reason is AdmissionReason.SOURCE_PROFILE
    assert dispositions["p1/beta.ts"].reason is AdmissionReason.SOURCE_PROFILE
    assert dispositions["p2/options.toml"].reason is (
        AdmissionReason.SOURCE_PROFILE_EXCLUDED
    )
    assert not dispositions["p2/options.toml"].admitted
    assert dispositions["p3/notes.md"].reason is (
        AdmissionReason.SOURCE_PROFILE_EXCLUDED
    )
    assert not dispositions["p3/notes.md"].admitted
    assert dispositions["p4/schema.xsd"].kind is ContentKind.DOCUMENT
    assert dispositions["p4/schema.xsd"].admitted
    assert dispositions["p4/schema.xsd"].reason is AdmissionReason.EXPLICIT_ROUTE
    assert dispositions["p5/table.xlsx"].reason is (
        AdmissionReason.SOURCE_PROFILE_EXCLUDED
    )
    assert not dispositions["p5/table.xlsx"].admitted
