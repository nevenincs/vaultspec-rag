"""End-to-end integration tests for the document-preprocessing hook (#185).

Real GPU + real Qdrant + a real subprocess preprocessor. A binary ``.pdf``
(outside ``SUPPORTED_EXTENSIONS``) is extracted by a project-supplied command
rule, indexed first-class, and found by hybrid search with its deep-link anchor;
the scoped/incremental path routes a changed binary through the preprocessor;
and a failing preprocessor surfaces a skip count rather than a silent gap.

The tri-state/TOFU boundary is proved end-to-end here too: the ``off`` kill
switch outranks trust-all, an untrusted root under the default mode executes
nothing and names the trust verb, a trusted root executes and a command edit
reverts it, and an ignore-file edit forwarded down the watcher path prunes the
newly-ignored chunks via the config-epoch escalation.
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
    """Isolate the trust store and default this module to trust-all.

    The TOFU trust store lives under the managed status dir, so the dir is
    relocated to a per-test tmp path (never the operator's real
    ``~/.vaultspec-rag``). Extractor-behavior tests run under trust-all so
    they exercise the real subprocess path without a per-root trust record;
    the TOFU boundary tests below override the mode env vars themselves.
    """
    status_key = EnvVar.STATUS_DIR.value
    trust_key = EnvVar.PREPROCESS_TRUST_ALL.value
    prev_status = os.environ.get(status_key)
    prev_trust = os.environ.get(trust_key)
    os.environ[status_key] = str(tmp_path_factory.mktemp("preproc-status"))
    os.environ[trust_key] = "1"
    reset_config()
    try:
        yield
    finally:
        for key, prev in ((status_key, prev_status), (trust_key, prev_trust)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        reset_config()


@pytest.fixture
def _default_mode() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]  # referenced via usefixtures
    """Drop the module's trust-all opt-in so the on-with-TOFU default applies."""
    trust_key = EnvVar.PREPROCESS_TRUST_ALL.value
    prev = os.environ.get(trust_key)
    os.environ.pop(trust_key, None)
    reset_config()
    try:
        yield
    finally:
        if prev is not None:
            os.environ[trust_key] = prev
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
            assert result.preprocess_skipped == 1
            assert any("broken.pdf" in f for f in result.preprocess_failures)
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_off_mode_outranks_trust_all_and_executes_nothing(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # C1 (end-to-end RCE proof, kill-switch tier): with
        # VAULTSPEC_RAG_PREPROCESS=off, indexing a repo that ships a command
        # rule must NOT execute the command even though the module fixture
        # sets trust-all - off wins over everything. A sentinel the command
        # would create stays absent.
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]
        sentinel = tmp_path / "EXECUTED.flag"
        _write_config(
            tmp_path,
            f'[[rule]]\npattern = "*.pdf"\n'
            f"command = '''{_command(_sentinel_extractor(tmp_path, sentinel))}'''\n"
            'on_error = "skip"\n',
        )
        (tmp_path / "doc.pdf").write_bytes(b"\x00\x01 binary")

        key = EnvVar.PREPROCESS.value
        prev = os.environ.get(key)
        os.environ[key] = "off"
        reset_config()
        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(reporter=NullProgressReporter())
            assert not sentinel.exists(), (
                "preprocess command executed under the off kill switch"
            )
        finally:
            store.close()
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
            reset_config()

    @pytest.mark.timeout(600)
    @pytest.mark.usefixtures("_default_mode")
    def test_untrusted_default_executes_nothing_and_names_trust_verb(
        self,
        rag_components: RagComponentsWithManifest,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # C1 (end-to-end RCE proof, TOFU tier): under the default mode with no
        # trust record, indexing a repo that ships a command rule executes
        # nothing, and the skip warning names the remediation verb.
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]
        sentinel = tmp_path / "EXECUTED.flag"
        _write_config(
            tmp_path,
            f'[[rule]]\npattern = "*.pdf"\n'
            f"command = '''{_command(_sentinel_extractor(tmp_path, sentinel))}'''\n"
            'on_error = "skip"\n',
        )
        (tmp_path / "doc.pdf").write_bytes(b"\x00\x01 binary")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            with caplog.at_level("WARNING"):
                indexer.full_index(reporter=NullProgressReporter())
            assert not sentinel.exists(), (
                "untrusted preprocess command executed (TOFU gate not closed)"
            )
            assert any("preprocess trust" in r.message for r in caplog.records), (
                "untrusted skip warning does not name the trust verb"
            )
        finally:
            store.close()

    @pytest.mark.timeout(600)
    @pytest.mark.usefixtures("_default_mode")
    def test_trusted_root_executes_and_command_edit_reverts_trust(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # TOFU round trip: trusting the resolved rule set lets the command run
        # under the default mode; editing the command reverts the root to
        # untrusted automatically (the trust hash no longer matches).
        from ... import CodebaseIndexer, VaultStore
        from ...indexer._preprocess_config import load_preprocess_rules
        from ...indexer._preprocess_trust import hash_rule_set, record_trust

        model = rag_components["model"]
        first = tmp_path / "FIRST.flag"
        second = tmp_path / "SECOND.flag"
        _write_config(
            tmp_path,
            f'[[rule]]\npattern = "*.pdf"\n'
            f"command = '''{_command(_sentinel_extractor(tmp_path, first))}'''\n"
            'on_error = "skip"\n',
        )
        (tmp_path / "doc.pdf").write_bytes(b"\x00\x01 binary")

        rules = load_preprocess_rules(tmp_path, strict=True).rules
        record_trust(
            tmp_path,
            rule_set_hash=hash_rule_set(rules),
            trusted_at="2026-07-13T00:00:00Z",
        )

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(reporter=NullProgressReporter())
            assert first.exists(), "trusted preprocess command did not execute"

            # A different command re-resolves to a different hash: the stored
            # trust record no longer matches, so nothing may execute.
            _write_config(
                tmp_path,
                f'[[rule]]\npattern = "*.pdf"\n'
                f"command = '''{_command(_sentinel_extractor(tmp_path, second))}'''\n"
                'on_error = "skip"\n',
            )
            indexer.full_index(clean=True, reporter=NullProgressReporter())
            assert not second.exists(), (
                "edited (re-untrusted) preprocess command executed"
            )
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
            assert result.preprocess_skipped == 1
            assert any("broken.pdf" in f for f in result.preprocess_failures)
        finally:
            store.close()
