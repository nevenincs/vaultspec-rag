"""In-process indexing is admitted by the same preflight the service runs.

A hook root's document source carries a real committed proof, opened through
production checkpoint code under the policy admission resolves. Editing the
hook's declared input makes that proof unable to parent an incremental run.
The public API must refuse such a run with the service's typed refusal before
it leases a model, opens a checkpoint, or records a generation.

MUTATION PROOF, run in one uninterrupted sequence: replacing the admission
call in ``index_documents`` with an admitted run that skips the preflight let
the request reach the compute lease, which failed loading the configured
never-cached model; the test failed on its ``isinstance`` assertion naming
that error. Restoring the admission call passed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._job_admission import IncompatibleIncrementalError
from .._job_errors import JobErrorKind
from .._store_writes import workspace_volume_path
from ..api import DocumentIndexOptions, index_documents
from ..indexer._content_policy import ContentKind
from ..indexer._run_ledger_models import index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ._config_fixtures import reset_config
from ._hook_publication import (
    edit_hook_script,
    publish_empty_document_proof,
    write_hook_root,
)
from ._ledger_fixtures import latest_generation
from ._scaffold import make_workspace

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: A model no cache can hold, so a request that wrongly reaches the compute
#: lease fails fast at its model check instead of loading real weights.
_UNCACHED_MODEL = "vaultspec-test/never-cached-model"


@pytest.fixture(name="stale_hook_root")
def _stale_hook_root(tmp_path: Path) -> Generator[Path]:
    from ..config._settings import get_config

    get_config({"local_only": True, "qdrant_url": None})
    root = (tmp_path / "project").resolve()
    root.mkdir()
    write_hook_root(make_workspace(root))
    publish_empty_document_proof(root)
    edit_hook_script(root)
    try:
        yield root
    finally:
        reset_config()


def test_an_incremental_the_proof_cannot_parent_is_refused_before_any_run(
    stale_hook_root: Path,
) -> None:
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(stale_hook_root)))
    published = latest_generation(ledger, ContentKind.DOCUMENT)
    assert published is not None

    refused: Exception | None = None
    try:
        index_documents(
            stale_hook_root, DocumentIndexOptions(model_name=_UNCACHED_MODEL)
        )
    except Exception as exc:  # the refusal's exact type is the assertion
        refused = exc

    assert isinstance(refused, IncompatibleIncrementalError), refused
    assert refused.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert refused.changed_identities == ("content_identity",)
    assert "--rebuild" in refused.rebuild_command
    latest = latest_generation(ledger, ContentKind.DOCUMENT)
    assert latest is not None
    assert latest.generation_id == published.generation_id


def test_a_scoped_document_run_the_proof_cannot_parent_is_refused(
    stale_hook_root: Path,
) -> None:
    """Scoped runs never escalate, and are refused like any other increment."""
    with pytest.raises(IncompatibleIncrementalError):
        index_documents(
            stale_hook_root,
            DocumentIndexOptions(
                changed_paths=[stale_hook_root / "a.pdf"],
                model_name=_UNCACHED_MODEL,
            ),
        )
