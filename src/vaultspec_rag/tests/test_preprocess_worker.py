"""Worker-level integration of the preprocess hook (no GPU).

Exercises D6: a document-targeted rule runs through the document worker and
turns its output into ``DocumentChunk``s with anchor/locator payload, the code
worker refuses that same rule rather than storing the extraction as source, the
``PreprocessContext`` is picklable (so it can cross the process boundary), and
the worker import chain stays torch-free with the preprocess modules wired in
(``index-workers-stay-cpu-only``).
"""

import pickle
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ..indexer import _chunk_worker
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_cache import preprocess_cache_dir
from ..indexer._preprocess_config import (
    PreprocessConfig,
    PreprocessContext,
    PreprocessRule,
)

pytestmark = [pytest.mark.unit]

_EXTRACTOR = """
    import json, sys
    src = sys.argv[1]
    print(json.dumps({
        "schema_version": 1,
        "preprocessor_id": "pdf-fake",
        "preprocessor_version": "1.0",
        "source_path": src,
        "units": [
            {"text": "first page body",
             "anchor": src + "#page=1",
             "locator": {"kind": "page", "value": 1}},
            {"text": "second page body",
             "anchor": src + "#page=2",
             "locator": {"kind": "page", "value": 2}},
        ],
    }))
"""


def _context(tmp_path: Path, pattern: str = "*.pdf") -> PreprocessContext:
    script = tmp_path / "extractor.py"
    script.write_text(textwrap.dedent(_EXTRACTOR), encoding="utf-8")
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
    rule = PreprocessRule(
        pattern=pattern,
        command=command,
        entry_point=None,
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
    )
    return PreprocessContext(
        config=PreprocessConfig([rule]),
        cache_root=preprocess_cache_dir(tmp_path),
        max_emitted_bytes=1024 * 1024,
        project_root=tmp_path,
    )


def test_document_rule_produces_preproc_chunks(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"\x00\x01 not real pdf bytes")
    prep = _context(tmp_path)
    chunks = _chunk_worker.chunk_document_and_hash_file(source, tmp_path, prep).chunks
    assert len(chunks) == 2
    first, second = (chunk.payload for chunk in chunks)
    assert first.content == "first page body"
    # The hook reads the original source path, so the anchor it echoes ends with
    # the real file's name.
    assert first.anchor is not None
    assert first.anchor.endswith("report.pdf#page=1")
    assert first.locator is not None
    assert first.locator.kind == "page"
    assert first.locator.value == 1
    assert first.source_path == "report.pdf"
    assert first.extractor_id == "pdf-fake"
    assert second.content == "second page body"
    # Ids are unique per unit.
    assert chunks[0].id != chunks[1].id


def test_chunk_document_and_hash_file_marks_status_ok(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"\x00\x01binary")
    prep = _context(tmp_path)
    result = _chunk_worker.chunk_document_and_hash_file(source, tmp_path, prep)
    assert result is not None
    assert result.preprocess_status == "ok"
    assert len(result.chunks) == 2
    assert result.content_hash  # raw-bytes hash still computed


def test_code_worker_refuses_a_document_targeted_rule(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"\x00\x01binary")
    prep = _context(tmp_path)
    with pytest.raises(ValueError, match="non-code extraction rule"):
        _chunk_worker.chunk_file(source, tmp_path, prep)
    with pytest.raises(ValueError, match="non-code extraction rule"):
        _chunk_worker.chunk_and_hash_file(source, tmp_path, prep)


def test_cache_hit_skips_second_invocation(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"\x00\x01binary")
    prep = _context(tmp_path)
    first = _chunk_worker.chunk_document_and_hash_file(source, tmp_path, prep).chunks
    # Delete the extractor script: a cache hit must not need to re-run it.
    (tmp_path / "extractor.py").unlink()
    second = _chunk_worker.chunk_document_and_hash_file(source, tmp_path, prep).chunks
    assert [c.payload.content for c in first] == [c.payload.content for c in second]


def test_unmatched_file_chunks_normally(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def foo():\n    return 1\n", encoding="utf-8")
    prep = _context(tmp_path, pattern="*.pdf")
    chunks = _chunk_worker.chunk_file(source, tmp_path, prep)
    assert chunks
    assert all(c.preprocessor_id is None for c in chunks)


def test_context_is_picklable(tmp_path: Path) -> None:
    prep = _context(tmp_path)
    restored = pickle.loads(pickle.dumps(prep))
    assert restored.max_emitted_bytes == prep.max_emitted_bytes
    assert restored.config.match("a.pdf") is not None


def test_worker_import_chain_with_preprocess_is_torch_free() -> None:
    code = (
        "import sys\n"
        "import vaultspec_rag.indexer._chunk_worker\n"
        "import vaultspec_rag.indexer._preprocess_runner\n"
        "import vaultspec_rag.indexer._preprocess_cache\n"
        "import vaultspec_rag.indexer._preprocess_config\n"
        "torch_mods = sorted(m for m in sys.modules "
        "if m == 'torch' or m.startswith('torch.'))\n"
        "assert not torch_mods, torch_mods\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
