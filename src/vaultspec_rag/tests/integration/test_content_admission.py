"""Integration coverage for policy-driven code-content discovery parity."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from ...indexer import CodebaseIndexer
from ...indexer._content_policy import (
    AdmissionReason,
    ContentKind,
)
from ...indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from ...progress import NullProgressReporter
from .._cli_helpers import app, runner

if TYPE_CHECKING:
    from ...indexer._codebase_indexer import ContentScanResult
    from ...indexer._content_discovery import AdmissionSample

pytestmark = [pytest.mark.integration]


def _admission_json(scan: ContentScanResult) -> dict[str, object]:
    return {
        "policy_fingerprint": scan.policy_fingerprint,
        "counts": [
            {
                "kind": count.kind.value if count.kind is not None else None,
                "admitted": count.admitted,
                "reason": count.reason.value,
                "count": count.count,
            }
            for count in scan.counts
        ],
        "samples": [
            {
                "path": sample.path,
                "kind": sample.kind.value if sample.kind is not None else None,
                "admitted": sample.admitted,
                "reason": sample.reason.value,
            }
            for sample in scan.samples
        ],
    }


def _write_admission_sources(tmp_path: Path) -> dict[str, Path]:
    """Create a mixed routed and unrouted source set for parity assertions."""
    (tmp_path / ".vault").mkdir()
    (tmp_path / ".vaultspec").mkdir()
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
    config_path = tmp_path / PREPROCESS_CONFIG_FILENAME
    config_path.write_text(
        "\n".join(
            (
                "version = 2",
                "[[rule]]",
                'pattern = "p4/schema.xsd"',
                'target = "document"',
                'extractor_version = "parity-v1"',
                'command = "unused {path}"',
                'on_error = "skip"',
                "",
            )
        ),
        encoding="utf-8",
    )
    paths[PREPROCESS_CONFIG_FILENAME] = config_path
    return paths


def _assert_discovery_parity(
    indexer: CodebaseIndexer,
    paths: dict[str, Path],
    tmp_path: Path,
) -> tuple[ContentScanResult, set[str]]:
    """Assert full and scoped discovery agree on admitted source paths."""
    resolved = indexer.resolve_policy_snapshot()
    full_scan = indexer.scan_content(sample_limit=len(paths))
    full = {path.relative_to(tmp_path).as_posix() for path in full_scan.files}
    scoped, rejected = indexer._scan_changed_paths(
        paths.values(),
        NullProgressReporter(),
        resolved,
    )
    admitted = {"p0/alpha.py", "p1/beta.ts"}
    assert full == admitted
    assert set(indexer.scan_files()) == set(full_scan.files)
    assert set(scoped) == admitted
    assert rejected == set(paths) - admitted
    assert full_scan.policy_fingerprint == resolved.fingerprints.snapshot
    assert sum(item.count for item in full_scan.counts) == len(paths)
    return full_scan, admitted


def _assert_disposition_parity(
    indexer: CodebaseIndexer,
    paths: dict[str, Path],
    full_scan: ContentScanResult,
) -> dict[str, AdmissionSample]:
    """Assert full-scan counts and samples match per-path classification."""
    resolved = indexer.resolve_policy_snapshot()
    dispositions = {item.path: item for item in full_scan.samples}
    scoped_dispositions = {
        relative: indexer._classify_file(path, relative, resolved).disposition
        for relative, path in paths.items()
    }
    assert Counter(
        (disposition.kind, disposition.admitted, disposition.reason)
        for disposition in scoped_dispositions.values()
    ) == Counter(
        {
            (count.kind, count.admitted, count.reason): count.count
            for count in full_scan.counts
        }
    )
    assert {
        relative: (item.kind, item.admitted, item.reason)
        for relative, item in dispositions.items()
    } == {
        relative: (item.kind, item.admitted, item.reason)
        for relative, item in scoped_dispositions.items()
    }
    return dispositions


def _assert_expected_dispositions(dispositions: dict[str, AdmissionSample]) -> None:
    """Assert the representative profile and explicit-route decisions."""
    alpha = dispositions["p0/alpha.py"]
    beta = dispositions["p1/beta.ts"]
    options = dispositions["p2/options.toml"]
    notes = dispositions["p3/notes.md"]
    schema = dispositions["p4/schema.xsd"]
    workbook = dispositions["p5/table.xlsx"]
    assert alpha.reason is AdmissionReason.SOURCE_PROFILE
    assert beta.reason is AdmissionReason.SOURCE_PROFILE
    assert options.reason is AdmissionReason.SOURCE_PROFILE_EXCLUDED
    assert not options.admitted
    assert notes.reason is AdmissionReason.SOURCE_PROFILE_EXCLUDED
    assert not notes.admitted
    assert schema.kind is ContentKind.DOCUMENT
    assert schema.admitted
    assert schema.reason is AdmissionReason.EXPLICIT_ROUTE
    assert workbook.reason is AdmissionReason.SOURCE_PROFILE_EXCLUDED
    assert not workbook.admitted


def _assert_public_admission_views(
    tmp_path: Path,
    full_scan: ContentScanResult,
    admitted: set[str],
    path_count: int,
) -> None:
    """Assert API, service, and CLI projections retain the same scan."""
    from ...api import scan_codebase
    from ...jobs import scan_code_index_preflight

    api_scan = scan_codebase(tmp_path, sample_limit=path_count)
    service_scan = scan_code_index_preflight(tmp_path)
    assert api_scan == full_scan
    assert service_scan == full_scan
    cli_result = runner.invoke(
        app,
        [
            "--target",
            str(tmp_path),
            "index",
            "--type",
            "code",
            "--dry-run",
            "--json",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_data = json.loads(cli_result.output)["data"]
    assert cli_data["count"] == len(admitted)
    assert {Path(path).as_posix() for path in cli_data["files"]} == admitted
    assert cli_data["admission"] == _admission_json(full_scan)


def test_full_and_scoped_discovery_share_code_admission(tmp_path: Path) -> None:
    paths = _write_admission_sources(tmp_path)

    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
    )
    full_scan, admitted = _assert_discovery_parity(indexer, paths, tmp_path)
    dispositions = _assert_disposition_parity(indexer, paths, full_scan)
    _assert_expected_dispositions(dispositions)
    _assert_public_admission_views(tmp_path, full_scan, admitted, len(paths))
