"""A hook root whose document index is published, for admission tests.

The root declares one document hook with a declared input file, and its
document source carries a real committed publication proof opened through
production checkpoint code under the policy admission resolves. Editing the
declared input afterwards is the cheapest way to make the published content
identity stale without touching the rule table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

if TYPE_CHECKING:
    from pathlib import Path

    from ..indexer._document_checkpoint import DocumentRunCheckpoint
    from ..indexer._run_ledger_models import RunAuthority, RunOperation
    from ..store_runtime import VaultStore

#: The declared input whose content joins the document content identity.
HOOK_SCRIPT = "tools/extract.py"


def write_hook_root(root: Path, *, declare_inputs: bool = True) -> Path:
    """Write a project with one document hook rule and its script."""
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (root / HOOK_SCRIPT).write_text("print('v1')\n", encoding="utf-8")
    lines = [
        "version = 2",
        "",
        "[[rule]]",
        'pattern = "*.pdf"',
        'target = "document"',
        'extractor_version = "1"',
        f"command = 'python {HOOK_SCRIPT} {{path}}'",
    ]
    if declare_inputs:
        lines.append(f'inputs = ["{HOOK_SCRIPT}"]')
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return root


def edit_hook_script(root: Path) -> None:
    """Change the declared input while leaving the rule table untouched."""
    (root / HOOK_SCRIPT).write_text("print('v2')\n", encoding="utf-8")


def open_document_generation(
    root: Path,
    *,
    operation: RunOperation,
    authority: RunAuthority,
) -> DocumentRunCheckpoint:
    """Open a document generation the way a document index run opens one.

    The policy is resolved exactly as admission resolves it, and the ledger
    and backend identity are the ones admission reads the proof from.
    """
    from .._store_writes import workspace_volume_path
    from ..indexer._content_discovery import CodeContentDiscovery
    from ..indexer._document_checkpoint import (
        DocumentRunCheckpoint,
        DocumentRunConfiguration,
        DocumentRunOpenRequest,
    )
    from ..indexer._run_ledger_models import RunOperation
    from ..indexer._run_policy import RunPolicy
    from ..store_runtime import configured_backend_identity

    resolved = root.resolve()
    return DocumentRunCheckpoint.open_generation(
        DocumentRunOpenRequest(
            data_root=workspace_volume_path(resolved),
            root_dir=resolved,
            policy=CodeContentDiscovery(resolved).resolve_policy(),
            run_policy=RunPolicy(no_progress_timeout_seconds=30.0),
            operation=operation,
            clean=operation is RunOperation.FULL,
            model_identity="hook-admission-model",
            dense_dimensions=4,
            configuration=DocumentRunConfiguration(
                slice_max_chunks=1,
                source_bytes=4096,
                generated_chunks=3,
                weighted_bytes=8192,
                sparse_enabled=False,
                sparse_dimension=1,
                encode_batch_size=2,
            ),
            backend_identity=configured_backend_identity(resolved),
            authority=authority,
        )
    )


def publish_empty_document_proof(root: Path) -> None:
    """Complete one real, empty document publication for *root*."""
    from ..indexer._run_ledger_models import RunAuthority, RunOperation

    checkpoint = open_document_generation(
        root, operation=RunOperation.FULL, authority=RunAuthority.REBUILD
    )
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()


def publish_one_document(root: Path, rel_path: str, store: VaultStore) -> None:
    """Publish one stored document point for *rel_path* under a real proof.

    The proof records a digest of content the file no longer has, so a
    delivered hit on it verifies as stale while storage and proof agree.
    """
    import hashlib

    from .._store_models import DocumentChunk, DocumentLocator, DocumentPayload
    from ..indexer._document_identity import document_point_id
    from ..indexer._run_ledger_models import RunAuthority, RunOperation

    text = "published extraction"
    # The point and the proof both name the digest of the published source.
    fingerprint = hashlib.blake2b(b"content the file no longer has").hexdigest()
    locator = DocumentLocator("line", 1)
    point_id = document_point_id(
        source_path=rel_path,
        unit_ordinal=0,
        content_fingerprint=fingerprint,
        locator=locator,
    )
    store.upsert_document_content_chunks(
        [
            DocumentChunk(
                point_id,
                DocumentPayload(
                    rel_path,
                    0,
                    fingerprint,
                    text,
                    locator=locator,
                    extractor_id="hook-admission-test",
                    extractor_version="1",
                ),
                vector=[0.1, 0.2, 0.3, 0.4],
            )
        ],
        write_policy=None,
    )
    checkpoint = open_document_generation(
        root, operation=RunOperation.FULL, authority=RunAuthority.REBUILD
    )
    unit = checkpoint.unit_for(
        rel_path,
        fingerprint,
        0,
        is_file_end=True,
        point_ids=(point_id,),
    )
    checkpoint.record_confirmed_slice(unit)
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()
