"""Deterministic corpus preparation for the real large-index harness."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

import pytest

from .benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    main,
    prepare_corpus,
    retain_benchmark_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_preparation_is_idempotent_and_production_chunk_exact(tmp_path: Path) -> None:
    spec = CorpusSpec(files=5, chunks_per_file=3)

    first = prepare_corpus(tmp_path, spec)
    second = prepare_corpus(tmp_path, spec)

    assert (first.created_files, first.retained_files) == (5, 0)
    assert (second.created_files, second.retained_files) == (0, 5)
    assert first.source_bytes == second.source_bytes
    marker = cast(
        "dict[str, object]",
        json.loads(
            (tmp_path / ".large-index-resilience-corpus.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert marker["state"] == "ready"
    assert marker["expected_chunks"] == 15


def test_preparation_refuses_marker_dimension_drift(tmp_path: Path) -> None:
    prepare_corpus(tmp_path, CorpusSpec(files=2, chunks_per_file=3))

    with pytest.raises(RuntimeError, match="requested"):
        prepare_corpus(tmp_path, CorpusSpec(files=3, chunks_per_file=3))


def test_prepare_only_command_writes_machine_readable_report(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "prepared.json"

    assert (
        main(
            (
                "--root",
                str(tmp_path / "corpus"),
                "--files",
                "2",
                "--prepare-only",
                "--json",
                str(report_path),
            )
        )
        == 0
    )
    payload = cast(
        "dict[str, object]",
        json.loads(report_path.read_text(encoding="utf-8")),
    )
    corpus = cast("dict[str, object]", payload["corpus"])
    assert corpus["created_files"] == 2
    assert corpus["chunks_per_file"] == 3


def test_benchmark_evidence_is_logged_and_atomically_retained(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    report_dir = tmp_path / "reports"

    with caplog.at_level(
        "INFO",
        logger="vaultspec_rag.tests.benchmarks.bench_large_index_resilience",
    ):
        destination = retain_benchmark_evidence(
            "n-two-n-high-water",
            {"n_chunks": 6, "two_n_chunks": 12},
            report_dir=report_dir,
        )

    assert destination is not None
    assert destination.parent == report_dir
    assert destination.name.startswith("n-two-n-high-water-")
    assert destination.suffix == ".json"
    payload = cast(
        "dict[str, object]",
        json.loads(destination.read_text(encoding="utf-8")),
    )
    assert payload == {
        "schema_version": 1,
        "evidence": "n-two-n-high-water",
        "n_chunks": 6,
        "two_n_chunks": 12,
    }
    assert any('"n_chunks": 6' in record.getMessage() for record in caplog.records)


def test_benchmark_evidence_retention_is_safe_for_concurrent_writers(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "reports"

    def _retain(run: int) -> Path:
        destination = retain_benchmark_evidence(
            "concurrent-search-headroom",
            {"run": run, "observed_headroom_mb": float(run)},
            report_dir=report_dir,
        )
        assert destination is not None
        return destination

    with ThreadPoolExecutor(max_workers=8) as pool:
        destinations = list(pool.map(_retain, range(32)))

    assert len(set(destinations)) == 32
    retained_runs: set[int] = set()
    for destination in destinations:
        payload = cast(
            "dict[str, object]",
            json.loads(destination.read_text(encoding="utf-8")),
        )
        assert payload["schema_version"] == 1
        assert payload["evidence"] == "concurrent-search-headroom"
        run = cast("int", payload["run"])
        retained_runs.add(run)
        assert payload["observed_headroom_mb"] == float(run)
    assert retained_runs == set(range(32))
    assert not list(report_dir.glob("*.tmp"))
