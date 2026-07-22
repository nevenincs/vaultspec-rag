"""Integration coverage for immutable policy snapshots during publication."""

from __future__ import annotations

import json
import os
import shlex
import sys
import textwrap
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, NamedTuple

import pytest

from ...config import EnvVar, reset_config
from ...indexer._code_meta import CONTENT_EPOCH_KEY, MEMBERSHIP_EPOCH_KEY
from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import CodebaseIndexer, IndexResult
    from ...indexer._preprocess_config import PreprocessRule
    from ...indexer._resolved_policy import ResolvedIndexPolicy
    from ...store import VaultStore
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]


class _SnapshotPaths(NamedTuple):
    config: Path
    replacement: Path
    source: Path
    html: Path
    started: Path
    proceed: Path


def _write_snapshot_project(root: Path) -> _SnapshotPaths:
    paths = _SnapshotPaths(
        root / PREPROCESS_CONFIG_FILENAME,
        root / "replacement-policy.toml",
        root / "a_payload.blob",
        root / "z_markup.html",
        root / "extraction-started.flag",
        root / "extraction-continue.flag",
    )
    paths.replacement.write_text(
        "\n".join(
            (
                "version = 2",
                "[[rule]]",
                'pattern = "*.blob"',
                'target = "document"',
                'extractor_version = "replacement-v2"',
                'command = "unused {path}"',
                'on_error = "skip"',
                "priority = 900",
                "[rule.options]",
                'profile = "replacement"',
                "window = 99",
                "",
            )
        ),
        encoding="utf-8",
    )
    extractor = root / "snapshot-extractor.runner"
    extractor.write_text(
        textwrap.dedent(
            """
            import json
            import pathlib
            import sys
            import time

            source, config, replacement, started, proceed = sys.argv[1:]
            pathlib.Path(config).write_text(
                pathlib.Path(replacement).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            pathlib.Path(started).write_text("started", encoding="utf-8")
            deadline = time.monotonic() + 30
            while not pathlib.Path(proceed).exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("test did not release extractor")
                time.sleep(0.02)
            print(json.dumps({
                "schema_version": 1,
                "preprocessor_id": "entry-snapshot-extractor",
                "preprocessor_version": "entry-v1",
                "source_path": source,
                "units": [{
                    "text": "immutable operation snapshot publication marker",
                    "anchor": source + "#unit=entry",
                }],
            }))
            """
        ),
        encoding="utf-8",
    )
    command = " ".join(
        (
            shlex.quote(sys.executable),
            shlex.quote(str(extractor)),
            "{path}",
            shlex.quote(str(paths.config)),
            shlex.quote(str(paths.replacement)),
            shlex.quote(str(paths.started)),
            shlex.quote(str(paths.proceed)),
        )
    )
    paths.config.write_text(
        "\n".join(
            (
                "version = 2",
                "[[rule]]",
                'pattern = "*.blob"',
                'target = "code"',
                'extractor_version = "entry-v1"',
                f"command = {json.dumps(command)}",
                'on_error = "fail"',
                "priority = 17",
                "[rule.options]",
                'profile = "entry"',
                "window = 7",
                "",
            )
        ),
        encoding="utf-8",
    )
    paths.source.write_bytes(b"\x00\x01 snapshot-owned binary input")
    paths.html.write_text(
        "<html><body><section>worker shaping marker "
        "<strong>preserved</strong></section></body></html>",
        encoding="utf-8",
    )
    return paths


@contextmanager
def _snapshot_environment() -> Iterator[str]:
    values = {
        EnvVar.HTML_STRIP.value: "true",
        EnvVar.INDEX_CHUNK_WORKERS.value: "1",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    reset_config()
    try:
        yield EnvVar.HTML_STRIP.value
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


def _cross_mutation_barrier(
    future: Future[IndexResult],
    paths: _SnapshotPaths,
    html_key: str,
) -> IndexResult:
    try:
        deadline = time.monotonic() + 30
        while not paths.started.exists():
            if future.done():
                future.result()
            if time.monotonic() >= deadline:
                raise TimeoutError("extractor did not reach mutation barrier")
            time.sleep(0.02)
        os.environ[html_key] = "false"
        reset_config()
    finally:
        paths.proceed.write_text("continue", encoding="utf-8")
    return future.result(timeout=600)


def _assert_active_snapshot(
    indexer: CodebaseIndexer,
    entry_policy: ResolvedIndexPolicy,
    entry_rule: PreprocessRule,
) -> None:
    """Assert the active indexer retained its operation-entry policy."""
    active_policy = indexer._resolved_policy
    assert active_policy is not None
    assert active_policy == entry_policy
    assert active_policy.fingerprints.snapshot == entry_policy.fingerprints.snapshot
    assert active_policy.classify("a_payload.blob").disposition.kind is ContentKind.CODE
    assert indexer._prep_ctx is not None
    assert indexer._prep_ctx.config.rules == [entry_rule]
    assert indexer._chunk_execution_policy.html_strip


def _assert_published_snapshot(
    indexer: CodebaseIndexer,
    entry_policy: ResolvedIndexPolicy,
) -> None:
    """Assert publication uses entry epochs while fresh resolution observes drift."""
    entry_code = entry_policy.fingerprints_for(ContentKind.CODE)
    published = indexer._read_meta_raw()
    assert published[MEMBERSHIP_EPOCH_KEY] == entry_code.membership
    assert published[CONTENT_EPOCH_KEY] == entry_code.content
    fresh_policy = indexer._resolve_operation_policy()
    fresh_code = fresh_policy.fingerprints_for(ContentKind.CODE)
    assert fresh_policy.fingerprints.snapshot != entry_policy.fingerprints.snapshot
    assert not fresh_policy.html_strip
    assert (
        fresh_policy.classify("a_payload.blob").disposition.kind is ContentKind.DOCUMENT
    )
    assert (
        published[MEMBERSHIP_EPOCH_KEY],
        published[CONTENT_EPOCH_KEY],
    ) != (fresh_code.membership, fresh_code.content)


def _assert_snapshot_search(
    root: Path,
    model: EmbeddingModel,
    store: VaultStore,
) -> None:
    """Assert searchable content carries entry-snapshot transformation evidence."""
    from ... import VaultSearcher

    searcher = VaultSearcher(root, model, store)
    hits = searcher.search_codebase(
        "immutable operation snapshot publication worker shaping marker",
        top_k=5,
    )
    published_hit = next(hit for hit in hits if hit.path == "a_payload.blob")
    assert published_hit.preprocessor_id == "entry-snapshot-extractor"
    assert published_hit.source_path == "a_payload.blob"
    html_hit = next(hit for hit in hits if hit.path == "z_markup.html")
    assert "<section>" not in html_hit.snippet
    assert "<strong>" not in html_hit.snippet


@pytest.mark.timeout(600)
def test_config_edit_during_extraction_cannot_change_active_snapshot(
    rag_components: RagComponentsWithManifest,
    tmp_path: Path,
) -> None:
    from ... import CodebaseIndexer, VaultStore

    paths = _write_snapshot_project(tmp_path)
    with _snapshot_environment() as html_key:
        store = VaultStore(tmp_path)
        indexer = CodebaseIndexer(
            tmp_path,
            rag_components["model"],
            store,
            content_policy=RootContentPolicy(
                SourceProfileVersion.CONVENTIONAL_V1,
                (ContentRoute("z_markup.html", ContentKind.CODE),),
            ),
        )
        changed_paths = [paths.source, paths.html]
        preflight = indexer.preflight_changed_paths(changed_paths)
        entry_policy = preflight.policy
        entry_rule = entry_policy.preprocess_rules[0].materialize()
        assert entry_policy.html_strip

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    indexer.incremental_index,
                    reporter=NullProgressReporter(),
                    changed_paths=preflight.changed_paths,
                    preflight=preflight,
                )
                result = _cross_mutation_barrier(future, paths, html_key)

            assert paths.config.read_text(
                encoding="utf-8"
            ) == paths.replacement.read_text(encoding="utf-8")
            assert result.preprocess_ok == 1
            assert store.get_code_ids_by_paths({"a_payload.blob", "z_markup.html"})
            _assert_active_snapshot(indexer, entry_policy, entry_rule)
            _assert_published_snapshot(indexer, entry_policy)
            _assert_snapshot_search(tmp_path, rag_components["model"], store)
        finally:
            store.close()
