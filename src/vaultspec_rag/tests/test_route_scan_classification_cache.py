"""Actual route scanner and classifier with an offline paged backend seam."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, call

import pytest

from ..indexer._content_policy import (
    ClassifiedContent,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._resolved_policy import DecoderPolicy, ResolvedIndexPolicy
from ..indexer._route_migration import iter_stored_route_pages
from ..indexer._run_policy import RunPolicy
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _policy(
    root: Path,
    *,
    routes: tuple[ContentRoute, ...] = (),
    ignores: tuple[str, ...] = (),
) -> ResolvedIndexPolicy:
    return ResolvedIndexPolicy(
        root_dir=root.resolve(),
        policy_schema_version=1,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1, routes),
        preprocess_schema_version=1,
        preprocess_rules=(),
        decoder=DecoderPolicy(),
        execution_mode="default",
        html_strip=False,
        max_emitted_bytes=1_000_000,
        gitignore_patterns=ignores,
        vaultragignore_patterns=(),
        extra_excludes=(),
    )


def _rows(paths: Sequence[str], kind: ContentKind) -> list[dict[str, object]]:
    path_key, id_key = (
        ("path", "chunk_id")
        if kind is ContentKind.CODE
        else ("source_path", "document_id")
    )
    return [
        {
            "id": f"point-{index}",
            "payload": {
                path_key: path,
                id_key: f"chunk-{index}" if index % 2 == 0 else None,
            },
        }
        for index, path in enumerate(paths)
    ]


def _store(pages: list[list[dict[str, object]]], kind: ContentKind) -> Mock:
    store = Mock(spec=VaultStore)
    scroll = (
        store.scroll_code_content
        if kind is ContentKind.CODE
        else store.scroll_document_content
    )
    scroll.side_effect = [
        (page, f"offset-{index + 1}" if index + 1 < len(pages) else None)
        for index, page in enumerate(pages)
    ]
    return store


@pytest.fixture
def classified_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    paths: list[str] = []
    actual = ResolvedIndexPolicy.classify

    def measured(policy: ResolvedIndexPolicy, path: str) -> ClassifiedContent:
        paths.append(path)
        return actual(policy, path)

    monkeypatch.setattr(ResolvedIndexPolicy, "classify", measured)
    return paths


@pytest.fixture
def checkpoint_labels(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    labels: list[str] = []
    actual = RunPolicy.checkpoint

    def measured(policy: RunPolicy, label: str) -> None:
        labels.append(label)
        actual(policy, label)

    monkeypatch.setattr(RunPolicy, "checkpoint", measured)
    return labels


@pytest.mark.parametrize("stored_kind", [ContentKind.CODE, ContentKind.DOCUMENT])
def test_route_scan_reuses_exact_paths_across_pages(
    tmp_path: Path,
    classified_paths: list[str],
    checkpoint_labels: list[str],
    stored_kind: ContentKind,
) -> None:
    paths = [
        "module.py",
        "guide.txt",
        "module.py",
        "Module.py",
        "folder\\module.py",
        "folder/module.py",
        "guide.txt",
    ]
    rows = _rows(paths, stored_kind)
    store = _store([rows[:2], rows[2:5], rows[5:]], stored_kind)
    policy = _policy(
        tmp_path, routes=(ContentRoute("guide.txt", ContentKind.DOCUMENT),)
    )
    pages = list(
        iter_stored_route_pages(
            cast("VaultStore", store),
            policy,
            stored_kind,
            run_policy=RunPolicy(no_progress_timeout_seconds=60),
        )
    )
    # Mutation: bypassing the production cache must repeat these actual calls.
    assert classified_paths == list(dict.fromkeys(paths)), (
        "route scan must reuse exact-path classification across pages"
    )
    flattened = [row for page in pages for row in page]
    assert [row.source_path for row in flattened] == paths
    assert [row.point_id for row in flattened] == [
        f"chunk-{index}" if index % 2 == 0 else f"point-{index}"
        for index in range(len(paths))
    ]
    assert all(row.stored_kind is stored_kind and row.admitted for row in flattened)
    assert [row.current_kind for row in flattened] == [
        ContentKind.DOCUMENT if path == "guide.txt" else ContentKind.CODE
        for path in paths
    ]
    scroll = (
        store.scroll_code_content
        if stored_kind is ContentKind.CODE
        else store.scroll_document_content
    )
    kwargs = {"collection": None} if stored_kind is ContentKind.CODE else {}
    assert scroll.call_args_list == [
        call(limit=256, offset=offset, source_paths=None, **kwargs)
        for offset in (None, "offset-1", "offset-2")
    ]
    assert checkpoint_labels == [
        label
        for _ in range(3)
        for label in (
            f"{stored_kind.value} route page before scroll",
            f"{stored_kind.value} route page after scroll",
        )
    ]


def test_route_scan_evicts_beyond_4096_paths(
    tmp_path: Path, classified_paths: list[str]
) -> None:
    unique = [f"src/module_{index}.py" for index in range(4097)]
    paths = [*unique, unique[0], unique[-1]]
    rows = _rows(paths, ContentKind.CODE)
    store = _store(
        [rows[start : start + 256] for start in range(0, len(rows), 256)],
        ContentKind.CODE,
    )
    pages = list(
        iter_stored_route_pages(
            cast("VaultStore", store), _policy(tmp_path), ContentKind.CODE
        )
    )
    flattened = [row for page in pages for row in page]
    assert [row.source_path for row in flattened] == paths
    assert all(
        row.admitted and row.current_kind is ContentKind.CODE for row in flattened
    )
    # Mutation: an unbounded production cache fails to reclassify the oldest path.
    assert classified_paths == [*unique, unique[0]], (
        "route classification cache must evict beyond 4096 entries"
    )


def test_new_route_scan_reclassifies_its_policy_snapshot(
    tmp_path: Path, classified_paths: list[str]
) -> None:
    paths = ["module.py", "ignored.py"]
    rows = _rows(paths, ContentKind.CODE)
    initial = _policy(tmp_path)
    changed = _policy(
        tmp_path,
        routes=(ContentRoute("module.py", ContentKind.DOCUMENT),),
        ignores=("ignored.py",),
    )
    first, second, third = [
        list(
            iter_stored_route_pages(
                cast("VaultStore", _store([rows], ContentKind.CODE)),
                policy,
                ContentKind.CODE,
            )
        )
        for policy in (initial, initial, changed)
    ]
    assert classified_paths == paths * 3, (
        "every route scan must start with a fresh cache"
    )
    assert first == second
    assert all(
        row.current_kind is ContentKind.CODE and row.admitted for row in first[0]
    )
    assert third[0][0].current_kind is ContentKind.DOCUMENT
    assert third[0][0].admitted
    assert third[0][1].current_kind is None
    assert not third[0][1].admitted


@pytest.mark.parametrize("stored_kind", [ContentKind.CODE, ContentKind.DOCUMENT])
def test_route_scan_filters_malformed_paths_before_classifying(
    tmp_path: Path, classified_paths: list[str], stored_kind: ContentKind
) -> None:
    path_key = "path" if stored_kind is ContentKind.CODE else "source_path"
    payloads: tuple[object, ...] = (
        None,
        [],
        {},
        {path_key: None},
        {path_key: ""},
        {path_key: 7},
    )
    malformed: list[dict[str, object]] = [{"payload": payload} for payload in payloads]
    rows = _rows(["valid.py", "valid.py"], stored_kind)
    store = _store([malformed[:3], malformed[3:], rows], stored_kind)
    pages = list(
        iter_stored_route_pages(
            cast("VaultStore", store), _policy(tmp_path), stored_kind
        )
    )
    assert classified_paths == ["valid.py"]
    assert len(pages) == 1
    assert [row.point_id for row in pages[0]] == ["chunk-0", "point-1"]
