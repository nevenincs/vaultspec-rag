"""Real-resource integration coverage for fail-closed index policy gates."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Generator

    from ...embeddings import EmbeddingModel
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
    embedding_model: EmbeddingModel,
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
        pattern = "incoming/*.bin"
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
        embedding_model,
        store,
        content_policy=RootContentPolicy(
            SourceProfileVersion.EXPLICIT_ONLY_V1,
            (ContentRoute("incoming/*.bin", ContentKind.CODE),),
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
    with pytest.raises(AdmissionPolicyError, match="targets both"):
        operation(**kwargs)

    assert store.get_all_code_ids() == before_ids == {"existing-sentinel"}
    assert metadata_path.read_bytes() == before_metadata
    assert _tree_bytes(cache_root) == before_cache


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

    with pytest.raises(PreprocessPolicyError):
        jobs.start_reindex_codebase(root, clean=True)

    assert jobs.snapshot() == before_records
    assert _json_state(status_root) == before_durable_state
    assert not (root / get_config().data_dir).exists()
