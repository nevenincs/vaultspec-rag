"""Unit tests for :mod:`vaultspec_rag.torch_config`.

Covers the five classification states, apply/remove symmetry, conflict
detection, and the torch-diagnosis lookup table. All fixtures are real
``pyproject.toml`` files at ``tmp_path``; no mocks, no monkeypatching.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
import tomlkit

from vaultspec_rag import torch_config as tc

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


PROJECT_ONLY = (
    '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["requests"]\n'
)

# CRLF gets normalised to LF by tomlkit's round-trip. Tests that want
# byte-equality after a full round-trip must start from LF content.
PROJECT_WITH_COMMENTS = (
    "# Top-of-file comment\n"
    "[project]\n"
    'name = "demo"  # inline name comment\n'
    'version = "0.1.0"\n'
    "# Between project and deps\n"
    "dependencies = [\n"
    '    "requests",\n'
    '    "urllib3",\n'
    "]\n"
)

CANONICAL_TAIL = (
    "\n"
    "[[tool.uv.index]]\n"
    'name = "pytorch-cu130"\n'
    'url = "https://download.pytorch.org/whl/cu130"\n'
    "explicit = true\n"
    "\n"
    "[tool.uv.sources]\n"
    "torch = [\n"
    '    {index = "pytorch-cu130", '
    "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"},\n"
    "]\n"
)

CUSTOM_WRONG_URL_TAIL = (
    "\n"
    "[[tool.uv.index]]\n"
    'name = "pytorch-cu130"\n'
    'url = "https://download.pytorch.org/whl/cu121"\n'
    "explicit = true\n"
)

CUSTOM_EXTRA_KEY_TAIL = (
    "\n"
    "[[tool.uv.index]]\n"
    'name = "pytorch-cu130"\n'
    'url = "https://download.pytorch.org/whl/cu130"\n'
    "explicit = true\n"
    "\n"
    "[tool.uv.sources]\n"
    "torch = [\n"
    '    {index = "pytorch-cu130", '
    "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\", "
    "priority = 1},\n"
    "]\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# detect_state
# ---------------------------------------------------------------------------


def test_detect_state_no_project_file(tmp_path: Path) -> None:
    assert (
        tc.detect_state(tmp_path / "pyproject.toml")
        == tc.TorchConfigState.NO_PROJECT_FILE
    )


def test_detect_state_missing(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING


def test_detect_state_canonical(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CANONICAL_TAIL)
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_detect_state_customised_wrong_url(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CUSTOM_WRONG_URL_TAIL)
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED


def test_detect_state_customised_extra_keys(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CUSTOM_EXTRA_KEY_TAIL)
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------


def test_apply_on_missing_writes_canonical(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    report = tc.apply_patch(p)
    assert report.action == "applied"
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_apply_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    tc.apply_patch(p)
    sha_after_first = _sha(p)
    report = tc.apply_patch(p)
    assert report.action == "already"
    assert _sha(p) == sha_after_first


def test_apply_on_customised_returns_conflict(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CUSTOM_WRONG_URL_TAIL)
    sha_before = _sha(p)
    report = tc.apply_patch(p)
    assert report.action == "conflict"
    assert report.conflicts  # non-empty
    assert _sha(p) == sha_before


def test_apply_on_absent_file(tmp_path: Path) -> None:
    report = tc.apply_patch(tmp_path / "pyproject.toml")
    assert report.action == "absent"


def test_apply_preserves_user_comments(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_WITH_COMMENTS)
    tc.apply_patch(p)
    after = p.read_text(encoding="utf-8")
    assert "# Top-of-file comment" in after
    assert "# inline name comment" in after
    assert "# Between project and deps" in after
    # All three deps still present in order.
    assert after.index('"requests"') < after.index('"urllib3"')


# ---------------------------------------------------------------------------
# remove_patch
# ---------------------------------------------------------------------------


def test_apply_then_remove_semantic_round_trip(tmp_path: Path) -> None:
    """After apply + remove, the parsed document is semantically equal
    to the original. Byte-equality is not guaranteed because tomlkit
    normalises line endings and appends a trailing newline."""
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    orig_parsed = tomlkit.parse(PROJECT_ONLY)
    tc.apply_patch(p)
    tc.remove_patch(p)
    final_parsed = tomlkit.parse(p.read_text(encoding="utf-8"))
    # Project table survives intact.
    assert final_parsed["project"] == orig_parsed["project"]
    # No [tool.uv] residue.
    assert "tool" not in final_parsed or "uv" not in final_parsed.get("tool", {})


def test_remove_on_missing_is_absent(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    report = tc.remove_patch(p)
    assert report.action == "absent"


def test_remove_on_customised_skips(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CUSTOM_WRONG_URL_TAIL)
    sha_before = _sha(p)
    report = tc.remove_patch(p)
    assert report.action == "skipped"
    assert report.conflicts
    assert _sha(p) == sha_before


def test_remove_on_no_project_file(tmp_path: Path) -> None:
    report = tc.remove_patch(tmp_path / "pyproject.toml")
    assert report.action == "absent"


# ---------------------------------------------------------------------------
# diagnose_torch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cuda", "available", "expected"),
    [
        (None, False, tc.TorchDiagnosis.CPU_ONLY),
        (None, True, tc.TorchDiagnosis.CPU_ONLY),  # anomaly → safer message
        ("13.0", False, tc.TorchDiagnosis.NO_GPU),
        ("13.0", True, tc.TorchDiagnosis.WORKING),
    ],
)
def test_diagnose_torch(
    cuda: str | None, available: bool, expected: tc.TorchDiagnosis
) -> None:
    assert tc.diagnose_torch(cuda, available) == expected


# ---------------------------------------------------------------------------
# manual_snippet / preview_patch
# ---------------------------------------------------------------------------


def test_manual_snippet_is_valid_toml() -> None:
    snippet = tc.manual_snippet()
    # Parses without error and yields our canonical shape. unwrap() drops
    # the tomlkit Item wrappers so nested subscription type-checks cleanly.
    doc = tomlkit.parse(snippet).unwrap()
    assert doc["tool"]["uv"]["index"][0]["name"] == tc.CU130_INDEX_NAME
    assert doc["tool"]["uv"]["index"][0]["url"] == tc.CU130_INDEX_URL
    assert doc["tool"]["uv"]["sources"]["torch"][0]["index"] == tc.CU130_INDEX_NAME


def test_preview_patch_on_missing(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    assert tc.preview_patch(p) == tc.manual_snippet()


def test_preview_patch_on_canonical(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CANONICAL_TAIL)
    assert tc.preview_patch(p) == ""


def test_preview_patch_on_customised(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY + CUSTOM_WRONG_URL_TAIL)
    assert tc.preview_patch(p) == ""


# ---------------------------------------------------------------------------
# detect on rag's own pyproject — must already be CANONICAL. Regression
# guard: if the canonical shape in this module drifts from rag's own
# pyproject.toml, this test fails and the constants must be re-aligned.
# ---------------------------------------------------------------------------


def test_rag_own_pyproject_is_canonical() -> None:
    from pathlib import Path as _Path

    rag_root = _Path(__file__).resolve().parents[3]
    pyproject = rag_root / "pyproject.toml"
    # If this path resolution breaks (e.g. editable layout changes),
    # the file must at least exist for the test to be meaningful.
    assert pyproject.is_file(), f"cannot locate rag pyproject at {pyproject}"
    assert tc.detect_state(pyproject) == tc.TorchConfigState.CANONICAL
