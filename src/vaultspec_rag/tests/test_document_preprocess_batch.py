"""Document runs spawn a batch hook once per group, not once per document.

Every case drives the real document indexer over a local store with a real
hook subprocess. The hook records each invocation as one marker file holding
the paths it was handed, so the assertions read spawn counts and manifests the
hook itself wrote. The hook emits empty text, so no document reaches the
encoder and the model needs no forward pass.
"""

from __future__ import annotations

import json
import math
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from ..indexer._chunk_producer import BATCH_SIZE
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._preprocess_runner import PreprocessAbortError
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._preprocess_approval import approve_preprocess_policy
from .test_document_index_symlinks import local_model, unloaded_model

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._vault_prep import IndexResult

__all__ = ["local_model", "unloaded_model"]

pytestmark = [pytest.mark.unit]

_NO_CONTENT = "document produced no decodable content"

# Records one marker per spawn listing the paths it received, then answers
# every path except those whose name contains "omit". Batch mode reads the
# manifest; single mode receives the one path as its argument.
_HOOK = """
    import json, os, sys
    log, mode, arg = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "batch":
        with open(arg, encoding="utf-8") as fh:
            paths = [line.rstrip("\\n") for line in fh if line.strip()]
    else:
        paths = [arg]
    os.makedirs(log, exist_ok=True)
    marker = os.path.join(log, "%d-%s" % (os.getpid(), os.urandom(8).hex()))
    with open(marker, "w", encoding="utf-8") as fh:
        json.dump(paths, fh)
    def output(p):
        return {"schema_version": 1, "preprocessor_id": "counting",
                "preprocessor_version": "1.0", "source_path": p, "text": ""}
    if mode == "batch":
        print(json.dumps([dict(output(p), path=p)
                          for p in paths if "omit" not in os.path.basename(p)]))
    else:
        print(json.dumps(output(paths[0])))
"""


def _write_rule(root: Path, *, batch: bool, on_error: str = "skip") -> Path:
    """Write and approve one ``*.blob`` document rule; return its spawn log."""
    script = root / "counting_hook.py"
    script.write_text(textwrap.dedent(_HOOK), encoding="utf-8")
    log = root / "spawns"
    mode, placeholder = ("batch", "{paths}") if batch else ("single", "{path}")
    command = " ".join(
        [
            shlex.quote(sys.executable),
            shlex.quote(str(script)),
            shlex.quote(str(log)),
            mode,
            placeholder,
        ]
    )
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\n'
        f'on_error = "{on_error}"\n'
        f"batch = {'true' if batch else 'false'}\n",
        encoding="utf-8",
    )
    approve_preprocess_policy(root)
    return log


def _manifests(log: Path) -> list[list[str]]:
    """Return the paths each spawn received, one list per spawn."""
    if not log.is_dir():
        return []
    return [json.loads(marker.read_text(encoding="utf-8")) for marker in log.iterdir()]


def _blobs(root: Path, names: list[str]) -> list[Path]:
    paths = [root / name for name in names]
    for path in paths:
        path.write_text(f"source bytes of {path.name}", encoding="utf-8")
    return paths


def _indexer(root: Path, model: EmbeddingModel, store: VaultStore) -> DocumentIndexer:
    return DocumentIndexer(
        root,
        model,
        store,
        content_policy=RootContentPolicy(
            SourceProfileVersion.CONVENTIONAL_V1,
            (ContentRoute("*.blob", ContentKind.DOCUMENT),),
        ),
    )


def _full(indexer: DocumentIndexer, *, clean: bool) -> IndexResult:
    return indexer.full_index(
        clean=clean,
        reporter=NullProgressReporter(),
        preflight=indexer.preflight_content(),
    )


def test_full_run_spawns_one_batch_hook_per_group(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    """N documents under a batch rule cost ceil(N / BATCH_SIZE) hook spawns.

    Catches a document run that hands each document to the hook alone: with
    the group spawn removed (the batch outcome lookup returning nothing before
    running the group), this run made 65 spawns and failed the count below.
    """
    log = _write_rule(tmp_path, batch=True)
    count = BATCH_SIZE + 1
    _blobs(tmp_path, [f"doc{i:03d}.blob" for i in range(count)])

    with VaultStore(tmp_path, embedding_dim=2) as store:
        outcome = _full(_indexer(tmp_path, local_model, store), clean=True)

    manifests = _manifests(log)
    assert len(manifests) == math.ceil(count / BATCH_SIZE)
    assert sorted(len(paths) for paths in manifests) == [1, BATCH_SIZE]
    # Every document still resolves on its own: the hook's empty text is one
    # recorded per-file outcome each, not a run failure.
    assert len(outcome.preprocess_failures) == count
    assert all(f.endswith(_NO_CONTENT) for f in outcome.preprocess_failures)


def test_cache_hits_are_not_sent_to_the_batch_hook(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    log = _write_rule(tmp_path, batch=True)
    _blobs(tmp_path, ["a.blob", "b.blob", "c.blob"])

    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = _indexer(tmp_path, local_model, store)
        _full(indexer, clean=True)
        assert len(_manifests(log)) == 1

        added = _blobs(tmp_path, ["d.blob", "e.blob"])
        _full(indexer, clean=False)

    later = [paths for paths in _manifests(log) if len(paths) != 3]
    assert len(later) == 1, "the second run is one spawn over its misses"
    assert sorted(later[0]) == sorted(str(path) for path in added)


def test_scoped_incremental_run_groups_changed_documents(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    log = _write_rule(tmp_path, batch=True)

    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = _indexer(tmp_path, local_model, store)
        # An empty corpus publishes cleanly, giving the scoped run the
        # publication it reconciles against.
        _full(indexer, clean=True)

        changed = _blobs(tmp_path, ["a.blob", "b.blob", "c.blob"])
        outcome = indexer.incremental_index(
            reporter=NullProgressReporter(),
            changed_paths=changed,
            preflight=indexer.preflight_changed_paths(changed),
        )

    manifests = _manifests(log)
    assert len(manifests) == 1, "the scoped run is one spawn over its changed paths"
    assert sorted(manifests[0]) == sorted(str(path) for path in changed)
    assert len(outcome.preprocess_failures) == len(changed)


def test_entry_missing_from_batch_output_resolves_through_skip(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    """The omitted document is a per-file skip, and is never re-run alone."""
    log = _write_rule(tmp_path, batch=True, on_error="skip")
    _blobs(tmp_path, ["a.blob", "omit.blob", "c.blob"])

    with VaultStore(tmp_path, embedding_dim=2) as store:
        outcome = _full(_indexer(tmp_path, local_model, store), clean=True)

    assert len(_manifests(log)) == 1
    assert sorted(outcome.preprocess_failures) == [
        f"a.blob: {_NO_CONTENT}",
        f"c.blob: {_NO_CONTENT}",
        "omit.blob: preprocessor returned no output for this file",
    ]


def test_entry_missing_from_batch_output_aborts_under_fail(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    log = _write_rule(tmp_path, batch=True, on_error="fail")
    _blobs(tmp_path, ["a.blob", "omit.blob"])

    with (
        VaultStore(tmp_path, embedding_dim=2) as store,
        pytest.raises(PreprocessAbortError, match="returned no output"),
    ):
        _full(_indexer(tmp_path, local_model, store), clean=True)

    assert len(_manifests(log)) == 1


def test_non_batch_rule_still_spawns_per_document(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    log = _write_rule(tmp_path, batch=False)
    names = ["a.blob", "b.blob", "c.blob"]
    _blobs(tmp_path, names)

    with VaultStore(tmp_path, embedding_dim=2) as store:
        _full(_indexer(tmp_path, local_model, store), clean=True)

    manifests = _manifests(log)
    assert len(manifests) == len(names)
    assert all(len(paths) == 1 for paths in manifests)
