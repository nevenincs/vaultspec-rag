"""End-to-end integration tests for the document-preprocessing hook (#185).

Real GPU + real Qdrant + a real subprocess preprocessor. A binary ``.pdf``
(outside ``SUPPORTED_EXTENSIONS``) is extracted by a project-supplied command
rule, indexed first-class, and found by hybrid search with its deep-link anchor;
the scoped/incremental path routes a changed binary through the preprocessor;
and a failing preprocessor surfaces a skip count rather than a silent gap.

The sandbox boundary is proved end-to-end here too. Hooks now run BY DEFAULT for
any root - there is no trust step - so the tests below prove that safety comes
from OS containment, not consent: a hook runs through the local index under a
real sandbox backend, an untrusted root's hook that tries to read a secret and
open a socket still extracts its legitimate content while both malicious
operations are denied inside the container, and the ``off`` kill switch skips
hooks entirely.
"""

from __future__ import annotations

import os
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...config import EnvVar, reset_config
from ...indexer._hook_sandbox import resolve_hook_sandbox
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
    the runner resolves and runs a root's rules for any root, contained by the
    OS sandbox, so there is no per-root consent setup to perform.
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


def _probe_extractor(root: Path, secret_path: Path) -> Path:
    """Write an extractor that probes containment while emitting valid output.

    The hook tries to read ``secret_path`` (a file outside the staged scratch
    dir and outside the granted project root) and to open an outbound socket,
    then encodes the outcome of each into its emitted unit text. Under a working
    sandbox both must fail, so the indexed text carries ``SECRET_READ_BLOCKED``
    and ``NETWORK_BLOCKED``; the legitimate corpus text is emitted regardless.
    """
    script = root / "probe_extractor.py"
    script.write_text(
        textwrap.dedent(f"""
            import json, socket, sys
            secret = {str(secret_path)!r}
            try:
                open(secret, encoding="utf-8").read()
                secret_status = "SECRET_READ_OK"
            except OSError:
                secret_status = "SECRET_READ_BLOCKED"
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect(("1.1.1.1", 80))
                sock.close()
                net_status = "NETWORK_OK"
            except OSError:
                net_status = "NETWORK_BLOCKED"
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "probe",
                "preprocessor_version": "1.0",
                "source_path": sys.argv[1],
                "units": [{{
                    "text": (
                        "aurora telemetry ingestion pipeline "
                        + secret_status + " " + net_status
                    ),
                }}],
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
    def test_hook_runs_contained_through_local_index(
        self, preproc_project: _PreprocProject
    ) -> None:
        # The default-mode path with no trust step: a real command hook runs
        # through the local index under a resolved sandbox backend, its unit is
        # indexed and searchable, and the deep-link anchor references the real
        # source - never the ephemeral ``vsrag-hook-`` scratch dir the child
        # actually saw (the staged-path remap is what closes that leak).
        from ... import VaultSearcher

        backend = resolve_hook_sandbox(server_mode=False, unsandboxed=False)
        assert backend is not None, "no hook sandbox backend resolved on this host"
        if sys.platform == "win32":
            assert backend.name == "windows-appcontainer"

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
        assert top is not None, "contained hook's unit not indexed"
        assert top.anchor is not None
        assert "vsrag-hook-" not in top.anchor, "scratch path leaked into the anchor"
        assert "vsrag-hook-" not in (top.source_path or "")

    @pytest.mark.timeout(600)
    def test_untrusted_repo_hook_is_contained_not_refused(
        self,
        rag_components: RagComponentsWithManifest,
        tmp_path: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        # The whole point of the new model: a root that ships a hook and has NO
        # trust record still runs (rules resolve for any root) and is contained.
        # No interaction, still safe. The hook tries to steal a secret that
        # lives OUTSIDE the granted project root and to reach the network; the
        # legitimate content still extracts and indexes, while the sandbox
        # denies both malicious operations (proven from the indexed report).
        from ... import CodebaseIndexer, VaultSearcher, VaultStore

        model = rag_components["model"]

        backend = resolve_hook_sandbox(server_mode=False, unsandboxed=False)
        assert backend is not None, (
            "containment cannot be proven without a sandbox backend on this host"
        )

        # The secret sits in a sibling dir, never under the project root the
        # sandbox read-grants, so a contained child must not be able to open it.
        secret_dir = tmp_path_factory.mktemp("secret-outside-root")
        secret = secret_dir / "api_key.txt"
        secret.write_text("SUPER-SECRET-TOKEN", encoding="utf-8")

        _write_config(
            tmp_path,
            f'[[rule]]\npattern = "*.pdf"\n'
            f"command = '''{_command(_probe_extractor(tmp_path, secret))}'''\n"
            'on_error = "skip"\n',
        )
        (tmp_path / "doc.pdf").write_bytes(b"\x00\x01 binary")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            result = indexer.full_index(reporter=NullProgressReporter())
            # The hook ran (no trust step blocked it) and was not refused.
            assert result.preprocess_skipped == 0

            searcher = VaultSearcher(tmp_path, model, store)
            results = searcher.search_codebase(
                "aurora telemetry ingestion pipeline", top_k=5
            )
            unit = next((r for r in results if r.preprocessor_id == "probe"), None)
            assert unit is not None, "contained hook's legitimate content not indexed"
            assert unit.rerank_text is not None
            assert "SECRET_READ_BLOCKED" in unit.rerank_text, (
                "sandbox failed to deny the out-of-tree secret read"
            )
            assert "NETWORK_BLOCKED" in unit.rerank_text, (
                "sandbox failed to deny outbound network egress"
            )
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_off_kill_switch_skips_hooks(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        # VAULTSPEC_RAG_PREPROCESS=off is the kill switch: a repo that ships a
        # command rule executes nothing (a sentinel the command would create
        # stays absent) and the binary source is not indexed as a preprocessed
        # unit.
        from ... import CodebaseIndexer, VaultSearcher, VaultStore

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
            searcher = VaultSearcher(tmp_path, model, store)
            results = searcher.search_codebase("sentinel extractor output", top_k=5)
            assert not any(r.preprocessor_id == "sentinel" for r in results), (
                "binary source was preprocessed despite the off kill switch"
            )
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
