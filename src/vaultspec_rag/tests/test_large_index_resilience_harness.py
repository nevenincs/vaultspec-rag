"""Deterministic corpus preparation for the real large-index harness."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from .benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    main,
    prepare_corpus,
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
