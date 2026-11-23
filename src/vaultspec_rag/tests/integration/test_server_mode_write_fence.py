"""Server mode: a write that crosses another client's reset fails its run.

A real pinned Qdrant server holds the collection, and two real stores on the
same root talk to it as two processes would. Server mode takes no
point-operation locks, so nothing on the client side orders one store's write
against the other store's reset. The writer's run policy fences its writes to
the reset epoch it began under and checks that fence before every attempt and
again after every acknowledged attempt.

The case drives the production retry helper with that policy. Inside the one
admitted attempt the other store runs the production reset to completion,
and only then does the writer's upsert reach the server. The check before the
attempt has already passed, so the upsert lands in the replacement; the check
after the acknowledgement then raises ``SourceResetEpochError``, so the stale
run fails before it can record or finalize anything from the discarded epoch.
The stale points stay in the replacement until its next rebuild discards them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._source_types import PublicSourceType
from ..._store_writes import run_store_operation_with_retry
from ...config._settings import get_config
from ...config._types import EnvVar
from ...indexer._rebuild_lifecycle import capture_reset_epoch, reset_selected_sources
from ...indexer._run_ledger_models import SourceResetEpochError
from ...indexer._run_policy import RunPolicy
from ...store_runtime import VaultStore
from ..conftest import managed_env
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

    from ..._store_models import CodeChunk
    from ...qdrant_runtime._supervise import QdrantSupervisor

pytestmark = [pytest.mark.unit]


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(
        real_qdrant_binary, tmp_path_factory.mktemp("qdrant-write-fence")
    )


@pytest.fixture
def server_mode(qdrant_server: QdrantSupervisor, tmp_path: Path) -> Iterator[None]:
    """Point store construction at the running server, with storage state in tmp."""
    with managed_env(
        **{
            EnvVar.QDRANT_URL.value: qdrant_server.url,
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant-state"),
        }
    ):
        yield


def _code_chunks(count: int) -> list[CodeChunk]:
    from ..._store_models import CodeChunk

    dimension = int(get_config().embedding_dimension)
    chunks: list[CodeChunk] = []
    for index in range(count):
        vector = [0.0] * dimension
        vector[index % dimension] = 1.0
        chunks.append(
            CodeChunk(
                id=f"pkg/stale.py:{index}",
                path="pkg/stale.py",
                language="python",
                content=f"def stale_{index}():\n    return {index}\n",
                line_start=index * 3 + 1,
                line_end=index * 3 + 2,
                vector=vector,
            )
        )
    return chunks


@pytest.mark.usefixtures("server_mode")
def test_a_write_crossing_another_clients_reset_fails_its_run(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "project").resolve()
    (root / ".vault").mkdir(parents=True)
    writer = VaultStore(root)
    resetter = VaultStore(root)
    try:
        assert writer._server_mode is True
        writer.ensure_code_table()
        began = capture_reset_epoch(
            root, PublicSourceType.CODE, writer.backend_identity
        )
        policy = RunPolicy(no_progress_timeout_seconds=60.0)
        policy.fence_writes(began.validate)
        chunks = _code_chunks(4)

        def write_after_a_foreign_reset(_attempt_timeout: int) -> None:
            reset_selected_sources(
                resetter, PublicSourceType.CODE, generation_id="foreign-rebuild"
            )
            writer.upsert_code_chunks(chunks, write_policy=None)

        # The acknowledged write is re-checked: the reset inside the attempt
        # moved the epoch, so the helper refuses rather than reporting success.
        with pytest.raises(SourceResetEpochError):
            run_store_operation_with_retry(
                write_after_a_foreign_reset,
                description="code upsert crossing a foreign reset",
                policy=policy.store_write_policy,
            )

        after = capture_reset_epoch(
            root, PublicSourceType.CODE, writer.backend_identity
        )
        assert after.epoch == began.epoch + 1
        assert after.serving
        assert after.generation_id == "foreign-rebuild"
        # Server mode has no cross-process writer exclusion, so the refusal
        # comes after the stale points reached the replacement.
        assert resetter.count_code() == len(chunks)
    finally:
        resetter.close()
        writer.close()
