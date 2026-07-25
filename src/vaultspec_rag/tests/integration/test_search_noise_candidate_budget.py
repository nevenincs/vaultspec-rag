"""Real-store verification for code-search candidate budgeting and backfill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...search._noise import NoisePolicy
from ...search._searcher import VaultSearcher
from ...store import CodeChunk, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.integration]


@pytest.fixture
def code_store(tmp_path: Path) -> Generator[VaultStore]:
    """Yield an isolated real Qdrant-local code store with small dense vectors."""
    store = VaultStore(tmp_path, embedding_dim=2)
    try:
        yield store
    finally:
        store.close()


def _chunk(index: int, path: str, vector: list[float]) -> CodeChunk:
    return CodeChunk(
        id=f"{path}:1-1-{index}",
        path=path,
        language="python",
        content=f"candidate_{index} = True",
        line_start=1,
        line_end=1,
        vector=vector,
    )


def _searcher_shell(
    root: Path,
    store: VaultStore,
    *,
    reranker_enabled: bool,
) -> VaultSearcher:
    """Construct the production search orchestrator without loading a model."""
    searcher = VaultSearcher.__new__(VaultSearcher)
    searcher.root_dir = root
    searcher.store = store
    searcher._reranker_enabled = reranker_enabled  # pyright: ignore[reportPrivateUsage]
    return searcher


def _fetch(
    searcher: VaultSearcher,
    *,
    top_k: int,
    policy: NoisePolicy,
    include_norm: list[str] | None = None,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    return searcher._fetch_codebase_candidates(  # pyright: ignore[reportPrivateUsage]
        query_vector=[1.0, 0.0],
        sparse_vector=None,
        query_text="candidate",
        store_filters={},
        top_k=top_k,
        include_norm=include_norm or [],
        exclude_norm=[],
        policy=policy,
        like_ids=None,
        unlike_ids=None,
        timings=None,
        notes=None,
    )


def test_pushed_domain_filters_use_normal_candidate_window(
    code_store: VaultStore,
    tmp_path: Path,
) -> None:
    """Pushed hard filters must not inherit the Python-glob 10x overfetch."""
    code_store.upsert_code_chunks(
        [
            _chunk(index, f"src/module_{index}.py", [1.0, index / 1_000.0])
            for index in range(60)
        ],
        write_policy=None,
    )
    searcher = _searcher_shell(tmp_path, code_store, reranker_enabled=True)
    pushed_policy = NoisePolicy(
        hide=frozenset({"generated", "worktree"}),
        only=frozenset(),
        demote=frozenset({"tests"}),
        penalty=0.3,
    )
    assert pushed_policy.has_hard_filter is True

    pushed_rows, pushed_drops = _fetch(
        searcher,
        top_k=5,
        policy=pushed_policy,
    )
    glob_rows, glob_drops = _fetch(
        searcher,
        top_k=5,
        policy=pushed_policy,
        include_norm=["src/**"],
    )

    # With the shipped reranker path active, the normal production budget is
    # max(4 * top_k, 20). An actual Python path glob retains
    # max(10 * top_k, 50).
    assert len(pushed_rows) == 20
    assert len(glob_rows) == 50
    assert pushed_drops == {}
    assert glob_drops == {}


def test_missing_domain_fallback_widens_until_survivors_fill_page(
    code_store: VaultStore,
    tmp_path: Path,
) -> None:
    """Legacy rows without domain payloads backfill after fallback depletion."""
    chunks = [
        _chunk(index, f"tests/test_{index}.py", [1.0, index / 100.0])
        for index in range(4)
    ]
    chunks.extend(
        [
            _chunk(4, "src/prod_a.py", [0.2, 0.8]),
            _chunk(5, "src/prod_b.py", [0.1, 0.9]),
        ]
    )
    code_store.upsert_code_chunks(chunks, write_policy=None)
    code_store.client.delete_payload(
        collection_name=code_store.CODE_TABLE_NAME,
        keys=["domain"],
        points=[code_store._stable_id(chunk.id) for chunk in chunks],  # pyright: ignore[reportPrivateUsage]
    )
    searcher = _searcher_shell(tmp_path, code_store, reranker_enabled=False)
    hide_tests = NoisePolicy(
        hide=frozenset({"tests"}),
        only=frozenset(),
        demote=frozenset(),
        penalty=0.0,
    )

    rows, dropped = _fetch(searcher, top_k=2, policy=hide_tests)

    assert {str(row["path"]) for row in rows} == {
        "src/prod_a.py",
        "src/prod_b.py",
    }
    assert dropped == {"tests": 4}
