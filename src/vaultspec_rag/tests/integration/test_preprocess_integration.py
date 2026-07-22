"""End-to-end integration tests for the document-preprocessing hook (#185).

Real GPU + real Qdrant + a real subprocess preprocessor. A binary ``.pdf``
(outside ``SUPPORTED_EXTENSIONS``) is extracted by a project-supplied command
rule, indexed first-class, and found by hybrid search with its deep-link anchor;
the scoped/incremental path routes a changed binary through the preprocessor;
and a failing preprocessor surfaces a skip count rather than a silent gap.

Hooks run BY DEFAULT for any root - there is no trust step and no OS containment
(preprocess-sandbox-removal ADR): a root's preprocess config is repo-authored
code that runs directly with the operator's privileges. The tests below prove
the direct-execution path end to end: a hook runs through the local index, its
unit is indexed and searchable with a deep-link anchor to the real source, and
the ``off`` kill switch skips hooks entirely.
"""

from __future__ import annotations

import os
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...config import EnvVar, reset_config
from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import CodebaseIndexer
    from ...store import VaultStore
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _preprocess_env(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Isolate the managed status dir to a per-test tmp path.

    The status dir is relocated so no test touches the operator's real
    ``~/.vaultspec-rag``. No trust store exists anymore: under the default mode
    the runner resolves and runs a root's rules for any root directly, so there
    is no per-root consent setup to perform.
    """
    status_key = EnvVar.STATUS_DIR.value
    prev_status = os.environ.get(status_key)
    os.environ[status_key] = str(tmp_path_factory.mktemp("preproc-status"))
    reset_config()
    try:
        yield
    finally:
        if prev_status is None:
            os.environ.pop(status_key, None)
        else:
            os.environ[status_key] = prev_status
        reset_config()


# Emits a two-unit PreprocOutput with recognisable text + page anchors.
_PDF_EXTRACTOR = """
    import json, sys
    src = sys.argv[1]
    print(json.dumps({
        "schema_version": 1,
        "preprocessor_id": "fake-pdf",
        "preprocessor_version": "1.0",
        "source_path": src,
        "units": [
            {"text": "Quarterly revenue projections and margin analysis.",
             "anchor": src + "#page=1",
             "locator": {"kind": "page", "value": 1}},
            {"text": "Appendix: regional sales breakdown by territory.",
             "anchor": src + "#page=2",
             "locator": {"kind": "page", "value": 2}},
        ],
    }))
"""

# Always exits non-zero -> a skip under on_error=skip.
_FAILING_EXTRACTOR = "import sys\nsys.exit(2)\n"


class _PreprocProject(TypedDict):
    code_indexer: CodebaseIndexer
    store: VaultStore
    model: EmbeddingModel
    root: Path


def _command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"


def _write_config(root: Path, rules: str) -> None:
    (root / ".vaultragpreprocess.toml").write_text(rules, encoding="utf-8")


def _file_tree_bytes(root: Path) -> dict[str, bytes]:
    """Snapshot exact files below one bounded test-owned directory."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _sentinel_extractor(root: Path, sentinel: Path) -> Path:
    """Write an extractor that proves execution by creating ``sentinel``.

    Emits a valid single-unit output so an (unexpectedly) executed run also
    indexes cleanly rather than masking itself as a skip.
    """
    script = root / f"extract_{sentinel.stem.lower()}.py"
    script.write_text(
        textwrap.dedent(f"""
            import json, pathlib, sys
            pathlib.Path({str(sentinel)!r}).write_text("executed")
            print(json.dumps({{
                "schema_version": 1, "preprocessor_id": "sentinel",
                "preprocessor_version": "1.0", "source_path": sys.argv[1],
                "units": [{{"text": "sentinel extractor output"}}],
            }}))
        """),
        encoding="utf-8",
    )
    return script


@pytest.fixture
def preproc_project(
    rag_components: RagComponentsWithManifest,
    tmp_path: Path,
) -> Generator[_PreprocProject]:
    """A temp project with a command preprocess rule and a binary .pdf source."""
    from ... import CodebaseIndexer, VaultStore

    model = rag_components["model"]

    script = tmp_path / "pdf_extractor.py"
    script.write_text(textwrap.dedent(_PDF_EXTRACTOR), encoding="utf-8")
    _write_config(
        tmp_path,
        f"[[rule]]\npattern = \"*.pdf\"\ncommand = '''{_command(script)}'''\n"
        'on_error = "skip"\n',
    )
    (tmp_path / "report.pdf").write_bytes(b"\x00\x01\x02 binary pdf bytes")

    store = VaultStore(tmp_path)
    code_indexer = CodebaseIndexer(tmp_path, model, store)
    yield _PreprocProject(
        code_indexer=code_indexer, store=store, model=model, root=tmp_path
    )
    store.close()


class TestPreprocessEndToEnd:
    @pytest.mark.timeout(600)
    def test_binary_pdf_is_extracted_indexed_and_searchable(
        self, preproc_project: _PreprocProject
    ) -> None:
        from ... import VaultSearcher

        result = preproc_project["code_indexer"].full_index(
            reporter=NullProgressReporter()
        )
        assert result.preprocess_ok == 1
        assert result.preprocess_skipped == 0
        assert preproc_project["store"].count_code() >= 2  # two units

        searcher = VaultSearcher(
            preproc_project["root"],
            preproc_project["model"],
            preproc_project["store"],
        )
        results = searcher.search_codebase("quarterly revenue margin", top_k=5)
        assert results
        top = next((r for r in results if r.preprocessor_id == "fake-pdf"), None)
        assert top is not None, "preprocessed unit not found in search results"
        assert top.anchor is not None and "#page=" in top.anchor
        assert top.locator is not None and top.locator.startswith("page ")
        assert top.source_path == "report.pdf"

    @pytest.mark.timeout(600)
    def test_hook_runs_directly_through_local_index(
        self, preproc_project: _PreprocProject
    ) -> None:
        # The default-mode path with no trust step and no containment: a real
        # command hook runs directly through the local index, its unit is
        # indexed and searchable, and the deep-link anchor references the real
        # source - never the ephemeral ``vsrag-hook-`` scratch cwd the child
        # ran in, because the hook reads the original source path directly.
        from ... import VaultSearcher

        result = preproc_project["code_indexer"].full_index(
            reporter=NullProgressReporter()
        )
        assert result.preprocess_ok == 1
        assert result.preprocess_skipped == 0

        searcher = VaultSearcher(
            preproc_project["root"],
            preproc_project["model"],
            preproc_project["store"],
        )
        results = searcher.search_codebase(
            "regional sales territory breakdown", top_k=5
        )
        top = next((r for r in results if r.preprocessor_id == "fake-pdf"), None)
        assert top is not None, "hook's unit not indexed"
        assert top.anchor is not None
        assert "vsrag-hook-" not in top.anchor, "scratch path leaked into the anchor"
        assert "vsrag-hook-" not in (top.source_path or "")

    @pytest.mark.timeout(600)
    def test_off_kill_switch_skips_hooks(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # The kill switch disables execution without erasing ownership. A
        # previously extracted code-owned path therefore remains published as
        # stale when its source changes while execution is off.
        from ... import CodebaseIndexer, VaultStore
        from ...config import get_config
        from ...indexer._content_policy import (
            AdmissionReason,
            ContentKind,
        )
        from ...indexer._preprocess_cache import preprocess_cache_dir

        model = rag_components["model"]
        sentinel = tmp_path / "EXECUTED.flag"
        extractor = _sentinel_extractor(tmp_path, sentinel)
        _write_config(
            tmp_path,
            "version = 2\n\n"
            '[[rule]]\npattern = "*.pdf"\n'
            f"command = '''{_command(extractor)}'''\n"
            'target = "code"\n'
            'extractor_version = "1"\n'
            'on_error = "skip"\n',
        )
        (tmp_path / ".vaultragignore").write_text(
            f"/{extractor.name}\n",
            encoding="utf-8",
        )
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"\x00\x01 binary")

        key = EnvVar.PREPROCESS.value
        prev = os.environ.get(key)
        os.environ.pop(key, None)
        reset_config()
        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            baseline = indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            assert baseline.preprocess_ok == 1
            assert sentinel.exists()
            sentinel.unlink()

            cfg = get_config()
            data_root = tmp_path / cfg.data_dir
            metadata_path = data_root / cfg.code_index_metadata_file
            cache_root = preprocess_cache_dir(data_root)
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / "preserved.json").write_bytes(b'{"preserved":true}')
            before_ids = store.get_all_code_ids()
            before_path_ids = store.get_code_ids_by_paths({"doc.pdf"})
            before_metadata = metadata_path.read_bytes()
            before_cache = _file_tree_bytes(cache_root)
            assert before_ids
            assert before_path_ids

            os.environ[key] = "off"
            reset_config()
            source.write_bytes(b"\x00\x02 changed binary")
            scan = indexer.scan_content()
            sample = next(item for item in scan.samples if item.path == "doc.pdf")
            assert (
                scan.preprocess_mode,
                scan.preprocess_rule_count,
                scan.hooks_will_run,
                sample.kind,
                sample.admitted,
                sample.reason,
                source in scan.files,
            ) == (
                "off",
                1,
                False,
                ContentKind.CODE,
                True,
                AdmissionReason.EXPLICIT_ROUTE,
                True,
            )

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=[source],
                preflight=indexer.preflight_changed_paths([source]),
            )

            assert (result.added, result.updated, result.removed) == (0, 0, 0)
            assert result.preprocess_ok == 0
            assert result.preprocess_skipped == 1
            assert result.preprocess_failures == [
                "doc.pdf: preprocessing disabled; retained work as stale"
            ]
            assert not sentinel.exists()
            assert store.get_all_code_ids() == before_ids
            assert store.get_code_ids_by_paths({"doc.pdf"}) == before_path_ids
            assert metadata_path.read_bytes() == before_metadata
            assert _file_tree_bytes(cache_root) == before_cache
        finally:
            store.close()
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
            reset_config()

    @pytest.mark.timeout(600)
    def test_incremental_routes_changed_binary_through_preprocessor(
        self, preproc_project: _PreprocProject
    ) -> None:
        indexer = preproc_project["code_indexer"]
        store = preproc_project["store"]
        indexer.full_index(reporter=NullProgressReporter())
        before = store.count_code()

        new_pdf = preproc_project["root"] / "appendix.pdf"
        new_pdf.write_bytes(b"\x00\x01 another binary")
        # The scoped path is exactly what the watcher invokes on a change.
        result = indexer.incremental_index(
            reporter=NullProgressReporter(), changed_paths=[new_pdf]
        )
        assert result.preprocess_ok == 1
        assert result.added > 0
        assert store.count_code() > before

    @pytest.mark.timeout(600)
    def test_failing_preprocessor_surfaces_skip_count(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]
        script = tmp_path / "boom.py"
        script.write_text(_FAILING_EXTRACTOR, encoding="utf-8")
        _write_config(
            tmp_path,
            f"[[rule]]\npattern = \"*.pdf\"\ncommand = '''{_command(script)}'''\n"
            'on_error = "skip"\n',
        )
        (tmp_path / "broken.pdf").write_bytes(b"\x00\x01 binary")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            result = indexer.full_index(reporter=NullProgressReporter())
            assert result.preprocess_ok == 0
            assert result.preprocess_skipped == 1
            assert any("broken.pdf" in f for f in result.preprocess_failures)
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_ignore_edit_prunes_stale_chunks_down_the_watcher_path(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # The consumer-reported drift scenario, end to end: index two source
        # files, then newly ignore one via .vaultragignore and forward ONLY the
        # ignore file down the scoped path (exactly what the watcher does).
        # The membership-epoch check must force the unscoped reconcile and
        # prune the newly-ignored file's chunks.
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]
        (tmp_path / "keep.py").write_text(
            "def keep_me():\n    return 'retained module'\n", encoding="utf-8"
        )
        (tmp_path / "drop.py").write_text(
            "def drop_me():\n    return 'stale module'\n", encoding="utf-8"
        )

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(reporter=NullProgressReporter())
            assert store.get_code_ids_by_paths({"drop.py"}), (
                "precondition: drop.py must be indexed before the ignore edit"
            )

            ignore = tmp_path / ".vaultragignore"
            ignore.write_text("drop.py\n", encoding="utf-8")
            result = indexer.incremental_index(
                reporter=NullProgressReporter(), changed_paths=[ignore]
            )
            assert result.removed >= 1
            assert not store.get_code_ids_by_paths({"drop.py"}), (
                "newly-ignored file's chunks were not pruned"
            )
            assert store.get_code_ids_by_paths({"keep.py"}), (
                "unrelated file's chunks were dropped by the reconcile"
            )
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_passthrough_indexes_raw_text(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # TST-002: a preprocess-matched file whose extractor fails under
        # on_error=passthrough is chunked as raw text and stays searchable.
        from ... import CodebaseIndexer, VaultSearcher, VaultStore

        model = rag_components["model"]
        script = tmp_path / "boom.py"
        script.write_text(_FAILING_EXTRACTOR, encoding="utf-8")
        _write_config(
            tmp_path,
            f"[[rule]]\npattern = \"*.log\"\ncommand = '''{_command(script)}'''\n"
            'on_error = "passthrough"\n',
        )
        # .log is not a supported extension; the rule match admits it, and
        # passthrough then chunks the raw text.
        (tmp_path / "notes.log").write_text(
            "passthrough sentinel phrase about quarterly logistics", encoding="utf-8"
        )

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(reporter=NullProgressReporter())
            searcher = VaultSearcher(tmp_path, model, store)
            results = searcher.search_codebase(
                "passthrough sentinel logistics", top_k=5
            )
            hit = next((r for r in results if "notes.log" in r.path), None)
            assert hit is not None, "passthrough raw text not indexed"
            assert hit.preprocessor_id is None  # raw chunk, not a preproc unit
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_command_change_reextracts(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # TST-003: bumping a rule's command (the cache lever) re-extracts the
        # same unchanged source rather than serving stale cached output.
        from ... import CodebaseIndexer, VaultSearcher, VaultStore

        model = rag_components["model"]

        def _emit(token: str) -> Path:
            s = tmp_path / f"extract_{token}.py"
            s.write_text(
                "import json, sys\n"
                "print(json.dumps({'schema_version': 1, 'preprocessor_id': 'v',\n"
                f"  'preprocessor_version': '{token}', 'source_path': sys.argv[1],\n"
                f"  'units': [{{'text': 'unique token {token} content'}}]}}))\n",
                encoding="utf-8",
            )
            return s

        source = tmp_path / "doc.pdf"
        source.write_bytes(b"\x00\x01binary")

        def _config(command: str) -> str:
            return f"[[rule]]\npattern = \"*.pdf\"\ncommand = '''{command}'''\n"

        store = VaultStore(tmp_path)
        try:
            _write_config(tmp_path, _config(_command(_emit("alpha"))))
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(reporter=NullProgressReporter())
            searcher = VaultSearcher(tmp_path, model, store)
            assert any(
                "alpha" in r.snippet
                for r in searcher.search_codebase("unique token alpha", top_k=5)
            )

            # Bump the command -> new cache key -> re-extract on clean rebuild.
            _write_config(tmp_path, _config(_command(_emit("beta"))))
            indexer.full_index(clean=True, reporter=NullProgressReporter())
            beta = searcher.search_codebase("unique token beta", top_k=5)
            assert any("beta" in r.snippet for r in beta)
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_incremental_surfaces_skip_count(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # Regression for review VIS-001: the scoped/incremental path (used by
        # the watcher) must surface preprocess skip counts, not just full index.
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]
        script = tmp_path / "boom.py"
        script.write_text(_FAILING_EXTRACTOR, encoding="utf-8")
        _write_config(
            tmp_path,
            f"[[rule]]\npattern = \"*.pdf\"\ncommand = '''{_command(script)}'''\n"
            'on_error = "skip"\n',
        )
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"\x00\x01 binary")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            result = indexer.incremental_index(
                reporter=NullProgressReporter(), changed_paths=[broken]
            )
            assert result.preprocess_ok == 0
            assert result.preprocess_skipped == 1
            assert any("broken.pdf" in f for f in result.preprocess_failures)
        finally:
            store.close()
