"""A rebuild that crashes after writing or after its proof recovers its own work.

Every case opens a real embedded Qdrant store and a real run ledger under the
test's temporary root. A crash is the exact durable state a process dying at
that point leaves: the generation is still ``RUNNING`` with nothing recorded
after the crash point. Recovery is the next attempt of the same request,
which claims the generation its job recorded and reopens it the way a
restarted service does. Nothing here loads a model.

MUTATION PROOF, each run in one uninterrupted sequence:

- Ignoring the claim in the shared generation start (opening every rebuild
  as a new one) failed
  ``test_a_crash_after_applied_writes_resumes_without_a_second_reset`` on its
  ``same generation`` assertion and
  ``test_a_crash_after_the_proof_commit_finishes_that_publication`` on its
  ``same generation`` assertion; restoring it passed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..indexer._run_ledger_models import RunTerminalState
from ._ledger_fixtures import continue_rebuild
from ._run_ledger_test_support import ledger_test_unit
from .test_rebuild_lifecycle import (
    _fence,
    _open_vault_rebuild,
    _points,
    _seed,
    _state,
    local_config,
    store,
)

if TYPE_CHECKING:
    from ..store_runtime import VaultStore

__all__ = ["local_config", "store"]

pytestmark = [pytest.mark.unit]


def test_a_crash_after_applied_writes_resumes_without_a_second_reset(
    store: VaultStore,
) -> None:
    """Applied but unrecorded work is the rebuild's own; the reset is not repeated.

    The process died after the replacement point was applied and before its
    unit was recorded. The next attempt continues the same generation over
    the same epoch, finds nothing confirmed, and rewrites the unit onto the
    point already there rather than discarding the replacement.
    """
    _seed(store, store.TABLE_NAME, point_id=1)
    crashed = _open_vault_rebuild(store)
    crashed.reset_for_rebuild(store, began_under=_fence(store, PublicSourceType.VAULT))
    assert _points(store, store.TABLE_NAME) == 0, "old content survived the reset"
    _seed(store, store.TABLE_NAME, point_id=3)
    unit = ledger_test_unit("doc", 0, 1)

    with continue_rebuild(crashed.generation_id):
        resumed = _open_vault_rebuild(store)
        resumed.reset_for_rebuild(
            store, began_under=_fence(store, PublicSourceType.VAULT)
        )

    assert resumed.generation_id == crashed.generation_id, "same generation"
    assert not resumed.ledger.unit_committed(resumed.generation_id, unit)
    state = _state(store, PublicSourceType.VAULT)
    assert state is not None
    assert (state.epoch, state.generation_id) == (1, crashed.generation_id)
    assert _points(store, store.TABLE_NAME) == 1
    _seed(store, store.TABLE_NAME, point_id=3)
    resumed.ledger.record_storage_confirmed_units(resumed.generation_id, (unit,))
    assert resumed.ledger.unit_committed(resumed.generation_id, unit)
    assert _points(store, store.TABLE_NAME) == 1


def test_a_crash_after_the_proof_commit_finishes_that_publication(
    store: VaultStore,
) -> None:
    """A committed proof is finished by the next attempt, never discarded.

    The process died after the canonical proof committed and before the
    generation was certified. The next attempt of the same request continues
    that generation without a reset, and certifying it publishes exactly the
    proof the crashed attempt committed.
    """
    crashed = _open_vault_rebuild(store)
    crashed.reset_for_rebuild(store, began_under=_fence(store, PublicSourceType.VAULT))
    crashed.publish_proof_transition()
    committed = acquire_publication_snapshot(store.root_dir, PublicSourceType.VAULT)
    assert committed.proof.generation_id == crashed.generation_id

    with continue_rebuild(crashed.generation_id):
        resumed = _open_vault_rebuild(store)
        resumed.reset_for_rebuild(
            store, began_under=_fence(store, PublicSourceType.VAULT)
        )
        assert resumed.publish_proof_transition() == 0
        certified = resumed.publish_generation()

    assert resumed.generation_id == crashed.generation_id, "same generation"
    assert certified.terminal_state is RunTerminalState.SUCCEEDED
    state = _state(store, PublicSourceType.VAULT)
    assert state is not None
    assert (state.epoch, state.generation_id) == (1, crashed.generation_id)
    published = acquire_publication_snapshot(store.root_dir, PublicSourceType.VAULT)
    assert published.proof.generation_id == crashed.generation_id
    assert published.proof.revision == committed.proof.revision
    published.validate()
