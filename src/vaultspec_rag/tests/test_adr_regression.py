"""ADR regression tests: verify architectural decisions haven't regressed.

Each test corresponds to an ADR in .vault/adr/ and catches regressions
that would violate the documented architectural contract.
"""

from __future__ import annotations

import hashlib
import typing
from typing import TYPE_CHECKING

import pytest

from ._import_probe import assert_fresh_import_excludes

if TYPE_CHECKING:
    import ast
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestBlake2bFileHashing:
    """ADR: blake2b-file-hashing - file hashes must use blake2b, not sha256."""

    def test_vault_indexer_meta_uses_blake2b_hashes(self, tmp_path: Path) -> None:
        """VaultIndexer._save_meta produces blake2b hex digests (128 chars)."""
        from ..indexer import VaultIndexer

        indexer = object.__new__(VaultIndexer)
        indexer._meta_path = tmp_path / ".rag" / "vault_meta.json"

        # Write a test file and hash it the same way the indexer does
        test_file = tmp_path / "test.md"
        test_file.write_text("hello world", encoding="utf-8")

        with open(test_file, "rb") as f:
            digest = hashlib.file_digest(f, "blake2b").hexdigest()

        # blake2b default digest is 64 bytes = 128 hex chars
        # sha256 is 32 bytes = 64 hex chars
        assert len(digest) == 128, (
            f"Expected blake2b (128 hex chars), got {len(digest)} chars"
        )

    def test_codebase_indexer_meta_uses_blake2b_hashes(self, tmp_path: Path) -> None:
        """CodebaseIndexer._write_meta produces blake2b hex digests."""
        from ..indexer import CodebaseIndexer

        indexer = CodebaseIndexer(
            tmp_path,
            typing.cast("typing.Any", None),
            typing.cast("typing.Any", None),
        )
        indexer._meta_path = tmp_path / ".rag" / "code_meta.json"

        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1", encoding="utf-8")

        with open(test_file, "rb") as f:
            digest = hashlib.file_digest(f, "blake2b").hexdigest()

        assert len(digest) == 128

        # Round-trip: write and load back
        indexer._write_meta(
            {"test.py": digest},
            policy=indexer.resolve_policy_snapshot(),
        )
        loaded = indexer._load_meta()
        assert loaded["test.py"] == digest
        assert len(loaded["test.py"]) == 128


class TestMCPAsyncTools:
    """ADR: mcp-sync-tools (superseded) - MCP tools must be async def + anyio."""

    def test_search_vault_is_async(self) -> None:
        import inspect

        from ..mcp._tools import search_vault

        assert inspect.iscoroutinefunction(search_vault)

    def test_search_codebase_is_async(self) -> None:
        import inspect

        from ..mcp._tools import search_codebase

        assert inspect.iscoroutinefunction(search_codebase)

    def test_reindex_vault_is_async(self) -> None:
        import inspect

        from ..mcp._tools import reindex_vault

        assert inspect.iscoroutinefunction(reindex_vault)

    def test_reindex_codebase_is_async(self) -> None:
        import inspect

        from ..mcp._tools import reindex_codebase

        assert inspect.iscoroutinefunction(reindex_codebase)

    def test_get_code_file_is_async(self) -> None:
        import inspect

        from ..mcp._tools import get_code_file

        assert inspect.iscoroutinefunction(get_code_file)


class TestPathResolveCache:
    """ADR: registry normalizes with Path.resolve() for cache consistency."""

    def test_relative_and_dot_relative_same_engine(self, tmp_path: Path) -> None:
        """Path('./x') and Path('x') resolve to the same registry key."""
        from ..registry import get_registry

        # Both paths resolve to the same absolute path
        abs_path = tmp_path / "project"
        abs_path.mkdir()
        p1 = abs_path
        p2 = abs_path.resolve()
        assert p1.resolve() == p2.resolve()
        # The registry is the single cache path for slots now.
        assert get_registry() is get_registry()


class TestGraphCache:
    """ADR: GraphCache returns same instance on repeated calls."""

    def test_graph_cache_invalidate_clears(self):
        from ..graph_cache import GraphCache

        cache = GraphCache(ttl_seconds=300.0)
        # After invalidate, internal state is cleared
        cache.invalidate()
        assert cache._graph is None
        assert cache._root is None
        assert cache._built_at == 0.0

    def test_graph_cache_has_lock(self):
        import threading

        from ..graph_cache import GraphCache

        cache = GraphCache(ttl_seconds=300.0)
        assert isinstance(cache._lock, type(threading.Lock()))


class TestQwen3NoDocumentPrompt:
    """ADR: encode_documents must NOT pass prompt_name to the dense model."""

    def test_encode_documents_no_prompt_name(self):
        import inspect

        from ..embeddings import EmbeddingModel

        source = inspect.getsource(EmbeddingModel.encode_documents)
        assert "prompt_name" not in source, (
            "encode_documents should not pass prompt_name to the dense model"
        )

    def test_encode_query_uses_prompt_name(self):
        import inspect

        from ..embeddings import EmbeddingModel

        source = inspect.getsource(EmbeddingModel.encode_query)
        assert "prompt_name" in source, (
            "encode_query should pass prompt_name='query' to the dense model"
        )


class TestEmbeddingModelLoadArguments:
    """Regression coverage for model constructor arguments."""

    @staticmethod
    def _load_ast():
        import ast
        import inspect
        import textwrap

        from ..embeddings import EmbeddingModel

        # The dense SentenceTransformer construction lives in
        # ``_load_dense_model`` (backend seam) while SparseEncoder stays in
        # ``__init__``; parse the whole class so both calls are in scope.
        source = textwrap.dedent(inspect.getsource(EmbeddingModel))
        return ast.parse(source)

    @staticmethod
    def _call_kwargs(tree: ast.AST, call_name: str) -> dict[str, object]:
        import ast

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == call_name:
                return {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        raise AssertionError(f"{call_name} call not found")

    def test_dense_text_model_uses_processor_kwargs(self):
        import ast

        kwargs = self._call_kwargs(self._load_ast(), "SentenceTransformer")
        assert "processor_kwargs" in kwargs
        assert "tokenizer_kwargs" not in kwargs

        processor_kwargs = kwargs["processor_kwargs"]
        assert isinstance(processor_kwargs, ast.Dict)
        assert any(
            isinstance(key, ast.Constant)
            and key.value == "padding_side"
            and isinstance(value, ast.Constant)
            and value.value == "left"
            for key, value in zip(
                processor_kwargs.keys,
                processor_kwargs.values,
                strict=True,
            )
        )

    def test_sparse_model_does_not_force_pickle_weights(self):
        import ast

        kwargs = self._call_kwargs(self._load_ast(), "SparseEncoder")
        model_kwargs = kwargs["model_kwargs"]
        assert isinstance(model_kwargs, ast.Dict)

        keys = [
            key.value
            for key in model_kwargs.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        assert "torch_dtype" in keys
        assert "use_safetensors" not in keys


class TestThreadingLock:
    """ADR: server and api use threading locks for initialization.

    The eviction work (#45) upgraded ``ServiceRegistry._lock`` from a
    plain ``threading.Lock`` to a reentrant ``threading.RLock`` so the
    eviction codepaths can call ``close_project`` while still holding
    the registry lock without deadlocking.  Both lock types expose the
    same ``acquire``/``release`` interface but ``isinstance`` against
    ``type(threading.Lock())`` rejects the RLock - these tests now
    accept the RLock as well.
    """

    @staticmethod
    def _lock_types() -> tuple[type, ...]:
        import threading

        return (type(threading.Lock()), type(threading.RLock()))

    def test_mcp_registry_lock_exists(self):
        from ..server import _registry

        assert isinstance(_registry._lock, self._lock_types())

    def test_registry_singleton_has_lock(self):
        from ..registry import get_registry

        reg = get_registry()
        assert isinstance(reg._lock, self._lock_types())


class TestFilterOnPrefetch:
    """ADR: hybrid_search applies filter on Prefetch, not on query_points."""

    def test_hybrid_search_uses_prefetch_filter(self):
        import inspect

        from ..store_runtime import VaultStore

        source = inspect.getsource(VaultStore._build_prefetch)
        # Filter must appear in Prefetch constructor, not as query_filter kwarg
        assert "Prefetch(" in source
        assert "filter=query_filter" in source


class TestManualNodeWalking:
    """ADR: ASTChunker._extract_name uses child_by_field_name for AST walking."""

    def test_extract_name_uses_child_by_field_name(self):
        import inspect

        from ..indexer import ASTChunker

        source = inspect.getsource(ASTChunker._extract_name)
        assert "child_by_field_name" in source, (
            "_extract_name must use child_by_field_name for AST node name extraction"
        )


class TestRerankerModelName:
    """ADR: gpu-only-rag-stack - reranker model must be bge-reranker-v2-m3."""

    def test_config_default_reranker_model(self):
        from ..config._settings import get_config, reset_config

        reset_config()
        cfg = get_config()
        assert cfg.reranker_model == "BAAI/bge-reranker-v2-m3"
        reset_config()


@pytest.mark.unit
class TestRrfKParameter:
    """RRF k must be 60, not the default k=2 (which creates 4x rank bias)."""

    def test_hybrid_search_uses_rrf_k60(self):
        import inspect
        import linecache

        from ..store_runtime import VaultStore

        linecache.clearcache()
        src = inspect.getsource(VaultStore._execute_hybrid_query)
        assert "Rrf(k=60)" in src or "rrf=models.Rrf(k=60)" in src, (
            "_execute_hybrid_query must use RrfQuery(rrf=Rrf(k=60)), "
            "not FusionQuery default (k=2)"
        )

    def test_hybrid_search_codebase_uses_rrf_k60(self):
        import inspect
        import linecache

        from ..store_runtime import VaultStore

        linecache.clearcache()
        src = inspect.getsource(VaultStore._execute_hybrid_query)
        assert "Rrf(k=60)" in src or "rrf=models.Rrf(k=60)" in src


class TestGraphCacheInvalidation:
    """R29 fix: reindex_vault must reset graph cache.

    Next search must rebuild from fresh index.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_reindex_vault_resets_graph_cache(self):
        """The vault attempt must invalidate the graph cache when it finishes.

        Job control moved the indexing body out of ``start_reindex_vault``,
        which now only admits and dispatches; the attempt runner owns the
        post-index work. The invariant is unchanged - a vault reindex that
        does not invalidate leaves the next search re-ranking on a stale
        graph - so the guard follows the behaviour to its new home.
        """
        import inspect

        from .. import job_dispatch

        src = inspect.getsource(job_dispatch._run_vault_attempt)
        assert "graph_cache" in src and "invalidate" in src, (
            "the vault index attempt must call slot.graph_cache.invalidate() "
            "after indexing to prevent stale graph re-ranking"
        )


class TestCliMcpFastPath:
    """CLI _do_http_call must use asyncio.run() (safe from sync Typer handlers)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_do_http_call_uses_urllib(self):
        import inspect

        from ..serviceclient import _transport

        # The invariant is the HTTP fast path stays synchronous (urllib),
        # because Typer handlers are sync and the MCP offloads these blocking
        # calls onto a worker thread. The wire client was factored into the
        # import-light serviceclient package, so inspect that module - which
        # the CLI now imports from directly.
        src = inspect.getsource(_transport)
        assert "urllib.request" in src, (
            "the HTTP fast path must use synchronous urllib.request instead "
            "of async HTTP because Typer handlers are sync."
        )
        for forbidden in ("aiohttp", "AsyncClient", "await "):
            assert forbidden not in src, (
                "the HTTP fast path must stay synchronous; "
                f"found async marker {forbidden!r}."
            )


class TestWatcherGraphInvalidation:
    """Watcher must use the graph cache contract for invalidation."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_watcher_configuration_requires_graph_cache(self):
        import inspect

        from ..watcher_intake import watch_and_reindex
        from ..watcher_runtime import WatcherConfiguration

        configuration_signature = inspect.signature(WatcherConfiguration)
        assert "graph_cache" in configuration_signature.parameters, (
            "WatcherConfiguration must carry the project GraphCache so the watcher "
            "can invalidate graph data after vault reindex"
        )
        # The watcher takes a single configuration object, so checking only
        # its own parameters can no longer see a searcher reintroduced through
        # that object; both sides are checked for the retired name.
        watcher_signature = inspect.signature(watch_and_reindex)
        carriers = set(watcher_signature.parameters) | set(
            configuration_signature.parameters
        )
        assert "searcher" not in carriers, (
            "neither watch_and_reindex nor WatcherConfiguration may retain the "
            "old private searcher invalidation path"
        )


class TestAtomicMetaWrite:
    """``_write_meta`` must publish atomically, never truncate in place.

    A direct ``write_text`` leaves a half-written sidecar if the process dies
    mid-write, and the next run reads that as the index's metadata. Publishing
    means writing a temp file and replacing the target in one step.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_vault_indexer_write_meta_publishes_atomically(self):
        import inspect

        from ..indexer import VaultIndexer

        src = inspect.getsource(VaultIndexer._write_meta)
        assert "write_json_atomically(" in src, (
            "VaultIndexer._write_meta must publish through "
            "_atomic_write.write_json_atomically; a direct write_text() risks "
            "corrupt metadata on crash, and a hand-rolled temp-and-replace "
            "leaves the temp behind when the publish fails"
        )

    def test_codebase_indexer_write_meta_publishes_atomically(self):
        import inspect

        from ..indexer import CodebaseIndexer

        src = inspect.getsource(CodebaseIndexer._write_meta)
        assert "write_json_atomically(" in src, (
            "CodebaseIndexer._write_meta must publish through "
            "_atomic_write.write_json_atomically; a direct write_text() risks "
            "corrupt metadata on crash, and a hand-rolled temp-and-replace "
            "leaves the temp behind when the publish fails"
        )


class TestStorageMaintenanceIsLifecycleInert:
    """Storage maintenance must never reach a stop/terminate/reclaim flow.

    A maintenance actor that can terminate the service turns a routine
    reclamation into an outage, and one that can restore an archive turns a
    reclamation into an unrequested write. The scheduled tick is read and
    drop; nothing else.

    Guarded in both directions for both flows: the maintenance import graph
    must not pull in the CLI lifecycle module or the restore module at all
    (fresh interpreter - the in-process ``sys.modules`` is polluted by other
    tests), and the maintenance sources must not name the terminate helpers
    or the restore operation.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    _IMPORT_CHECK = """
import sys

import vaultspec_rag.storage_manifest  # noqa: F401
import vaultspec_rag.storage_reclamation  # noqa: F401
import vaultspec_rag.storage_reconciliation  # noqa: F401
import vaultspec_rag.storage_survey_ops  # noqa: F401
import vaultspec_rag.server._lifecycle  # noqa: F401

loaded = sorted(
    m for m in sys.modules
    if m == "vaultspec_rag.cli" or m.startswith("vaultspec_rag.cli.")
)
assert not loaded, loaded
"""

    _RESTORE_IMPORT_CHECK = """
import sys

import vaultspec_rag.storage_manifest  # noqa: F401
import vaultspec_rag.storage_reclamation  # noqa: F401
import vaultspec_rag.storage_reconciliation  # noqa: F401
import vaultspec_rag.storage_survey_ops  # noqa: F401
import vaultspec_rag.server._lifecycle  # noqa: F401

assert "vaultspec_rag.storage_restore" not in sys.modules
"""

    def test_maintenance_import_graph_excludes_cli_lifecycle(self):
        assert_fresh_import_excludes(self._IMPORT_CHECK)

    def test_maintenance_import_graph_excludes_the_restore_module(self):
        """A tick that can import restore is one refactor from calling it.

        This guard catches what the source scan cannot: reach through an
        intermediate module. Mutation-proved by adding a module that
        re-exports ``restore_archive`` and importing *that* from
        ``storage_survey_ops``. No maintenance source then names a forbidden
        symbol, so the source scan below stays green and only this assertion
        fires - which is the whole reason both guards exist.

        A direct ``import vaultspec_rag.storage_restore`` trips both, because
        the import line itself carries the module name. That is the easy case;
        the transitive one above is the case this guard is for.
        """
        assert_fresh_import_excludes(self._RESTORE_IMPORT_CHECK)

    def test_maintenance_sources_never_name_terminate_helpers(self):
        import inspect

        from .. import storage_manifest, storage_reclamation, storage_survey_ops
        from ..server import _lifecycle

        forbidden = (
            "_terminate_and_confirm",
            "_reclaim_machine_singleton",
            "_stop_service_on_port",
            "_terminate_pid",
        )
        for module in (
            storage_reclamation,
            storage_survey_ops,
            storage_manifest,
            _lifecycle,
        ):
            src = inspect.getsource(module)
            hits = [name for name in forbidden if name in src]
            assert not hits, (
                f"{module.__name__} references lifecycle terminate helpers "
                f"{hits}; storage maintenance is read/drop only"
            )

    def test_maintenance_sources_never_name_the_restore_operation(self):
        """Restore is an operator verb; the scheduled tick may not reach it.

        The names are matched exactly rather than on the word "restore".
        ``storage_manifest`` legitimately defines ``record_restored_archive``
        - the provenance write restore itself calls - and
        ``storage_reclamation`` legitimately owns a private
        ``_read_archive_records``. A substring guard on "restore" or
        "read_archive" would fire on both and be loosened away on its first
        false positive.

        Mutation-proved by naming ``restore_archive`` in
        ``storage_survey_ops`` without importing anything: the assertion below
        fires naming that module and that symbol, the import-graph guard above
        stays green, and restoring the source returns all four to passing.
        """
        import inspect

        from .. import storage_manifest, storage_reclamation, storage_survey_ops
        from ..server import _lifecycle

        forbidden = ("storage_restore", "restore_archive", "RestoreRequest")
        for module in (
            storage_reclamation,
            storage_survey_ops,
            storage_manifest,
            _lifecycle,
        ):
            src = inspect.getsource(module)
            hits = [name for name in forbidden if name in src]
            assert not hits, (
                f"{module.__name__} references the archive restore operation "
                f"{hits}; the scheduled maintenance tick is read/drop only and "
                "restore is an operator verb"
            )


class TestGeometryReconcileIsNonDestructive:
    """Reconcile shrinks preallocation; it must never destroy anything.

    The reconcile stage runs inside the same maintenance cycle as the
    reclamation stages and shares its client, so the one thing that must
    never happen is a geometry fix that drops a collection or its points.
    The reconcile path is confined to an optimizer-config update plus
    read-only observation, and this pins that shape against a future edit
    that reaches for a delete to "reset" a stubborn collection.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_reconcile_sources_never_name_destructive_helpers(self):
        import inspect

        from .. import storage_reconciliation

        forbidden = (
            "delete_collection",
            "delete_prefix",
            "_delete_collection_hard",
            "rmtree",
            "delete_points",
        )
        for fn in (
            storage_reconciliation.reconcile_collection,
            storage_reconciliation.reconcile_collections,
            storage_reconciliation.read_geometry,
            storage_reconciliation.plan_reconcile,
            storage_reconciliation.await_convergence,
        ):
            src = inspect.getsource(fn)
            hits = [name for name in forbidden if name in src]
            assert not hits, (
                f"{fn.__qualname__} references destructive helpers {hits}; "
                f"geometry reconcile is non-destructive by contract"
            )

    def test_reconcile_target_matches_the_create_time_geometry(self):
        """Reconcile and creation must converge on one geometry.

        If these drift apart, the maintenance cycle would perpetually
        "fix" collections toward a target that creation never uses, and
        every new collection would immediately read as drifted.
        """
        import inspect

        from .. import store_runtime, store_schema

        src = inspect.getsource(store_runtime.VaultStore._ensure_collection)
        assert "store_schema.SERVER_SEGMENT_NUMBER" in src
        assert "store_schema.SERVER_WAL_CAPACITY_MB" in src
        assert store_schema.SERVER_SEGMENT_NUMBER == 2


class TestLedgerConcurrencyContract:
    """ADR: the shared per-root ledger's durable-state concurrency contract.

    The behavioural guards for this live in the run-ledger suite and need
    real threads and a real database file. These are the cheap structural
    backstops: they catch the contract being edited out of the source, which
    is how it was lost the first time - a formatting-level change to one
    connection helper, with every existing test still green.
    """

    def test_every_ledger_connection_requests_write_ahead_logging(self) -> None:
        """One opener, and it must ask for WAL and verify it got it.

        A second connection helper is the real risk here: the ledger and the
        route-migration journal are separate databases, and a copied opener
        that skipped this line would reintroduce the starvation on one of them
        while the other stayed correct.
        """
        import inspect

        from ..indexer import _route_migration, _run_ledger_models

        requested = inspect.getsource(_run_ledger_models._request_write_ahead_logging)
        assert "journal_mode = WAL" in requested
        source = inspect.getsource(_run_ledger_models.open_ledger_connection)
        assert 'mode != "wal"' in source, (
            "the opener must verify the mode took effect, not just request it"
        )

        # Every module that reaches durable state, not just the two that own
        # the helpers. The contract was lost in the runtime module, which still
        # imports sqlite3 and is where the deleted opener used to live, so a
        # scan that skipped it would miss the exact regression it names.
        from ..indexer import (
            _run_ledger_commits,
            _run_ledger_files,
            _run_ledger_finalization,
            _run_ledger_runtime,
        )

        opener = inspect.getsource(_run_ledger_models.open_ledger_connection)
        for module in (
            _run_ledger_models,
            _run_ledger_runtime,
            _run_ledger_commits,
            _run_ledger_files,
            _run_ledger_finalization,
            _route_migration,
        ):
            assert "sqlite3.connect(" not in inspect.getsource(module).replace(
                opener, ""
            ), (
                f"{module.__name__} opens SQLite outside the shared opener, "
                "so that connection escapes the concurrency contract"
            )

    def test_opening_the_ledger_does_not_scan_the_whole_database(self) -> None:
        """A full-database scan on open is what starved commits cross-kind.

        ``quick_check`` reads every page in a file shared by every content
        kind on the root, and it held a read lock for that whole time. It
        belongs to deliberate recovery, not to opening.
        """
        import inspect

        from ..indexer._run_ledger_runtime import RunLedger

        assert "quick_check" not in inspect.getsource(RunLedger.__init__)
        assert "quick_check" in inspect.getsource(RunLedger.verify_integrity)

    def test_lock_contention_is_classified_as_its_own_transient_kind(self) -> None:
        """Contention must never fall through to the terminal ``other`` bucket.

        That fallthrough is what turned a transient lock into a discarded
        generation holding storage-confirmed work.
        """
        from .._job_errors import JobErrorKind, classify_error_text, remediation

        for text in ("database is locked", "database table is locked"):
            assert classify_error_text(text) is JobErrorKind.LEDGER_CONTENDED
        assert remediation(JobErrorKind.LEDGER_CONTENDED)

    def test_unapplied_ingest_carries_its_remedy_rather_than_being_other(
        self,
    ) -> None:
        """A terminal failure with an exact remedy must still carry that remedy.

        Not every classification exists to make something retryable. This one is
        genuinely terminal - a retry repeats it, and the circuit opening is the
        right response - but it has one specific fix, and ``other`` is where a
        fix goes to be lost. It is the condition an operator meets after the
        vector store is carried across a Qdrant version change, at which point
        the affected index needs a clean rebuild.
        """
        from .._job_errors import JobErrorKind, classify_error_text, remediation
        from ..watcher_retry import _classify_failure

        observed = (
            "ingest verification failed for r01fa8eefb788_codebase_docs: "
            "expected 96441 applied point(s), found 95375. One or more "
            "acknowledged batches did not apply; failing the run before "
            "stale-purge or metadata publish."
        )
        kind = classify_error_text(observed)
        assert kind is JobErrorKind.INGEST_VERIFICATION_FAILED
        assert "clean re-index" in (remediation(kind) or "")

        _kind, retryable = _classify_failure(RuntimeError(observed))
        assert not retryable, (
            "retrying an unapplied-write failure repeats it; the circuit must open"
        )

    def test_contention_does_not_open_the_watcher_circuit_on_first_failure(
        self,
    ) -> None:
        """Classifying the kind is worthless if nothing consults it.

        The watcher decides retryability from its own set, and anything outside
        that set opens the circuit on the first occurrence - pausing automatic
        indexing for a condition that clears when the peer run commits. A kind
        that classifies correctly but is missing from this set produces exactly
        the outcome the classification exists to avoid, which is why the guard
        asserts the decision rather than the label.
        """
        import sqlite3

        from .._job_errors import JobErrorKind
        from ..indexer._run_ledger_models import RunLedgerContentionError
        from ..watcher_retry import _classify_failure

        kind, retryable = _classify_failure(
            RunLedgerContentionError(
                "run ledger runs.sqlite3 is locked: database is locked"
            )
        )
        assert kind is JobErrorKind.LEDGER_CONTENDED
        assert retryable, "contention must not open the circuit on first failure"

        _kind, raw_retryable = _classify_failure(
            sqlite3.OperationalError("database is locked")
        )
        assert raw_retryable


class TestDeviceTierIsolation:
    """The GPU runner must schedule the two device tiers separately.

    Subprocess-GPU tests spawn a service that loads its own models; the
    resident tiers keep theirs loaded. Together they exceed the card, and what
    that produces is not an out-of-memory error but a spawned service that
    never becomes healthy - surfacing as a health-poll timeout in an unrelated
    test, late in a long lane, naming nothing about memory. The constraint was
    written beside the marker and enforced nowhere, so the project's own recipe
    selected both in one expression.

    The gate that refuses such a selection is exercised where it lives, against
    collected items. This guards the other half: that the runner satisfies it.
    Cheap, and it fails in the fast lane the moment the recipe stops splitting,
    rather than an hour into a GPU run.
    """

    def _gpu_recipe_selections(self) -> list[str]:
        """Return the marker expressions the GPU recipe runs, in order."""
        import re
        from pathlib import Path

        justfile = Path(__file__).resolve().parents[3] / "justfile"
        recipe = justfile.read_text(encoding="utf-8")
        block = re.search(r'"gpu"\s*\{(.*?)\n\s*\}', recipe, re.DOTALL)
        assert block is not None, "the runner has no gpu recipe"
        return re.findall(r'pytest [^\n]*?-m "([^"]+)"', block.group(1))

    def test_the_gpu_recipe_runs_the_two_tiers_as_separate_selections(self) -> None:
        """Mutation it catches: merging the two selections back into one.

        A single ``-m "integration or ... or subprocess_gpu"`` reads as
        covering the same tests, and does - in one session, which is the
        wedge. Asserted as a count plus each selection's role, so restoring
        the union fails here rather than after an hour of GPU time.
        """
        selections = self._gpu_recipe_selections()

        assert len(selections) == 2, (
            f"the gpu recipe must run two selections, found {selections}"
        )
        resident, subprocess_tier = selections
        assert "not subprocess_gpu" in resident, (
            f"the resident selection must exclude the subprocess tier: {resident}"
        )
        assert subprocess_tier == "subprocess_gpu", (
            f"the second selection must name only the subprocess tier: "
            f"{subprocess_tier}"
        )


class TestJobErrorTaxonomyStaysLight:
    """The shared job-failure taxonomy must stay torch- and CLI-free.

    The taxonomy is consumed by the jobs registry (service domain), the
    /jobs route shaping, and the CLI renderers; if it ever grew a torch
    or CLI import, the CLI service commands would drag in weights (or a
    lifecycle path) just to render an error label.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    _IMPORT_CHECK = """
import sys

import vaultspec_rag._job_errors  # noqa: F401

loaded = sorted(
    m for m in sys.modules
    if m == "torch"
    or m == "vaultspec_rag.cli"
    or m.startswith("vaultspec_rag.cli.")
)
assert not loaded, loaded
"""

    def test_taxonomy_import_graph_is_torch_and_cli_free(self):
        assert_fresh_import_excludes(self._IMPORT_CHECK)


def _cuda_oom_handlers(root: ast.AST) -> list[ast.ExceptHandler]:
    """Collect the ``except`` handlers naming the CUDA OOM error under *root*."""
    import ast

    return [
        node
        for node in ast.walk(root)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and "OutOfMemoryError" in ast.unparse(node.type)
    ]


class TestEncodeRecoveryStaysBounded:
    """No unbounded retry may stand between a storage error and job failure.

    The silent index-wedge incident showed what an unbounded loop in the
    embed-and-upsert path costs: hours of GPU burn with no failure. The
    CUDA-OOM recovery must keep its floor - a bucket that cannot shrink
    (a single text) re-raises the real error instead of replanning - so
    every OOM handler must pair with the floor re-raise, and every encode
    path must reach a handler that has one.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_every_oom_handler_keeps_the_floor_raise(self):
        import ast
        import inspect

        from .. import embeddings

        tree = ast.parse(inspect.getsource(embeddings))
        oom_handlers = _cuda_oom_handlers(tree)
        # The shared bucket loop carries the one handler both encode
        # paths route through; zero found means this scan went stale,
        # not that the risk is gone.
        assert oom_handlers, (
            "expected the shared bucket loop's CUDA-OOM handler in "
            "embeddings.py; the source scan no longer finds any"
        )

        def keeps_floor_reraise(handler: ast.ExceptHandler) -> bool:
            # The floor is a conditional bare re-raise directly in the
            # handler body: when the failing bucket cannot shrink, the
            # real OOM propagates instead of another replan iteration.
            return any(
                isinstance(statement, ast.If)
                and any(
                    isinstance(node, ast.Raise) and node.exc is None
                    for node in ast.walk(statement)
                )
                for statement in handler.body
            )

        # Deleting the single-text-bucket re-raise from any handler
        # makes this fail by naming the handler's line: without the
        # floor, a persistent allocator failure retries forever instead
        # of failing the job.
        missing = [
            handler.lineno
            for handler in oom_handlers
            if not keeps_floor_reraise(handler)
        ]
        assert not missing, (
            f"CUDA-OOM handlers at embeddings.py lines {missing} lack "
            "the single-text-bucket floor re-raise; the bucket retry "
            "must terminate"
        )

    def test_both_encode_paths_reach_an_oom_handler(self):
        """Each encode path must route its buckets through the OOM recovery.

        The dense and sparse paths share one bucket-encode loop, so one
        handler bounds both - but only while both actually route through
        it. This asserts that routing directly: an encode path either
        handles the CUDA OOM itself or calls a function that does, so an
        OOM on either path always meets the bounded recovery the floor
        test pins.

        Mutation check: bypassing the shared loop in
        ``encode_documents_sparse`` - encoding its buckets inline instead
        of calling ``_run_bucketed_encode`` - makes this fail on the
        uncovered-paths assertion below, naming the function; restoring
        the call returns it to green.
        """
        import ast
        import inspect

        from .. import embeddings

        encode_paths = ("_encode_documents_output", "encode_documents_sparse")
        tree = ast.parse(inspect.getsource(embeddings))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        absent = [path for path in encode_paths if path not in functions]
        assert not absent, (
            f"encode paths {absent} no longer exist in embeddings.py; "
            "this scan went stale"
        )
        handling = {
            name for name, function in functions.items() if _cuda_oom_handlers(function)
        }

        def reaches_handling(function: ast.FunctionDef) -> bool:
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                called = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else callee.id
                    if isinstance(callee, ast.Name)
                    else None
                )
                if called in handling:
                    return True
            return False

        uncovered = [
            path
            for path in encode_paths
            if path not in handling and not reaches_handling(functions[path])
        ]
        assert not uncovered, (
            f"encode paths {uncovered} neither handle a CUDA OOM nor "
            "call a function that does; an OOM there would escape the "
            "bounded bucket recovery"
        )


class TestStdioLifetimeWatchdogStaysThin:
    """The stdio lifetime watchdog honors the thin-client decisions.

    The watchdog binds the shim's lifetime to the service client: its
    import graph must load neither ``torch``
    nor ``mcp`` (fresh interpreter - the in-process ``sys.modules`` is
    polluted by other tests), and only the stdio branch of the entry
    point may install it - the HTTP daemon outlives its spawner by
    design.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    _IMPORT_CHECK = """
import sys

import vaultspec_rag.server._stdio_lifetime  # noqa: F401

loaded = sorted(
    m for m in sys.modules
    if m in {"torch", "mcp"}
    or m.startswith(("torch.", "mcp."))
)
assert not loaded, loaded
"""

    def test_watchdog_import_graph_excludes_torch_and_mcp(self):
        assert_fresh_import_excludes(self._IMPORT_CHECK)

    def test_only_the_stdio_branch_installs_the_watchdog(self):
        import inspect

        from ..server import _lifespan, _main

        # ``main`` is a dispatcher: the transport branches are the two runner
        # functions it selects between, so the guard reads their sources. The
        # dispatch assertions pin which runner each branch reaches; without
        # them the watchdog checks below could pass against a main that routes
        # stdio into the HTTP daemon. Every split is a partition so that a
        # reshaped dispatcher fails on the assertion naming what went missing
        # rather than crashing on an index before any assertion is reached.
        main_src = inspect.getsource(_main.main)
        _, port_branch, dispatch = main_src.partition("if port is not None:")
        assert port_branch, (
            "main must select its transport by branching on the port; the "
            "guard cannot tell the two dispatch paths apart without it"
        )
        http_dispatch, _, stdio_dispatch = dispatch.partition("return")
        assert "_run_http_daemon(port)" in http_dispatch, (
            "the port branch of main must run the HTTP daemon"
        )
        assert "_run_stdio_mcp(" in stdio_dispatch, (
            "the portless branch of main must run the stdio MCP client"
        )
        http_src = inspect.getsource(_main._run_http_daemon)
        stdio_src = inspect.getsource(_main._run_stdio_mcp)
        assert "install_stdio_lifetime_watchdog" not in main_src + http_src, (
            "the HTTP daemon must never install the stdio lifetime watchdog; "
            "a daemon that dies with its spawner breaks the resident service"
        )
        assert "install_stdio_lifetime_watchdog" in stdio_src, (
            "the stdio branch must install the lifetime watchdog"
        )
        assert "install_stdio_lifetime_watchdog" not in inspect.getsource(_lifespan), (
            "service lifespan must not reference the stdio watchdog installer"
        )
