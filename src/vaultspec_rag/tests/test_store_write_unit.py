"""Unit tests for the classified, bounded-retry store write path (#242).

The incident behind issue #242 was a silent index wedge: qdrant refused
every write on a full disk while the indexer kept embedding and
discarding batches. These tests pin the fail-loud contract: every
persistent write failure raises ``StorageWriteError`` with a stable
``error_kind`` within the bounded retry budget, and ``disk_full`` never
retries at all.
"""

from collections.abc import Generator
from typing import Any, ClassVar

import pytest

from ..config import reset_config
from ..store import StorageWriteError, VaultStore, _classify_write_error


class _ScriptedClient:
    """Client double whose ``upsert`` raises a scripted exception series."""

    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def upsert(self, *, collection_name: str, points: list[Any]) -> None:
        del collection_name, points
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)


def _server_store(client: _ScriptedClient) -> VaultStore:
    """Build a server-mode store shell around *client*.

    ``VaultStore.__init__`` opens a real backend, which a unit test of the
    retry policy must not; the write path only touches ``_server_mode``,
    ``_client``, and the point-lock plumbing.
    """
    store = object.__new__(VaultStore)
    store._server_mode = True
    store._client = client  # type: ignore[assignment]
    store._collection_locks = {}
    return store


@pytest.fixture
def write_knobs(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Zero backoff and a 2-retry budget, restored after the test."""
    monkeypatch.setenv("VAULTSPEC_RAG_STORE_WRITE_BACKOFF_S", "0")
    monkeypatch.setenv("VAULTSPEC_RAG_STORE_WRITE_RETRIES", "2")
    reset_config()
    yield
    reset_config()


class TestClassifyWriteError:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_errno_28_is_disk_full(self):
        assert _classify_write_error(OSError(28, "No space left on device")) == (
            "disk_full"
        )

    def test_qdrant_wal_message_is_disk_full(self):
        exc = RuntimeError(
            "Service internal error: No space left on device: "
            "WAL buffer size exceeds available disk space"
        )
        assert _classify_write_error(exc) == "disk_full"

    def test_optimizer_space_message_is_disk_full(self):
        exc = RuntimeError(
            "Optimization error: Not enough space available for optimization"
        )
        assert _classify_write_error(exc) == "disk_full"

    def test_timeout_text_is_timeout(self):
        assert _classify_write_error(OSError("request timed out")) == "timeout"

    def test_connection_refused_is_unavailable(self):
        assert _classify_write_error(OSError("connection refused")) == "unavailable"

    def test_anything_else_is_rejected(self):
        assert _classify_write_error(RuntimeError("bad vector shape")) == "rejected"


@pytest.mark.usefixtures("write_knobs")
class TestUpsertBackpressure:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_disk_full_fails_without_retry(self):
        client = _ScriptedClient([OSError(28, "No space left on device")] * 5)
        store = _server_store(client)
        with pytest.raises(StorageWriteError) as excinfo:
            store._upsert_points("codebase_docs", [])
        assert excinfo.value.error_kind == "disk_full"
        assert client.calls == 1

    def test_transient_timeout_retries_then_succeeds(self):
        client = _ScriptedClient([OSError("timed out"), OSError("timed out")])
        store = _server_store(client)
        store._upsert_points("codebase_docs", [])
        assert client.calls == 3

    def test_exhausted_retry_budget_raises_with_kind(self):
        client = _ScriptedClient([OSError("timed out")] * 10)
        store = _server_store(client)
        with pytest.raises(StorageWriteError) as excinfo:
            store._upsert_points("codebase_docs", [])
        assert excinfo.value.error_kind == "timeout"
        # 1 initial attempt + 2 configured retries.
        assert client.calls == 3

    def test_rejected_fails_without_retry(self):
        client = _ScriptedClient([OSError("malformed request")] * 5)
        store = _server_store(client)
        with pytest.raises(StorageWriteError) as excinfo:
            store._upsert_points("vault_docs", [])
        assert excinfo.value.error_kind == "rejected"
        assert client.calls == 1

    def test_cause_chain_preserves_original_error(self):
        original = OSError(28, "No space left on device")
        client = _ScriptedClient([original])
        store = _server_store(client)
        with pytest.raises(StorageWriteError) as excinfo:
            store._upsert_points("codebase_docs", [])
        assert excinfo.value.__cause__ is original
