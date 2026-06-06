"""Public API facade for vaultspec-rag.

Thin wrappers around :class:`ServiceRegistry.lease`.  Every facade
function acquires a refcounted lease on the per-project slot, so the
eviction machinery (idle TTL + LRU cap + busy-slot skip) applies to
direct API consumers as well as MCP tool handlers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from .graph_cache import GraphCache
from .progress import NullProgressReporter
from .registry import get_registry

if TYPE_CHECKING:
    import pathlib

    from .indexer import IndexResult
    from .progress import ProgressReporter
    from .search import SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "GraphCache",
    "clean",
    "get_related",
    "get_service_state",
    "get_status",
    "index",
    "index_codebase",
    "list_documents",
    "run_benchmark",
    "run_quality_probe",
    "scan_codebase_files",
    "search_codebase",
    "search_vault",
]


def _resolve(root_dir: pathlib.Path) -> pathlib.Path:
    from pathlib import Path

    return Path(root_dir).resolve()


def index(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
    clean: bool = False,
    reporter: ProgressReporter | None = None,
    model_name: str | None = None,
) -> IndexResult:
    """Index vault documents, returning an :class:`IndexResult`.

    Invalidates the cached :class:`VaultGraph` after indexing so that
    subsequent ``get_related`` calls reflect updated documents.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index; otherwise incremental.
        clean: If ``True``, drop and recreate the collection.
        reporter: Optional progress reporter. A ``NullProgressReporter``
            is used when omitted so library consumers can call this
            facade without any UI.
        model_name: Optional override for the dense embedding model name.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed documents.
    """
    root = _resolve(root_dir)
    rep = reporter if reporter is not None else NullProgressReporter()
    registry = get_registry()
    registry.load_model(model_name)
    with registry.lease(root) as slot:
        result = (
            slot.vault_indexer.full_index(clean=clean, reporter=rep)
            if (full or clean)
            else slot.vault_indexer.incremental_index(reporter=rep)
        )
        slot.graph_cache.invalidate()
        return result


def index_codebase(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
    clean: bool = False,
    reporter: ProgressReporter | None = None,
    model_name: str | None = None,
    extra_excludes: list[str] | None = None,
) -> IndexResult:
    """Index codebase source files, returning an :class:`IndexResult`.

    Does **not** invalidate the vault graph cache because code
    changes do not affect vault document relationships.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index; otherwise
            incremental.
        clean: If ``True``, drop and recreate the codebase collection.
        reporter: Optional progress reporter.
        model_name: Optional override for the dense embedding model name.
        extra_excludes: Optional list of ad-hoc exclusion patterns.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed code chunks.
    """
    root = _resolve(root_dir)
    rep = reporter if reporter is not None else NullProgressReporter()
    registry = get_registry()
    registry.load_model(model_name)
    with registry.lease(root) as slot:
        if extra_excludes is not None:
            slot.code_indexer._extra_excludes = extra_excludes
        if full or clean:
            return slot.code_indexer.full_index(clean=clean, reporter=rep)
        return slot.code_indexer.incremental_index(reporter=rep)


def search_vault(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
) -> list[SearchResult]:
    """Search the documentation vault.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query.
        top_k: Number of results to return.
        doc_type: Optional vault doc-type filter (e.g. ``'adr'``).
        feature: Optional feature-tag filter.
        date: Optional ISO date filter.
        tag: Optional free-form tag filter.
        like_ids: Optional list of document IDs or point IDs to guide search.
        unlike_ids: Optional list of document IDs or point IDs to push search away.

    Returns:
        Ranked list of SearchResult objects.
    """
    from .search import validate_search_filters

    validate_search_filters(
        "vault",
        doc_type=doc_type,
        feature=feature,
        date=date,
        tag=tag,
    )
    root = _resolve(root_dir)
    registry = get_registry()
    registry.load_model()
    with registry.lease(root) as slot:
        return slot.searcher.search_vault(
            query,
            top_k=top_k,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )


def search_codebase(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
) -> list[SearchResult]:
    """Search the source codebase.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query or code snippet.
        top_k: Number of results to return.
        language: Optional language filter (e.g., ``'python'``,
            ``'rust'``).
        path: Optional exact-match path filter (KEYWORD payload
            index).
        node_type: Optional AST node type filter.
        function_name: Optional function/method name filter.
        class_name: Optional class/struct name filter.
        include_paths: Optional fnmatch glob patterns kept by
            post-query filter (e.g. ``['src/foo/**']``).
        exclude_paths: Optional fnmatch glob patterns dropped by
            post-query filter (e.g. ``['locales/*.yml',
            'tests/**']``).
        dedup_locales: When True, collapse near-tie locale variants
            into a single canonical result. Opt-in.
        prefer: Optional ``"prod" | "tests" | "docs"`` - applies a
            small +/- score nudge to the matching category after
            rerank. Opt-in.
        like_ids: Optional list of chunk IDs or point IDs to guide search.
        unlike_ids: Optional list of chunk IDs or point IDs to push search away.

    Returns:
        Ranked list of SearchResult objects.
    """
    from .search import validate_search_filters

    validate_search_filters(
        "code",
        language=language,
        path=path,
        node_type=node_type,
        function_name=function_name,
        class_name=class_name,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        dedup_locales=dedup_locales,
        prefer=prefer,
    )
    root = _resolve(root_dir)
    registry = get_registry()
    registry.load_model()
    with registry.lease(root) as slot:
        return slot.searcher.search_codebase(
            query,
            top_k=top_k,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )


def list_documents(
    root_dir: pathlib.Path,
    doc_type: str | None = None,
) -> list[dict[str, object]]:
    """List all indexed documents, optionally filtered by doc_type.

    Args:
        root_dir: Workspace root directory.
        doc_type: If provided, only return documents of this type
            (e.g., ``"adr"``, ``"plan"``).

    Returns:
        List of document dicts with keys ``id``, ``path``,
        ``doc_type``, ``title``, etc.  Returns an empty list when
        no documents match.
    """
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        return slot.store.list_all_documents(doc_type=doc_type)


def get_related(
    root_dir: pathlib.Path,
    doc_id: str,
) -> dict[str, object] | None:
    """Get graph relationships for a document.

    Args:
        root_dir: Workspace root directory.
        doc_id: Document identifier (relative path without
            extension, e.g. ``"adr/overview"``).

    Returns:
        A dict with keys ``doc_id`` (str), ``outgoing``
        (sorted list of linked doc IDs), and ``incoming``
        (sorted list of back-linking doc IDs).  Returns
        ``None`` if the vault graph could not be built or
        if *doc_id* is not present in the graph.
    """
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        graph = slot.graph_cache.get(root)
        if graph is None:
            return None
        node = graph.nodes.get(doc_id)
        if node is None:
            return None
        return {
            "doc_id": doc_id,
            "outgoing": sorted(node.out_links),
            "incoming": sorted(node.in_links),
        }


def clean(
    root_dir: pathlib.Path,
    *,
    clean_type: Literal["vault", "code", "all"] = "all",
) -> list[str]:
    """Wipe the selected collections and their index metadata sidecars.

    Does not load embedding models or touch GPUs.

    Args:
        root_dir: Workspace root directory.
        clean_type: What to wipe: 'vault', 'code', or 'all'.

    Returns:
        List of cleared source labels (e.g. ['vault', 'codebase']).
    """
    root = _resolve(root_dir)
    from .config import get_config
    from .registry import get_registry
    from .store import VaultStore

    cfg = get_config()
    cleared: list[str] = []

    # Evict project from registry to close Qdrant connections and release locks
    registry = get_registry()
    registry.close_project(root)

    store = VaultStore(root)
    try:
        do_vault = clean_type in ("vault", "all")
        do_code = clean_type in ("code", "all")
        if do_vault:
            store.drop_table()
            store.ensure_table()
            cleared.append("vault")
        if do_code:
            store.drop_code_table()
            store.ensure_code_table()
            cleared.append("codebase")
    finally:
        store.close()

    data_dir = root / cfg.data_dir
    if clean_type in ("vault", "all"):
        meta = data_dir / cfg.index_metadata_file
        meta.unlink(missing_ok=True)
    if clean_type in ("code", "all"):
        meta = data_dir / cfg.code_index_metadata_file
        meta.unlink(missing_ok=True)

    return cleared


def get_status(root_dir: pathlib.Path) -> dict[str, object]:
    """Return status of the RAG engine, storage metrics, and GPU info.

    Args:
        root_dir: Workspace root directory.

    Returns:
        Dict containing RAG status information.
    """
    root = _resolve(root_dir)
    torch: Any = None
    try:
        import torch as _torch

        torch = _torch
    except ImportError:
        pass

    cuda_available = torch is not None and torch.cuda.is_available()
    if cuda_available:
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mb = props.total_memory // (1024 * 1024)
        vram_gb = round(props.total_memory / 1e9, 2)
    else:
        gpu_name = None
        vram_mb = 0
        vram_gb = 0.0

    from .capabilities import backend_capabilities_dict
    from .registry import get_registry
    from .store import VaultStore

    registry = get_registry()
    slot = registry._projects.get(root)
    if slot is not None:
        store = slot.store
        own_store = False
    else:
        store = VaultStore(root)
        own_store = True

    try:
        vault_count = store.count()
        code_count = store.count_code()
        storage_path = str(store.db_path)
    finally:
        if own_store:
            store.close()

    return {
        "cuda": cuda_available,
        "gpu_name": gpu_name,
        "vram_mb": vram_mb,
        "vram_gb": vram_gb,
        "storage_path": storage_path,
        "vault_documents": vault_count,
        "codebase_chunks": code_count,
        "vault_count": vault_count,
        "code_count": code_count,
        "target_dir": str(root),
        "backend_capabilities": backend_capabilities_dict(),
    }


def scan_codebase_files(
    root_dir: pathlib.Path,
    *,
    extra_excludes: list[str] | None = None,
) -> list[pathlib.Path]:
    """Scan the codebase, returning list of paths that would be indexed.

    Does not require GPU or vector store - safe for dry-runs.
    """
    root = _resolve(root_dir)
    from .indexer import CodebaseIndexer

    indexer = CodebaseIndexer(
        root_dir=root,
        model=cast("Any", None),
        store=cast("Any", None),
        extra_excludes=extra_excludes,
    )
    return indexer.scan_files()


def run_benchmark(
    root_dir: pathlib.Path,
    *,
    n_queries: int = 20,
) -> dict[str, Any]:
    """Run search latency benchmarks against the indexed vault.

    Args:
        root_dir: Workspace root directory.
        n_queries: Number of search queries to time.

    Returns:
        Dict containing benchmark results: p50, p95, p99, mean, stdev,
        vault_count, code_count, gpu_name, vram_mb.
    """
    import statistics
    import time

    root = _resolve(root_dir)
    registry = get_registry()
    registry.load_model()

    with registry.lease(root) as slot:
        vault_count = slot.store.count()
        if vault_count == 0:
            raise ValueError("No vault documents indexed.")

        code_count = slot.store.count_code()

        # Warmup
        slot.searcher.search_vault("warmup", top_k=1)

        _bench_queries = [
            "architecture decision",
            "pipeline execution model",
            "connector protocol design",
            "security audit vulnerability",
            "implementation plan phase",
            "type:adr architecture",
            "feature:pipeline-engine execution",
            "scheduler algorithm selection",
            "pipeline executor implementation",
            "dag execution research",
            "data transformation pipeline",
            "worker pool thread",
            "type:plan implementation",
            "semantic search embedding",
            "Qdrant vector store",
            "date:2026-01 decisions",
            "checkpoint storage performance",
            "connector grpc streaming",
            "execution graph dependency",
            "incremental indexing hash",
        ]

        latencies: list[float] = []
        for i in range(n_queries):
            q = _bench_queries[i % len(_bench_queries)]
            t0 = time.perf_counter()
            slot.searcher.search_vault(q, top_k=5)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = latencies[n_queries // 2]
        p95 = latencies[int(n_queries * 0.95)]
        p99 = latencies[int(n_queries * 0.99)]
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        try:
            import torch

            gpu_name = (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
            )
            vram_mb = (
                torch.cuda.memory_allocated(0) / (1024 * 1024)
                if torch.cuda.is_available()
                else 0.0
            )
        except ImportError:
            gpu_name = "N/A"
            vram_mb = 0.0

        return {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "mean": mean,
            "stdev": stdev,
            "vault_count": vault_count,
            "code_count": code_count,
            "gpu": gpu_name,
            "vram_mb": vram_mb,
        }


def run_quality_probe(
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    """Run search quality probes against a synthetic test corpus.

    Generates a temporary synthetic vault, indexes it, runs
    needle-based precision probes, and returns results.

    Returns:
        Dict containing:
            - "passed": int
            - "total": int
            - "precision": float
            - "threshold": float
            - "probes": list of dicts with {"query": str, "label": str, "passed": bool}
    """
    import tempfile
    from pathlib import Path

    from .progress import NullProgressReporter
    from .synthetic import build_synthetic_vault

    registry = get_registry()
    registry.load_model()

    with tempfile.TemporaryDirectory(prefix="vaultspec-quality-") as tmp:
        root = Path(tmp)
        manifest = build_synthetic_vault(root, n_docs=24, seed=42)

        with registry.lease(root) as slot:
            slot.vault_indexer.full_index(reporter=NullProgressReporter())

            probes: list[dict[str, Any]] = []
            passed = 0

            needles = list(manifest.needles.items())[:8]
            for needle, doc_id in needles:
                results = slot.searcher.search_vault(needle, top_k=5)
                ok = any(doc_id in r.id for r in results)
                if ok:
                    passed += 1
                probes.append(
                    {
                        "query": needle,
                        "label": f"Needle → {doc_id}",
                        "expected_id": doc_id,
                        "passed": ok,
                    }
                )

            total = len(needles)
            precision = passed / total if total else 0.0

        registry.close_project(root)

        return {
            "passed": passed,
            "total": total,
            "precision": precision,
            "threshold": threshold,
            "probes": probes,
        }


def get_service_state(
    root_dir: pathlib.Path,
    *,
    watching_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state.

    Args:
        root_dir: Workspace root directory.
        watching_roots: Optional list of root paths currently watched.

    Returns:
        Dict containing index, projects, and watcher sections.
    """
    from datetime import datetime

    from .config import get_config
    from .registry import get_registry
    from .service import RegistryFullError
    from .store import VaultStoreLockedError

    root = _resolve(root_dir)

    try:
        index_data = get_status(root)
    except RegistryFullError as exc:
        index_data = {
            "error": "registry_full",
            "message": str(exc),
            "max_projects": exc.max_projects,
        }
    except VaultStoreLockedError as exc:
        index_data = {
            "error": "store_locked",
            "message": str(exc),
        }
    except Exception as exc:
        index_data = {
            "error": "unknown",
            "message": str(exc),
        }

    registry = get_registry()
    snapshot = registry.snapshot()
    wall_now = datetime.now().astimezone()
    projects = []
    for entry in snapshot:
        idle_s = float(entry["idle_seconds"])
        last_access_wall = wall_now.timestamp() - idle_s
        last_access_iso = (
            datetime.fromtimestamp(last_access_wall).astimezone().isoformat()
        )
        projects.append(
            {
                "root": str(entry["root"]),
                "last_access_iso": last_access_iso,
                "idle_seconds": idle_s,
                "ref_count": int(entry["ref_count"]),
            },
        )
    projects_data = {
        "projects": projects,
        "max_projects": registry.max_projects,
        "idle_ttl_seconds": registry.idle_ttl_seconds,
    }

    cfg = get_config()
    watching = watching_roots or []
    watcher_data: dict[str, Any] = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": watching,
        "running": str(root) in watching,
    }

    return {
        "index": index_data,
        "projects": projects_data,
        "watcher": watcher_data,
    }
