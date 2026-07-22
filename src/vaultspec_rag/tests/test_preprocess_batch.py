"""Tests for opt-in batch preprocess hooks (no GPU, no mocks, #241).

Three layers over real subprocesses and real temp dirs:

- Config validation of the ``batch`` knob (accept/reject matrix), over real
  ``.vaultragpreprocess.toml`` fixtures.
- The batch runner (:func:`run_preprocessor_batch`): a real hook reads the paths
  manifest and emits a JSON array; per-file mapping, per-file ``on_error``, and
  the scaled wall-clock timeout are exercised end to end.
- The batch worker (:func:`_chunk_worker.chunk_batch_files`): one spawn produces
  per-file chunks and populates the D7 cache, so a second pass hits the cache
  with no further spawn - verified by a spawn-counting side effect the hook
  itself writes.
"""

import os
import shlex
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from .. import CodebaseIndexer
from ..config import EnvVar, reset_config
from ..indexer import _chunk_worker
from ..indexer._preprocess_cache import preprocess_cache_dir
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    OnError,
    PreprocessConfig,
    PreprocessConfigError,
    PreprocessContext,
    PreprocessRule,
    load_preprocess_rules,
)
from ..indexer._preprocess_runner import (
    PreprocessAbortError,
    run_preprocessor_batch,
)
from ..progress import NullProgressReporter
from ..store import CodeChunk

pytestmark = [pytest.mark.unit]

_CAP = 1024 * 1024


# --------------------------------------------------------------------------
# Config validation: the batch knob accept/reject matrix.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_status_dir_and_default_mode(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the status dir and resolve the ``default`` preprocess mode.

    Mirrors the managed-singleton isolation the sibling config tests use, so a
    rule's ``batch`` knob resolves under ``default`` without touching real
    managed state.
    """
    status = tmp_path_factory.mktemp("status")
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status))
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    reset_config()
    try:
        yield
    finally:
        reset_config()


def _write_config(root: Path, body: str) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(body, encoding="utf-8")


def test_batch_rule_with_paths_placeholder_loads(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {paths}"
        batch = true
        """,
    )
    rule = load_preprocess_rules(tmp_path).match("a.pdf")
    assert rule is not None
    assert rule.batch is True
    assert rule.command == "extract {paths}"


def test_non_batch_rule_defaults_batch_false(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        """,
    )
    rule = load_preprocess_rules(tmp_path).match("a.pdf")
    assert rule is not None
    assert rule.batch is False


def test_batch_command_lacking_paths_placeholder_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        batch = true
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_batch_command_with_single_placeholder_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {paths} {path}"
        batch = true
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_batch_with_entry_point_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        entry_point = "mod:call"
        batch = true
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_non_batch_command_with_paths_placeholder_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {paths}"
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_non_boolean_batch_is_dropped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {paths}"
        batch = "yes"
        """,
    )
    assert load_preprocess_rules(tmp_path).rules == []


def test_batch_defect_raises_in_strict_mode(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        batch = true
        """,
    )
    with pytest.raises(PreprocessConfigError):
        load_preprocess_rules(tmp_path, strict=True)


def test_batch_rule_is_picklable(tmp_path: Path) -> None:
    import pickle

    _write_config(
        tmp_path,
        """
        [[rule]]
        pattern = "*.pdf"
        command = "extract {paths}"
        batch = true
        """,
    )
    rule = load_preprocess_rules(tmp_path).match("a.pdf")
    assert rule is not None
    restored = pickle.loads(pickle.dumps(rule))
    assert restored == rule
    assert restored.batch is True


# --------------------------------------------------------------------------
# The batch runner: real hook reading the paths manifest.
# --------------------------------------------------------------------------

# A batch hook: read the manifest (argv[1]), emit one v1 output object per path
# in a JSON array, each carrying its "path" key for the runner to map back.
_BATCH_BODY = """
    import json, sys
    with open(sys.argv[1], encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    print(json.dumps([
        {"path": p, "schema_version": 1, "preprocessor_id": "batch-echo",
         "preprocessor_version": "1.0", "source_path": p,
         "units": [{"text": "body of " + p}]}
        for p in paths
    ]))
"""

# Same, but omits the first manifest path from the response (a missing element).
_OMIT_FIRST_BODY = """
    import json, sys
    with open(sys.argv[1], encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    print(json.dumps([
        {"path": p, "schema_version": 1, "preprocessor_id": "batch-echo",
         "preprocessor_version": "1.0", "source_path": p,
         "units": [{"text": "body of " + p}]}
        for p in paths[1:]
    ]))
"""

# Deletes the omitted member after the worker's initial read. Passthrough must
# surface the failed second read instead of publishing a successful omission.
_DELETE_AND_OMIT_FIRST_BODY = """
    import json, pathlib, sys
    with open(sys.argv[1], encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    pathlib.Path(paths[0]).unlink()
    print(json.dumps([
        {"path": p, "schema_version": 1, "preprocessor_id": "batch-echo",
         "preprocessor_version": "1.0", "source_path": p,
         "units": [{"text": "body of " + p}]}
        for p in paths[1:]
    ]))
"""

# A malformed envelope: a JSON object, not the required array.
_NON_ARRAY_BODY = """
    import json
    print(json.dumps({"not": "an array"}))
"""

_SLEEP_BODY = "import time\ntime.sleep(5)\n"


def _script(tmp_path: Path, body: str, name: str = "batch.py") -> Path:
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def _batch_rule(
    script: Path,
    *,
    prefix_args: str = "",
    on_error: OnError = "skip",
    timeout_s: float | None = 30.0,
) -> PreprocessRule:
    parts = [shlex.quote(sys.executable), shlex.quote(str(script))]
    if prefix_args:
        parts.append(prefix_args)
    parts.append("{paths}")
    return PreprocessRule(
        pattern="*.bin",
        command=" ".join(parts),
        entry_point=None,
        priority=100,
        on_error=on_error,
        timeout_s=timeout_s,
        options={},
        order=0,
        batch=True,
    )


def _make_files(tmp_path: Path, count: int) -> list[Path]:
    paths: list[Path] = []
    for i in range(count):
        p = tmp_path / f"doc{i}.bin"
        p.write_bytes(f"binary-{i}".encode())
        paths.append(p)
    return paths


def test_batch_maps_output_per_file(tmp_path: Path) -> None:
    script = _script(tmp_path, _BATCH_BODY)
    files = _make_files(tmp_path, 3)
    results = run_preprocessor_batch(
        files, _batch_rule(script), max_emitted_bytes=_CAP, project_root=tmp_path
    )
    assert set(results) == {str(p) for p in files}
    for p in files:
        res = results[str(p)]
        assert res.status == "ok"
        assert res.output is not None
        assert res.output.units is not None
        assert res.output.units[0].text == f"body of {p}"


def test_batch_missing_element_skips_that_file_only(tmp_path: Path) -> None:
    script = _script(tmp_path, _OMIT_FIRST_BODY)
    files = _make_files(tmp_path, 3)
    results = run_preprocessor_batch(
        files, _batch_rule(script), max_emitted_bytes=_CAP, project_root=tmp_path
    )
    # The first file is absent from the response -> skipped per on_error=skip;
    # the other two still succeed.
    assert results[str(files[0])].status == "skipped"
    assert results[str(files[0])].reason is not None
    assert results[str(files[1])].status == "ok"
    assert results[str(files[2])].status == "ok"


def test_batch_missing_element_passthrough(tmp_path: Path) -> None:
    script = _script(tmp_path, _OMIT_FIRST_BODY)
    files = _make_files(tmp_path, 2)
    results = run_preprocessor_batch(
        files,
        _batch_rule(script, on_error="passthrough"),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )
    assert results[str(files[0])].status == "passthrough"
    assert results[str(files[1])].status == "ok"


def test_batch_missing_element_on_error_fail_raises(tmp_path: Path) -> None:
    script = _script(tmp_path, _OMIT_FIRST_BODY)
    files = _make_files(tmp_path, 3)
    with pytest.raises(PreprocessAbortError):
        run_preprocessor_batch(
            files,
            _batch_rule(script, on_error="fail"),
            max_emitted_bytes=_CAP,
            project_root=tmp_path,
        )


def test_batch_non_array_envelope_fails_every_file(tmp_path: Path) -> None:
    script = _script(tmp_path, _NON_ARRAY_BODY)
    files = _make_files(tmp_path, 3)
    results = run_preprocessor_batch(
        files, _batch_rule(script), max_emitted_bytes=_CAP, project_root=tmp_path
    )
    # A whole-envelope defect resolves every file through on_error=skip.
    assert {r.status for r in results.values()} == {"skipped"}
    assert len(results) == 3


def test_batch_timeout_scales_and_resolves_per_file(tmp_path: Path) -> None:
    # timeout_s=0.2 over 2 files gives a 0.4s budget; the hook sleeps 5s, so the
    # batch times out and every file resolves through on_error=skip.
    script = _script(tmp_path, _SLEEP_BODY)
    files = _make_files(tmp_path, 2)
    results = run_preprocessor_batch(
        files,
        _batch_rule(script, timeout_s=0.2),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )
    assert set(results) == {str(p) for p in files}
    for res in results.values():
        assert res.status == "skipped"
        assert res.reason is not None
        assert "timed out" in res.reason


def test_batch_per_file_emitted_cap_skips_only_oversize(tmp_path: Path) -> None:
    body = """
        import json, sys
        with open(sys.argv[1], encoding="utf-8") as fh:
            paths = [line.rstrip("\\n") for line in fh if line.strip()]
        out = []
        for i, p in enumerate(paths):
            text = ("x" * 5000) if i == 0 else "small"
            out.append({"path": p, "schema_version": 1, "preprocessor_id": "c",
                        "preprocessor_version": "1.0", "source_path": p,
                        "text": text})
        print(json.dumps(out))
    """
    script = _script(tmp_path, body)
    files = _make_files(tmp_path, 2)
    results = run_preprocessor_batch(
        files, _batch_rule(script), max_emitted_bytes=100, project_root=tmp_path
    )
    oversize = results[str(files[0])]
    assert oversize.status == "skipped"
    assert oversize.reason is not None
    assert "exceeds cap" in oversize.reason
    assert results[str(files[1])].status == "ok"


# A batch hook that echoes each path RELATIVE to its cwd (the project root),
# exercising the parent's relative-path resolution against project_root.
_RELATIVE_BODY = """
    import json, os, sys
    with open(sys.argv[1], encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    print(json.dumps([
        {"path": os.path.relpath(p), "schema_version": 1, "preprocessor_id": "rel",
         "preprocessor_version": "1.0", "source_path": p,
         "units": [{"text": "rel " + p}]}
        for p in paths
    ]))
"""


def test_batch_relative_echoed_path_resolves_against_project_root(
    tmp_path: Path,
) -> None:
    # The hook runs with the project root as its cwd and echoes each path as
    # os.path.relpath(p) (relative to that cwd). The runner must resolve those
    # against project_root - not its own cwd - to map every element back.
    script = _script(tmp_path, _RELATIVE_BODY)
    files = _make_files(tmp_path, 3)
    results = run_preprocessor_batch(
        files, _batch_rule(script), max_emitted_bytes=_CAP, project_root=tmp_path
    )
    assert set(results) == {str(p) for p in files}
    for p in files:
        assert results[str(p)].status == "ok"


# --------------------------------------------------------------------------
# The batch worker: one spawn, per-file chunks, and D7 cache reuse.
# --------------------------------------------------------------------------

_COUNTING_BODY = """
    import json, sys
    log, manifest = sys.argv[1], sys.argv[2]
    with open(log, "a", encoding="utf-8") as counter:
        counter.write("spawn\\n")
    with open(manifest, encoding="utf-8") as fh:
        paths = [line.rstrip("\\n") for line in fh if line.strip()]
    print(json.dumps([
        {"path": p, "schema_version": 1, "preprocessor_id": "counting",
         "preprocessor_version": "1.0", "source_path": p,
         "units": [{"text": "unit for " + p}]}
        for p in paths
    ]))
"""


def _counting_context(tmp_path: Path) -> tuple[PreprocessContext, Path]:
    log = tmp_path / "spawns.log"
    script = _script(tmp_path, _COUNTING_BODY, name="counting.py")
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
        f"{shlex.quote(str(log))} {{paths}}"
    )
    rule = PreprocessRule(
        pattern="*.bin",
        command=command,
        entry_point=None,
        priority=100,
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
        batch=True,
    )
    ctx = PreprocessContext(
        config=PreprocessConfig([rule]),
        cache_root=preprocess_cache_dir(tmp_path),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )
    return ctx, log


def _spawn_count(log: Path) -> int:
    if not log.exists():
        return 0
    return len([line for line in log.read_text(encoding="utf-8").splitlines() if line])


def test_chunk_batch_files_one_spawn_for_many_files(tmp_path: Path) -> None:
    ctx, log = _counting_context(tmp_path)
    rule = ctx.config.rules[0]
    files = _make_files(tmp_path, 4)
    results = _chunk_worker.chunk_batch_files(files, tmp_path, rule, ctx)

    # One subprocess handled all four files.
    assert _spawn_count(log) == 1
    assert len(results) == 4
    for res in results:
        assert res.preprocess_status == "ok"
        assert res.content_hash
        assert len(res.chunks) == 1
        assert res.chunks[0].content.startswith("unit for ")
        assert res.chunks[0].preprocessor_id == "counting"


def test_batch_passthrough_propagates_source_read_failure(tmp_path: Path) -> None:
    script = _script(tmp_path, _DELETE_AND_OMIT_FIRST_BODY, name="delete-first.py")
    files = _make_files(tmp_path, 2)
    rule = _batch_rule(script, on_error="passthrough")
    ctx = PreprocessContext(
        config=PreprocessConfig([rule]),
        cache_root=preprocess_cache_dir(tmp_path),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )

    with pytest.raises(FileNotFoundError):
        _chunk_worker.chunk_batch_files(files, tmp_path, rule, ctx)


def test_chunk_batch_files_second_pass_hits_cache_no_spawn(tmp_path: Path) -> None:
    ctx, log = _counting_context(tmp_path)
    rule = ctx.config.rules[0]
    files = _make_files(tmp_path, 3)

    first = _chunk_worker.chunk_batch_files(files, tmp_path, rule, ctx)
    assert _spawn_count(log) == 1

    # Delete the hook script: a fully-cached second pass must not need it.
    (tmp_path / "counting.py").unlink()
    second = _chunk_worker.chunk_batch_files(files, tmp_path, rule, ctx)

    # No further spawn, and the chunks match the first pass exactly.
    assert _spawn_count(log) == 1
    assert [c.content for c in _flatten(first)] == [c.content for c in _flatten(second)]


def test_chunk_batch_files_mixed_hit_miss_shrinks_manifest(tmp_path: Path) -> None:
    ctx, log = _counting_context(tmp_path)
    rule = ctx.config.rules[0]
    files = _make_files(tmp_path, 3)

    # Prime the cache for the first two files only.
    _chunk_worker.chunk_batch_files(files[:2], tmp_path, rule, ctx)
    assert _spawn_count(log) == 1

    # A pass over all three re-spawns once (for the single miss) and still maps
    # every file, cache hits included.
    results = _chunk_worker.chunk_batch_files(files, tmp_path, rule, ctx)
    assert _spawn_count(log) == 2
    assert len(results) == 3
    assert all(res.preprocess_status == "ok" for res in results)


def _flatten(results: list[_chunk_worker.FileChunkResult]) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    for res in results:
        chunks.extend(res.chunks)
    return chunks


# --------------------------------------------------------------------------
# Indexer dispatch: batch matches are grouped, everything else stays per-file.
# --------------------------------------------------------------------------


def _batch_indexer(root: Path, ctx: PreprocessContext) -> CodebaseIndexer:
    """Build a chunk-only indexer wired with a batch preprocess context.

    Mirrors the established ``__new__`` + manual attribute pattern: the chunk
    dispatch never touches the embedding model or vector store.
    """
    indexer = CodebaseIndexer.__new__(CodebaseIndexer)
    indexer.root_dir = root
    indexer._extra_excludes = []
    indexer._prep_ctx = ctx
    indexer._prep_skips = []
    indexer._prep_ok = 0
    return indexer


def test_chunk_paths_batches_matches_and_chunks_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EnvVar.INDEX_CHUNK_WORKERS.value, "1")
    reset_config()

    ctx, log = _counting_context(tmp_path)
    bins = _make_files(tmp_path, 3)
    py = tmp_path / "module.py"
    py.write_text("def foo():\n    return 1\n", encoding="utf-8")

    indexer = _batch_indexer(tmp_path, ctx)
    chunks = indexer._chunk_paths([*bins, py], reporter=NullProgressReporter())

    # One spawn handled all three batch files; the .py file chunked normally.
    assert _spawn_count(log) == 1
    preproc = [c for c in chunks if c.preprocessor_id == "counting"]
    normal = [c for c in chunks if c.preprocessor_id is None]
    assert len(preproc) == 3
    assert normal  # the .py file produced ordinary code chunks
    assert indexer._prep_ok == 3


def _counting_rule(command: str, pattern: str) -> PreprocessRule:
    return PreprocessRule(
        pattern=pattern,
        command=command,
        entry_point=None,
        priority=100,
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
        batch=True,
    )


def test_chunk_paths_multi_worker_pool_over_batch_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two batch rules give two groups; forcing two workers routes them through
    # the real process-pool (as_completed) branch of _run_batch_groups, not the
    # serial fallback.
    monkeypatch.setenv(EnvVar.INDEX_CHUNK_WORKERS.value, "2")
    reset_config()

    log = tmp_path / "spawns.log"
    script = _script(tmp_path, _COUNTING_BODY, name="counting.py")
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
        f"{shlex.quote(str(log))} {{paths}}"
    )
    ctx = PreprocessContext(
        config=PreprocessConfig(
            [_counting_rule(command, "*.aaa"), _counting_rule(command, "*.bbb")]
        ),
        cache_root=preprocess_cache_dir(tmp_path),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )
    a_files = [tmp_path / f"a{i}.aaa" for i in range(3)]
    b_files = [tmp_path / f"b{i}.bbb" for i in range(3)]
    for p in (*a_files, *b_files):
        p.write_bytes(p.name.encode())

    indexer = _batch_indexer(tmp_path, ctx)
    chunks = indexer._chunk_paths([*a_files, *b_files], reporter=NullProgressReporter())

    # Two groups -> two batch spawns through the pool; every file produced a
    # preprocessed chunk.
    assert _spawn_count(log) == 2
    preproc = [c for c in chunks if c.preprocessor_id == "counting"]
    assert len(preproc) == 6
    assert indexer._prep_ok == 6

    # Cache entries were written by the pool tasks: a second pass hits the cache
    # with no further spawn, even without the hook script present.
    (tmp_path / "counting.py").unlink()
    indexer2 = _batch_indexer(tmp_path, ctx)
    again = indexer2._chunk_paths([*a_files, *b_files], reporter=NullProgressReporter())
    assert _spawn_count(log) == 2
    assert len([c for c in again if c.preprocessor_id == "counting"]) == 6


def test_indexer_pool_propagates_batch_on_error_fail(tmp_path: Path) -> None:
    """The production process-pool path preserves the fail policy."""
    script = _script(tmp_path, _OMIT_FIRST_BODY, name="omit_first.py")
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{paths}}"
    rules = [
        PreprocessRule(
            pattern=pattern,
            command=command,
            entry_point=None,
            priority=100,
            on_error="fail",
            timeout_s=30.0,
            options={},
            order=order,
            batch=True,
        )
        for order, pattern in enumerate(("*.aaa", "*.bbb"))
    ]
    ctx = PreprocessContext(
        config=PreprocessConfig(rules),
        cache_root=preprocess_cache_dir(tmp_path),
        max_emitted_bytes=_CAP,
        project_root=tmp_path,
    )
    files = [tmp_path / "first.aaa", tmp_path / "second.bbb"]
    for path in files:
        path.write_bytes(path.name.encode())

    indexer = _batch_indexer(tmp_path, ctx)
    with pytest.raises(PreprocessAbortError):
        indexer._chunk_paths(files, reporter=NullProgressReporter())


def test_batch_pool_retains_only_one_worker_window(tmp_path: Path) -> None:
    """Slow publication cannot let the pool preprocess the whole corpus ahead."""
    previous_workers = os.environ.get(EnvVar.INDEX_CHUNK_WORKERS.value)
    os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = "2"
    reset_config()
    try:
        marker_dir = tmp_path / "window-markers"
        marker_dir.mkdir()
        window_body = """
            import json, pathlib, sys
            marker_dir, manifest = pathlib.Path(sys.argv[1]), sys.argv[2]
            with open(manifest, encoding="utf-8") as fh:
                paths = [line.rstrip("\\n") for line in fh if line.strip()]
            marker = marker_dir / (pathlib.Path(paths[0]).suffix.lstrip(".") + ".done")
            marker.write_text("done", encoding="utf-8")
            print(json.dumps([
                {"path": p, "schema_version": 1, "preprocessor_id": "window",
                 "preprocessor_version": "1.0", "source_path": p,
                 "units": [{"text": "unit for " + p}]}
                for p in paths
            ]))
        """
        script = _script(tmp_path, window_body, name="window_counting.py")
        command = (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
            f"{shlex.quote(str(marker_dir))} {{paths}}"
        )
        rules = [_counting_rule(command, f"*.g{i}") for i in range(6)]
        ctx = PreprocessContext(
            config=PreprocessConfig(rules),
            cache_root=preprocess_cache_dir(tmp_path),
            max_emitted_bytes=_CAP,
            project_root=tmp_path,
        )
        files = [tmp_path / f"doc.g{i}" for i in range(6)]
        for path in files:
            path.write_bytes(path.name.encode())

        indexer = _batch_indexer(tmp_path, ctx)
        batch_groups, singles = indexer._partition_batch_work(files)
        assert singles == []
        assert len(batch_groups) == 6

        handler_started = threading.Event()
        release_handler = threading.Event()
        received: list[int] = []
        failures: list[BaseException] = []

        def _observe_window(results: list[_chunk_worker.FileChunkResult]) -> None:
            received.append(len(results))
            handler_started.set()
            assert release_handler.wait(timeout=15)

        def _run() -> None:
            try:
                indexer._run_batch_groups(
                    batch_groups,
                    NullProgressReporter(),
                    _observe_window,
                )
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        try:
            assert handler_started.wait(timeout=15)
            time.sleep(1.0)
            assert len(list(marker_dir.glob("*.done"))) <= 2
        finally:
            release_handler.set()
            worker.join(timeout=30)
        assert not worker.is_alive()
        assert failures == []
        assert sum(received) == 6
        assert len(list(marker_dir.glob("*.done"))) == 6
    finally:
        if previous_workers is None:
            os.environ.pop(EnvVar.INDEX_CHUNK_WORKERS.value, None)
        else:
            os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = previous_workers
        reset_config()
