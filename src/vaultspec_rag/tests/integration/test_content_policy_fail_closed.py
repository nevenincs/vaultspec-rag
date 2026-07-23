"""Real-resource integration coverage for fail-closed index policy gates."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Generator

    from ...indexer import CodebaseIndexer
    from ...store import VaultStore

pytestmark = [pytest.mark.integration]


class PolicyBoundaryProject(TypedDict):
    indexer: CodebaseIndexer
    store: VaultStore
    metadata_path: Path
    cache_root: Path


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Return the exact observable file state below one bounded test path."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _json_state(root: Path) -> dict[str, bytes]:
    """Snapshot bounded durable JSON state without reading unrelated binaries."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.json")
        if path.is_file()
    }


@pytest.fixture
def policy_boundary_project(
    tmp_path: Path,
) -> Generator[PolicyBoundaryProject]:
    """Seed a real collection, sidecar, and cache behind conflicting routing."""
    from ... import CodebaseIndexer, VaultStore
    from ...config import get_config
    from ...indexer._content_policy import (
        ContentKind,
        ContentRoute,
        RootContentPolicy,
        SourceProfileVersion,
    )
    from ...indexer._preprocess_cache import preprocess_cache_dir
    from ...indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
    from ...store import CodeChunk

    routed_dir = tmp_path / "incoming"
    routed_dir.mkdir()
    (routed_dir / "payload.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / PREPROCESS_CONFIG_FILENAME).write_text(
        """
        version = 2

        [[rule]]
        pattern = "**/*.bin"
        command = "extract {path}"
        target = "document"
        extractor_version = "1"
        """,
        encoding="utf-8",
    )

    store = VaultStore(tmp_path)
    store.upsert_code_chunks(
        [
            CodeChunk(
                id="existing-sentinel",
                path="existing.py",
                language="python",
                content="existing = True",
                line_start=1,
                line_end=1,
                vector=[0.0] * int(get_config().embedding_dimension),
            )
        ],
        write_policy=None,
    )

    data_root = tmp_path / get_config().data_dir
    metadata_path = data_root / get_config().code_index_metadata_file
    metadata_path.write_bytes(b'{"sentinel":"metadata"}')
    cache_root = preprocess_cache_dir(data_root)
    cache_root.mkdir(parents=True)
    (cache_root / "sentinel.json").write_bytes(b'{"sentinel":"cache"}')

    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        store,
        content_policy=RootContentPolicy(
            SourceProfileVersion.EXPLICIT_ONLY_V1,
            (ContentRoute("incoming/*", ContentKind.CODE),),
        ),
    )
    try:
        yield PolicyBoundaryProject(
            indexer=indexer,
            store=store,
            metadata_path=metadata_path,
            cache_root=cache_root,
        )
    finally:
        store.close()


def test_api_rejects_invalid_policy_before_model_or_store_acquisition(
    tmp_path: Path,
) -> None:
    """A fresh API process fails on policy even when CUDA is unavailable."""
    from ...config import get_config
    from ...indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

    root = tmp_path / "invalid-api-root"
    root.mkdir()
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        """
        version = 2

        [[rule]]
        pattern = "*.bin"
        command = "extract {path}"
        target = "unknown"
        extractor_version = "1"
        """,
        encoding="utf-8",
    )
    before = _tree_bytes(root)
    script = """
import pathlib
import sys

from vaultspec_rag.api import index_codebase  # absolute-import-ok
from vaultspec_rag.indexer._preprocess_config import (  # absolute-import-ok
    PreprocessPolicyError,
)
from vaultspec_rag.registry import get_registry  # absolute-import-ok

registry = get_registry()
before = registry.health()
try:
    index_codebase(pathlib.Path(sys.argv[1]), clean=True)
except PreprocessPolicyError:
    pass
else:
    raise RuntimeError("invalid policy unexpectedly reached index execution")
after = registry.health()
assert before["model_loaded"] is False
assert after["model_loaded"] is False
assert before["project_count"] == after["project_count"] == 0
"""
    environment = dict(os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = ""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(root)],
        cwd=Path(__file__).parents[4],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert _tree_bytes(root) == before
    assert not (root / get_config().data_dir).exists()


@pytest.mark.parametrize("entrypoint", ("full_index", "incremental_index"))
def test_conflicting_routing_leaves_real_index_resources_unchanged(
    policy_boundary_project: PolicyBoundaryProject,
    entrypoint: str,
) -> None:
    """Both public code-index operations reject before mutation authority."""
    from ...indexer._content_policy import AdmissionPolicyError

    indexer = policy_boundary_project["indexer"]
    store = policy_boundary_project["store"]
    metadata_path = policy_boundary_project["metadata_path"]
    cache_root = policy_boundary_project["cache_root"]
    before_ids = store.get_all_code_ids()
    before_metadata = metadata_path.read_bytes()
    before_cache = _tree_bytes(cache_root)

    operation = getattr(indexer, entrypoint)
    kwargs: dict[str, object] = {"reporter": NullProgressReporter()}
    if entrypoint == "full_index":
        kwargs["clean"] = True
    with pytest.raises(AdmissionPolicyError, match="conflicting explicit"):
        if entrypoint == "full_index":
            kwargs["preflight"] = indexer.preflight_content()
        else:
            changed = indexer.root_dir / "incoming" / "payload.bin"
            kwargs["changed_paths"] = (changed,)
            kwargs["preflight"] = indexer.preflight_changed_paths((changed,))
        operation(**kwargs)

    assert store.get_all_code_ids() == before_ids == {"existing-sentinel"}
    assert metadata_path.read_bytes() == before_metadata
    assert _tree_bytes(cache_root) == before_cache


def test_missing_mismatched_and_foreign_preflights_are_mutation_free(
    tmp_path: Path,
) -> None:
    """Direct mutators reject absent or forged authority before store writes."""
    from ... import CodebaseIndexer, VaultStore
    from ...config import get_config
    from ...indexer._codebase_indexer import CodeScopedPreflight
    from ...store import CodeChunk

    root = tmp_path / "target"
    foreign_root = tmp_path / "foreign"
    root.mkdir()
    foreign_root.mkdir()
    first = root / "first.py"
    second = root / "second.py"
    foreign = foreign_root / "foreign.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 2\n", encoding="utf-8")
    foreign.write_text("foreign = 3\n", encoding="utf-8")

    store = VaultStore(root)
    store.upsert_code_chunks(
        [
            CodeChunk(
                id="authority-sentinel",
                path="sentinel.py",
                language="python",
                content="sentinel = True",
                line_start=1,
                line_end=1,
                vector=[0.0] * int(get_config().embedding_dimension),
            )
        ],
        write_policy=None,
    )
    indexer = CodebaseIndexer(root, cast("Any", None), store)
    foreign_indexer = CodebaseIndexer(
        foreign_root,
        cast("Any", None),
        cast("Any", None),
    )
    data_root = root / get_config().data_dir
    before_ids = store.get_all_code_ids()
    before_json = _json_state(data_root)
    reporter = NullProgressReporter()
    try:
        with pytest.raises(TypeError, match="preflight"):
            cast("Any", indexer.incremental_index)(reporter=reporter)

        scoped = indexer.preflight_changed_paths((first,))
        with pytest.raises(ValueError, match="scope does not match"):
            indexer.incremental_index(
                reporter=reporter,
                changed_paths=(second,),
                preflight=scoped,
            )

        foreign_authority = foreign_indexer.preflight_changed_paths((foreign,))
        forged = CodeScopedPreflight(
            root_dir=root.resolve(),
            policy=foreign_authority.policy,
            changed_paths=(first.resolve(),),
        )
        with pytest.raises(ValueError, match="belongs to another root"):
            indexer.incremental_index(
                reporter=reporter,
                changed_paths=(first,),
                preflight=forged,
            )
        assert store.get_all_code_ids() == before_ids == {"authority-sentinel"}
        assert _json_state(data_root) == before_json
    finally:
        store.close()


def test_invalid_job_policy_does_not_admit_or_persist_a_job(tmp_path: Path) -> None:
    """Job validation fails before canonical or compatibility ledger mutation."""
    from ... import jobs
    from ...config import get_config
    from ...indexer._preprocess_config import (
        PREPROCESS_CONFIG_FILENAME,
        PreprocessPolicyError,
    )

    root = tmp_path / "invalid-job-root"
    root.mkdir()
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        """
        version = 2

        [[rule]]
        pattern = "*.bin"
        command = "extract {path}"
        target = "unknown"
        extractor_version = "1"
        """,
        encoding="utf-8",
    )
    status_root = Path(str(get_config().status_dir)).expanduser()
    before_records = jobs.snapshot()
    before_durable_state = _json_state(status_root)

    with pytest.raises(PreprocessPolicyError, match="unknown"):
        jobs.start_reindex_codebase(root, clean=True)

    assert jobs.snapshot() == before_records
    assert _json_state(status_root) == before_durable_state
    assert not (root / get_config().data_dir).exists()
