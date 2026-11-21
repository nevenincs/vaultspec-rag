"""A search never returns content read across a reset of its source.

Every case runs against a real local store and a real run ledger under the
test's temporary root. A reset in progress is the exact durable state a
rebuild leaves between recording its intent and recording completion; a reset
that crosses a read is the production reset itself, run from inside the read.
Nothing here loads a model: the empty-collection path answers without one, so
a search that should have been refused and was not comes back as an empty
success the assertions reject.

MUTATION PROOF, each run in one uninterrupted sequence:

- Deleting the validation after the read in ``read_current_epoch`` failed
  ``test_a_read_that_spans_a_reset_returns_nothing`` on its ``pytest.raises``
  for every source; restoring it passed.
- Deleting the ``serving`` refusal in ``capture_source_read_fence`` failed
  ``test_a_source_mid_reset_refuses_before_reading`` on its ``pytest.raises``
  and ``test_each_public_search_refuses_a_source_mid_reset`` on its
  ``pytest.raises``; restoring it passed.
- Returning the outcome unchanged from ``_fenced_combined_outcome`` failed
  ``test_a_reset_crossing_a_combined_search_fences_that_domain`` on its
  ``error_kind`` assertion; restoring it passed.
- Dropping the reset-in-progress branch of ``typed_search_refusal_fact``
  failed ``test_combined_search_refuses_only_the_domain_a_reset_crossed`` on
  its ``error_kind`` assertion; restoring it passed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._public_search import (
    CombinedSearchRequest,
    DocumentSearchRequest,
    search_combined_timed,
    search_documents_timed,
)
from .._publication_state import IndexTransitionError, read_current_epoch
from .._search_state import (
    AbsenceAuthority,
    SearchAvailability,
    SearchReasonCode,
    SearchSourceFact,
)
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..api import (
    CodebaseSearchRequest,
    VaultSearchRequest,
    search_codebase_timed,
    search_vault_timed,
)
from ..indexer._rebuild_lifecycle import CONCRETE_SOURCES, reset_selected_sources
from ..indexer._run_ledger_models import SourceResetPhase, index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ..service import ServiceRegistry
from ..store_runtime import configured_backend_identity
from ._config_fixtures import reset_config
from .test_rebuild_lifecycle import _collection, _open, _points, _seed

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(name="local_root")
def _local_root(tmp_path: Path) -> Generator[Path]:
    """A root on local storage with two-wide dense vectors and no sparse ones."""
    from ..config._settings import get_config

    get_config(
        {
            "local_only": True,
            "qdrant_url": None,
            "embedding_dimension": 2,
            "sparse_enabled": False,
        }
    )
    (tmp_path / ".vault").mkdir()
    try:
        yield tmp_path.resolve()
    finally:
        reset_config()


def record_reset_intent(root: Path, source: PublicSourceType) -> None:
    """Leave the durable state of a reset that recorded intent and no more."""
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root)))
    state = ledger.begin_source_reset(
        source, str(root), configured_backend_identity(root), "rebuild-in-flight"
    )
    assert state.phase is SourceResetPhase.INTENT


def search_source(
    root: Path, source: PublicSourceType, registry: ServiceRegistry
) -> list[object]:
    """Run the production search facade of one concrete source."""
    if source is PublicSourceType.VAULT:
        vault, _ = search_vault_timed(
            VaultSearchRequest(root_dir=root, query="needle"), registry=registry
        )
        return list(vault)
    if source is PublicSourceType.CODE:
        code, _ = search_codebase_timed(
            CodebaseSearchRequest(root_dir=root, query="needle"), registry=registry
        )
        return list(code)
    document, _ = search_documents_timed(
        DocumentSearchRequest(root_dir=root, query="needle"), registry=registry
    )
    return list(document)


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_read_that_spans_a_reset_returns_nothing(
    local_root: Path, source: PublicSourceType
) -> None:
    """A read whose storage a reset discards mid-read is refused, not returned."""
    with _open(local_root) as store:
        store.ensure_table()
        store.ensure_code_table()
        store.ensure_document_table()
        collection = _collection(store, source)
        _seed(store, collection)

        def read_then_reset() -> int:
            observed = _points(store, collection)
            reset_selected_sources(store, source, generation_id="rebuild-1")
            return observed

        with pytest.raises(IndexTransitionError) as refused:
            read_current_epoch(local_root, source, read_then_reset)

        assert refused.value.source is source
        assert _points(store, collection) == 0


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_source_mid_reset_refuses_before_reading(
    local_root: Path, source: PublicSourceType
) -> None:
    """Storage being discarded is never read at all."""
    record_reset_intent(local_root, source)
    reads: list[PublicSourceType] = []

    with pytest.raises(IndexTransitionError):
        read_current_epoch(local_root, source, lambda: reads.append(source))

    assert reads == []


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_a_completed_reset_serves_what_its_rebuild_wrote_so_far(
    local_root: Path, source: PublicSourceType
) -> None:
    """Partial replacement content of the current epoch is answered.

    A rebuild that has written one batch has not published, and its content
    is still the only content of the epoch it writes under.
    """
    with _open(local_root) as store:
        store.ensure_table()
        store.ensure_code_table()
        store.ensure_document_table()
        collection = _collection(store, source)
        _seed(store, collection, point_id=1)
        reset_selected_sources(store, source, generation_id="rebuild-1")
        _seed(store, collection, point_id=2)

        served = read_current_epoch(
            local_root, source, lambda: _points(store, collection)
        )

    assert served == 1


@pytest.mark.parametrize("source", CONCRETE_SOURCES)
def test_each_public_search_refuses_a_source_mid_reset(
    local_root: Path, source: PublicSourceType
) -> None:
    """Every single-source facade refuses; its siblings keep answering."""
    record_reset_intent(local_root, source)
    registry = ServiceRegistry()

    with pytest.raises(IndexTransitionError) as refused:
        search_source(local_root, source, registry)

    assert refused.value.source is source
    for sibling in CONCRETE_SOURCES:
        if sibling is not source:
            assert search_source(local_root, sibling, registry) == []


def test_combined_search_refuses_only_the_domain_a_reset_crossed(
    local_root: Path,
) -> None:
    """A combined search keeps every other domain and types the fenced one."""
    record_reset_intent(local_root, PublicSourceType.CODE)

    outcome, _timings = search_combined_timed(
        CombinedSearchRequest(root_dir=local_root, query="needle"),
        registry=ServiceRegistry(),
    )

    assert outcome.code.error_kind == SearchReasonCode.INDEX_TRANSITION.value
    assert outcome.code.results == ()
    fact = outcome.code.source_fact
    assert fact.reason_code is SearchReasonCode.INDEX_TRANSITION
    assert fact.availability is SearchAvailability.UNAVAILABLE
    assert fact.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert fact.retryable is True
    assert outcome.vault.ok
    assert outcome.document is not None
    assert outcome.document.ok


def test_a_reset_crossing_a_combined_search_fences_that_domain(
    local_root: Path,
) -> None:
    """A reset recorded after a combined count is caught before the answer.

    The count of every domain is taken under the epoch captured before it;
    a reset recorded afterwards leaves the count and any search behind it
    unreturnable for that domain.
    """
    from .. import _public_search

    registry = ServiceRegistry()
    counts, failures, facts, _timings, fences = _public_search._count_combined_domains(
        local_root, registry, include_documents=True
    )
    assert not failures
    record_reset_intent(local_root, PublicSourceType.VAULT)

    empty = _public_search._empty_or_failed_combined_outcome(failures, facts, 5)
    fenced = _public_search._fenced_combined_outcome(empty, fences, local_root)

    assert counts[PublicSourceType.VAULT] == 0
    assert fenced.vault.error_kind == SearchReasonCode.INDEX_TRANSITION.value
    assert fenced.code.ok


def _document_fact(root: Path, registry: ServiceRegistry) -> SearchSourceFact:
    outcome, _timings = search_combined_timed(
        CombinedSearchRequest(root_dir=root, query="needle"), registry=registry
    )
    assert outcome.document is not None
    assert outcome.document.ok
    assert outcome.document.results == ()
    return outcome.document.source_fact


def _published_document_generation(root: Path) -> str:
    from .._publication_state import acquire_publication_snapshot

    return acquire_publication_snapshot(
        root, PublicSourceType.DOCUMENT
    ).proof.generation_id


async def test_an_empty_corpus_is_authoritative_only_once_its_rebuild_finalizes(
    local_root: Path,
) -> None:
    """Absence is proven by a finished build, never by one still running.

    The corpus is genuinely empty throughout, so the reset leaves exactly what
    the completed rebuild will certify. Only the certification differs.

    Mutation: dropping the ``integrity_verified`` requirement from
    ``_target_is_current`` let the readiness registry's cached claim on the
    discarded publication certify the rebuilding source, and failed the
    middle assertion with ``authoritative``; restoring it passed.
    """
    import asyncio

    from ._hook_publication import publish_empty_document_proof

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    publish_empty_document_proof(local_root)
    readiness.publish_next(
        local_root,
        "document",
        generation=_published_document_generation(local_root),
    )

    assert (
        _document_fact(local_root, registry).absence_authority
        is AbsenceAuthority.AUTHORITATIVE
    )

    with _open(local_root) as store:
        reset_selected_sources(
            store, PublicSourceType.DOCUMENT, generation_id="rebuild-2"
        )

    rebuilding = _document_fact(local_root, registry)
    assert rebuilding.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert rebuilding.availability is SearchAvailability.USABLE

    publish_empty_document_proof(local_root)
    readiness.publish_next(
        local_root,
        "document",
        generation=_published_document_generation(local_root),
    )

    assert (
        _document_fact(local_root, registry).absence_authority
        is AbsenceAuthority.AUTHORITATIVE
    )
