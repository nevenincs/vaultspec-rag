"""Code admission and reads reject filesystem aliases to ignored inputs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..indexer._chunk_worker import chunk_and_hash_file, chunk_batch_files
from ..indexer._codebase_indexer import CodebaseIndexer
from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._content_policy import AdmissionReason
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    PreprocessConfig,
    PreprocessContext,
    PreprocessRule,
)
from ..indexer._stat_gate import file_digest
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("target_name", [".env", ".git/config", "private/input.py"])
@pytest.mark.parametrize("chained", [False, True])
@pytest.mark.parametrize("transformed", [False, True])
def test_discovery_rejects_ignored_target_alias(
    tmp_path: Path, target_name: str, chained: bool, transformed: bool
) -> None:
    """Removing the identity gates failed membership; restoring them passed."""
    target = tmp_path / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture_sensitive_value = 'fixture only'\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\nprivate/\n", encoding="utf-8")
    if transformed:
        (tmp_path / PREPROCESS_CONFIG_FILENAME).write_text(
            'version = 2\n[[rule]]\npattern = "*.py"\ntarget = "code"\n'
            'extractor_version = "1"\ncommand = "unused {path}"\non_error = "skip"\n',
            encoding="utf-8",
        )
    source = tmp_path / "source.py"
    source.symlink_to(target)
    if chained:
        outer = tmp_path / "outer.py"
        outer.symlink_to(source)
    ordinary = tmp_path / "main.py"
    ordinary.write_text("ordinary = 1\n", encoding="utf-8")

    scan = CodeContentDiscovery(tmp_path).scan_admission()

    assert scan.files == (ordinary,), "symlink aliases must not enter code membership"
    sample = next(sample for sample in scan.samples if sample.path == source.name)
    assert not sample.admitted
    assert sample.reason is AdmissionReason.SOURCE_PROBE_FAILED
    assert scan.measurement.source_files == 1
    assert scan.measurement.source_bytes == ordinary.stat().st_size


def test_full_preflight_rejects_source_replaced_by_link(tmp_path: Path) -> None:
    """Disabling identity validation failed the refusal; restoring it passed."""
    source = tmp_path / "source.py"
    source.write_text("ordinary = 1\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("fixture_sensitive_value = 1\n", encoding="utf-8")
    discovery = CodeContentDiscovery(tmp_path)
    preflight = discovery.preflight_content()
    source.unlink()
    source.symlink_to(target)

    with pytest.raises(ValueError, match="non-canonical source"):
        discovery.accept_preflight(preflight, changed_paths=None)


def test_full_preflight_rejects_forged_link_membership(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("fixture_sensitive_value = 1\n", encoding="utf-8")
    alias = tmp_path / "source.py"
    alias.symlink_to(target)
    discovery = CodeContentDiscovery(tmp_path)
    preflight = discovery.preflight_content()
    forged = replace(preflight, scan=replace(preflight.scan, files=(alias,)))

    with pytest.raises(ValueError, match="non-canonical source"):
        discovery.accept_preflight(forged, changed_paths=None)


@pytest.mark.parametrize("directory_alias", [False, True])
def test_worker_rejects_link_created_after_preflight(
    tmp_path: Path, directory_alias: bool
) -> None:
    """Unguarded reads failed the zero-chunk assertion; guarded reads passed."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "source.py"
    source.write_text("ordinary = 1\n", encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir()
    target = private / "source.py"
    target.write_text("fixture_sensitive_value = 'fixture only'\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("private/\n", encoding="utf-8")
    discovery = CodeContentDiscovery(tmp_path)
    preflight = discovery.preflight_content()
    discovery.accept_preflight(preflight, changed_paths=None)
    source.unlink()
    if directory_alias:
        source_dir.rmdir()
        source_dir.symlink_to(private, target_is_directory=True)
    else:
        source.symlink_to(target)

    result = chunk_and_hash_file(source, tmp_path)

    assert result.chunks == [], "a replaced source must yield no protected chunks"
    assert result.content_hash == "unpublished"
    assert result.preprocess_status == "skipped"
    assert result.preprocess_reason is not None


def test_incremental_digest_rejects_link(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("fixture_sensitive_value = 1\n", encoding="utf-8")
    source = tmp_path / "source.py"
    source.symlink_to(target)

    with pytest.raises(OSError, match="non-canonical source"):
        file_digest(source, root_dir=tmp_path)


def test_regular_source_keeps_hash_chunks_and_preflight(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    raw = b"def ordinary():\r\n    return 1\r\n"
    source.write_bytes(raw)
    discovery = CodeContentDiscovery(tmp_path)
    preflight = discovery.preflight_content()
    _policy, paths = discovery.accept_preflight(preflight, changed_paths=None)
    result = chunk_and_hash_file(source, tmp_path)

    assert paths == (source,)
    assert result.content_hash == hashlib.blake2b(raw).hexdigest()
    assert file_digest(source, root_dir=tmp_path) == result.content_hash
    assert result.chunks
    assert all(chunk.path == "main.py" for chunk in result.chunks)
    assert "return 1" in "\n".join(chunk.content for chunk in result.chunks)


def test_symlinked_project_root_keeps_regular_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("ordinary = 1\n", encoding="utf-8")
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)
    discovery = CodeContentDiscovery(alias)
    preflight = discovery.preflight_content()
    _policy, paths = discovery.accept_preflight(preflight, changed_paths=None)

    assert paths == (source,)
    assert chunk_and_hash_file(source, project).chunks


@pytest.mark.parametrize("directory_alias", [False, True])
def test_open_time_replacement_cannot_supply_worker_bytes(
    tmp_path: Path, directory_alias: bool
) -> None:
    """Disabling opened-object checks failed zero chunks; restoring them passed.

    An audit hook schedules real filesystem replacement at the open syscall,
    after source inspection; the child contains its process-wide hook.
    """
    script = textwrap.dedent(
        """
        import json, os, sys
        from pathlib import Path
        from vaultspec_rag.indexer._chunk_worker import chunk_and_hash_file

        root = Path(sys.argv[1])
        directory_alias = sys.argv[2] == 'True'
        source_dir = root / 'src'
        source_dir.mkdir()
        source = source_dir / 'source.py'
        source.write_text('ordinary = 1\\n', encoding='utf-8')
        private = root / 'private'
        private.mkdir()
        target = private / source.name
        target.write_text('fixture_sensitive_value = 1\\n', encoding='utf-8')
        replaced = False

        def intercept(event, args):
            global replaced
            if event != 'open' or replaced:
                return
            name = args[0]
            trigger = str(source) if os.name == 'nt' else (
                'src' if directory_alias else source.name
            )
            if name != trigger:
                return
            replaced = True
            if directory_alias:
                source_dir.rename(root / 'original')
                source_dir.symlink_to(private, target_is_directory=True)
            else:
                source.unlink()
                source.symlink_to(target)

        sys.addaudithook(intercept)
        try:
            result = chunk_and_hash_file(source, root)
            chunks = [chunk.content for chunk in result.chunks]
        except OSError:
            chunks = []
        print(json.dumps({'replaced': replaced, 'chunks': chunks}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(directory_alias)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert result["replaced"], "the source replacement must reach the open syscall"
    assert result["chunks"] == [], "opened aliases must not yield protected chunks"


@pytest.mark.parametrize("target_kind", ["safe", "outside", "missing"])
def test_discovery_rejects_other_file_link_targets(
    tmp_path: Path, target_kind: str
) -> None:
    source = tmp_path / "source.py"
    target = (
        tmp_path.parent / "outside-source.py"
        if target_kind == "outside"
        else tmp_path / "target.py"
    )
    if target_kind != "missing":
        target.write_text("ordinary = 1\n", encoding="utf-8")
    source.symlink_to(target)

    scan = CodeContentDiscovery(tmp_path).scan_admission()

    expected = (target,) if target_kind == "safe" else ()
    assert scan.files == expected
    sample = next(sample for sample in scan.samples if sample.path == source.name)
    assert not sample.admitted
    assert sample.reason is AdmissionReason.SOURCE_PROBE_FAILED


@pytest.mark.parametrize("batch", [False, True])
def test_code_transform_cannot_bypass_link_rejection(
    tmp_path: Path, batch: bool
) -> None:
    from ..indexer._content_policy import ContentKind

    target = tmp_path / ".env"
    target.write_text("fixture_sensitive_value = 1\n", encoding="utf-8")
    alias = tmp_path / "source.py"
    alias.symlink_to(target)
    command = f'{sys.executable} -c "raise RuntimeError()" {{path}}'
    rule = PreprocessRule(
        pattern="*.py",
        command=command,
        entry_point=None,
        priority=100,
        target=ContentKind.CODE,
        extractor_version="1",
        on_error="skip",
        timeout_s=5,
        options={},
        order=0,
        batch=batch,
    )
    prep = PreprocessContext(
        config=PreprocessConfig([rule]),
        cache_root=tmp_path / "cache",
        max_emitted_bytes=1024,
        project_root=tmp_path,
    )

    if batch:
        results = chunk_batch_files([alias], tmp_path, rule, prep)
        assert len(results) == 1
        result = results[0]
    else:
        result = chunk_and_hash_file(alias, tmp_path, prep)

    assert result.content_hash == "unpublished"
    assert result.chunks == []
    assert result.preprocess_status == "skipped"


def test_cached_code_digest_does_not_reuse_link_target(tmp_path: Path) -> None:
    """Allowing link-following stat failed empty hashes; restoring the gate passed."""
    source = tmp_path / "source.py"
    source.write_bytes(b"ordinary = 1\n")
    old_time = time.time() - 10
    os.utime(source, (old_time, old_time))
    observed = source.stat()
    indexer = CodebaseIndexer(tmp_path, cast("Any", None), cast("Any", None))
    first = indexer._hash_changed_paths({source.name: source}, NullProgressReporter())
    assert first[source.name] == hashlib.blake2b(source.read_bytes()).hexdigest()
    target = tmp_path / ".env"
    target.write_bytes(b"protected= 1\n")
    assert target.stat().st_size == observed.st_size
    os.utime(target, ns=(observed.st_atime_ns, observed.st_mtime_ns))
    source.unlink()
    source.symlink_to(target)
    selected = {source.name: source}

    hashes = indexer._hash_changed_paths(selected, NullProgressReporter())

    assert hashes == {}, "linked sources must not reuse cached code hashes"
    assert selected == {}
