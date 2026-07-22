"""Unit tests for out-of-process entry_point preprocessors (#185 follow-up, no GPU).

Exercises the entry runner directly (`resolve_entry_point`, `main`) and end-to-end
through `run_preprocessor`, which invokes the runner as a real subprocess. A real
extractor module is written to a temp dir and made importable to the child via
``PYTHONPATH`` (real env, no mocks).
"""

from __future__ import annotations

import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import OnError, PreprocessRule
from ..indexer._preprocess_entry import main, resolve_entry_point
from ..indexer._preprocess_runner import PreprocessResult, run_preprocessor

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_EXTRACTOR_MODULE = """
def extract(source_path):
    return {
        "schema_version": 1,
        "preprocessor_id": "entry-fake",
        "preprocessor_version": "1.0",
        "source_path": source_path,
        "units": [{"text": "extracted via entry point",
                   "anchor": source_path + "#page=1",
                   "locator": {"kind": "page", "value": 1}}],
    }


def boom(source_path):
    raise RuntimeError("extractor blew up")
"""


@pytest.fixture
def entry_modpath(tmp_path: Path) -> Generator[Path]:
    """Write an importable extractor module and expose it to child processes."""
    pkg_dir = tmp_path
    (pkg_dir / "extractor_mod.py").write_text(
        textwrap.dedent(_EXTRACTOR_MODULE), encoding="utf-8"
    )
    sys.path.insert(0, str(pkg_dir))
    prev = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        str(pkg_dir) + os.pathsep + prev if prev else str(pkg_dir)
    )
    try:
        yield pkg_dir
    finally:
        sys.path.remove(str(pkg_dir))
        if prev is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prev
        sys.modules.pop("extractor_mod", None)


def _entry_rule(ref: str, *, on_error: OnError = "skip") -> PreprocessRule:
    return PreprocessRule(
        pattern="*.pdf",
        command=None,
        entry_point=ref,
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
        on_error=on_error,
        timeout_s=30.0,
        options={},
        order=0,
    )


@pytest.mark.usefixtures("entry_modpath")
def test_resolve_entry_point_ok() -> None:
    assert callable(resolve_entry_point("extractor_mod:extract"))


def test_resolve_entry_point_bad_format() -> None:
    with pytest.raises(ValueError, match="module:callable"):
        resolve_entry_point("no-colon-here")


@pytest.mark.usefixtures("entry_modpath")
def test_resolve_entry_point_missing_attr() -> None:
    with pytest.raises(AttributeError):
        resolve_entry_point("extractor_mod:does_not_exist")


@pytest.mark.usefixtures("entry_modpath")
def test_main_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extractor_mod:extract", "docs/a.pdf"]) == 0
    assert '"preprocessor_id": "entry-fake"' in capsys.readouterr().out


def test_main_bad_ref_returns_nonzero() -> None:
    assert main(["nope:nothing", "docs/a.pdf"]) == 3


def _entry_run(
    source: Path,
    ref: str,
    *,
    project_root: Path,
    on_error: OnError = "skip",
) -> PreprocessResult:
    """Invoke the runner on an entry_point rule directly.

    The curated child env carries no inherited ``PYTHONPATH``; the runner puts
    ``project_root`` on it so a project-local entry_point module resolves. The
    extractor module the fixture writes lives under ``project_root``, so the
    child imports it there.
    """
    return run_preprocessor(
        source,
        _entry_rule(ref, on_error=on_error),
        max_emitted_bytes=1024 * 1024,
        project_root=project_root,
    )


def test_run_preprocessor_entry_point_ok(entry_modpath: Path, tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"\x00\x01binary")
    result = _entry_run(source, "extractor_mod:extract", project_root=entry_modpath)
    assert result.status == "ok"
    assert result.output is not None
    assert result.output.preprocessor_id == "entry-fake"
    assert result.output.units is not None
    assert result.output.units[0].locator is not None
    assert result.output.units[0].locator.value == 1


def test_run_preprocessor_entry_point_raises_is_skipped(
    entry_modpath: Path, tmp_path: Path
) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"x")
    result = _entry_run(source, "extractor_mod:boom", project_root=entry_modpath)
    assert result.status == "skipped"
    assert result.reason is not None


def test_run_preprocessor_entry_point_unresolvable_is_skipped(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"x")
    result = _entry_run(source, "missing_module_xyz:fn", project_root=tmp_path)
    assert result.status == "skipped"
