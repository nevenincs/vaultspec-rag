"""A real document rebuild publishes every batch-extracted document.

The unit tier proves the spawn count with documents that carry no text, so
nothing reaches the encoder. This case runs the same grouping through the real
model and store: every document carries text, every document is embedded and
published, and the hook still runs once per group.
"""

from __future__ import annotations

import math
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from ...indexer._chunk_producer import BATCH_SIZE
from .._preprocess_approval import approve_preprocess_policy
from ._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]

_HOOK = """
    import json, os, sys
    log, manifest = sys.argv[1], sys.argv[2]
    with open(manifest, encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    os.makedirs(log, exist_ok=True)
    marker = os.path.join(log, "%d-%s" % (os.getpid(), os.urandom(8).hex()))
    with open(marker, "w", encoding="utf-8") as fh:
        json.dump(paths, fh)
    print(json.dumps([
        {"path": p, "schema_version": 1, "preprocessor_id": "batch-text",
         "preprocessor_version": "1.0", "source_path": p,
         "text": "Extracted guidance for " + os.path.basename(p)}
        for p in paths
    ]))
"""


@pytest.mark.timeout(600)
def test_full_rebuild_publishes_batch_extracted_documents_with_grouped_spawns(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ...indexer import DocumentIndexer
    from ...progress import NullProgressReporter
    from ...store_runtime import VaultStore

    script = tmp_path / "batch_text.py"
    script.write_text(textwrap.dedent(_HOOK), encoding="utf-8")
    log = tmp_path / "spawns"
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
        f"{shlex.quote(str(log))} {{paths}}"
    )
    (tmp_path / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\n'
        'on_error = "skip"\nbatch = true\n',
        encoding="utf-8",
    )
    approve_preprocess_policy(tmp_path)
    count = BATCH_SIZE + 1
    for i in range(count):
        (tmp_path / f"doc{i:03d}.blob").write_bytes(b"\xff\xfe extractor-owned %d" % i)

    store = VaultStore(tmp_path)
    try:
        indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=_document_policy("*.blob"),
        )
        outcome = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        assert outcome.preprocess_failures == []
        assert len(list(log.iterdir())) == math.ceil(count / BATCH_SIZE)
        rows, _ = store.scroll_document_content(limit=count * 2)
        published = {row["payload"]["source_path"] for row in rows}
        assert published == {f"doc{i:03d}.blob" for i in range(count)}
    finally:
        store.close()
