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


def test_detect_state_customised_single_table_index(tmp_path: Path) -> None:
    """User wrote `[tool.uv.index]` (single table) instead of the
    array-of-tables form. Classifier must flag this as CUSTOMISED so
    apply_patch refuses, avoiding an AttributeError on ``.append()``.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        PROJECT_ONLY + "\n[tool.uv.index]\n"
        'name = "private"\n'
        'url = "https://private.example.com/simple"\n',
    )
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED
    report = tc.apply_patch(p)
    assert report.action == "conflict"
    assert any("single table" in c for c in report.conflicts)


def test_detect_state_customised_scalar_torch_source(tmp_path: Path) -> None:
    """User wrote `torch = "some-string"` - legal TOML, nonsense for
    uv. Classifier must flag CUSTOMISED so apply_patch refuses before
    the mutation helpers crash on a non-dict value.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        PROJECT_ONLY + '\n[tool.uv.sources]\ntorch = "pinned-string"\n',
    )
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED
    report = tc.apply_patch(p)
    assert report.action == "conflict"
    assert any("not an array or table" in c for c in report.conflicts)


def test_remove_drops_empty_tool_uv_after_full_uninstall(tmp_path: Path) -> None:
    """After apply → remove, no orphaned [tool.uv.sources] / [tool.uv]
    / [tool] sections remain when those tables were introduced by us.
    Regression guard for the cascading-cleanup fix in
    :func:`_drop_torch_source`.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, PROJECT_ONLY)
    tc.apply_patch(p)
    tc.remove_patch(p)
    after = p.read_text(encoding="utf-8")
    # None of these section headers should survive the round trip.
    assert "[tool.uv.sources]" not in after
    assert "[[tool.uv.index]]" not in after
    assert "[tool.uv]" not in after
    # And the file still reparses cleanly.
    tomlkit.parse(after)


def test_detect_state_customised_standard_table_torch_source(tmp_path: Path) -> None:
    """User wrote `[tool.uv.sources.torch]` (standard table section)
    rather than an inline-table array. Classifier must flag this as
    CUSTOMISED so apply_patch refuses, avoiding an invalid-TOML
    promotion into an array.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        PROJECT_ONLY + "\n[tool.uv.sources.torch]\n"
        'git = "https://github.com/pytorch/pytorch"\n'
        'rev = "main"\n',
    )
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED
    report = tc.apply_patch(p)
    assert report.action == "conflict"
    assert any("standard table" in c for c in report.conflicts)


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


def test_remove_preserves_user_trivia_on_sibling_index_entries(
    tmp_path: Path,
) -> None:
    """When the consumer has *other* [[tool.uv.index]] entries alongside
    our cu130 block, removal must keep their comments and formatting.
    Regression guard for the remove_patch in-place pop() approach.
    """
    p = tmp_path / "pyproject.toml"
    content = (
        PROJECT_ONLY + "\n" + "# user index before cu130\n"
        "[[tool.uv.index]]\n"
        'name = "private"\n'
        'url = "https://private.example.com/simple"\n'
        "\n"
        "[[tool.uv.index]]\n"
        'name = "pytorch-cu130"\n'
        'url = "https://download.pytorch.org/whl/cu130"\n'
        "explicit = true\n"
        "\n"
        "[tool.uv.sources]\n"
        "# user comment above torch pin\n"
        "torch = [\n"
        '    {index = "pytorch-cu130", '
        "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"},\n"
        "]\n"
    )
    _write(p, content)
    tc.remove_patch(p)
    after = p.read_text(encoding="utf-8")
    # The user's sibling index entry and its preceding comment survive.
    assert "# user index before cu130" in after
    assert '"private"' in after
    assert "https://private.example.com/simple" in after
    # The cu130 entry is gone.
    assert "pytorch-cu130" not in after
    # File still reparses as valid TOML.
    tomlkit.parse(after)


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
# detect on rag's own pyproject - must already be CANONICAL. Regression
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


# ---------------------------------------------------------------------------
# OutOfOrderTableProxy / scattered ``[tool.*]`` shapes (#83 finding 1)
#
# tomlkit returns ``OutOfOrderTableProxy`` for any ``[tool.X]`` whose
# child tables are interleaved with unrelated sections. This is the
# dominant pyproject layout. Detection used to misclassify these as
# MISSING, and apply_patch crashed on the resulting state. Each test
# below pins one bug-class so future regressions cannot creep back in.
# ---------------------------------------------------------------------------


# Scattered ``[tool.uv]`` / ``[tool.ruff]`` / ``[tool.uv.sources]`` -
# the exact reproducer from issue #83. A single string keeps the test
# bodies focused on the assertion rather than fixture plumbing.
SCATTERED_PROJECT = (
    "[project]\n"
    'name = "demo"\n'
    'version = "0.1.0"\n'
    'dependencies = ["requests", "torch>=2.4"]\n'
    "\n"
    "[tool.uv]\n"
    "override-dependencies = []\n"
    "\n"
    "[tool.ruff]\n"
    "line-length = 120\n"
    "\n"
    "[tool.pytest.ini_options]\n"
    'testpaths = ["tests"]\n'
    "\n"
    "[tool.coverage.run]\n"
    'source = ["src"]\n'
)


SCATTERED_CANONICAL_TAIL = (
    "\n"
    "[[tool.uv.index]]\n"
    'name = "pytorch-cu130"\n'
    'url = "https://download.pytorch.org/whl/cu130"\n'
    "explicit = true\n"
    "\n"
    "[tool.ruff.lint]\n"
    'select = ["E"]\n'
    "\n"
    "[tool.uv.sources]\n"
    "torch = [\n"
    '    {index = "pytorch-cu130", '
    "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"},\n"
    "]\n"
)


def test_scattered_tool_uv_detect_canonical(tmp_path: Path) -> None:
    """Scattered ``[tool.uv.*]`` with intervening ``[tool.ruff.lint]``
    section - tomlkit yields ``OutOfOrderTableProxy`` for ``tool.uv``.
    Detection must return CANONICAL, not MISSING.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT + SCATTERED_CANONICAL_TAIL)
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_scattered_tool_uv_detect_missing(tmp_path: Path) -> None:
    """Same scattered layout, but no cu130 block. Must classify as
    MISSING (not crash, not CUSTOMISED, not NO_PROJECT_FILE).
    """
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT)
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING


def test_scattered_tool_uv_apply_writes_patch(tmp_path: Path) -> None:
    """``apply_patch`` on a scattered MISSING pyproject lands the
    canonical block without raising on OutOfOrderTableProxy. Round-trip
    leaves the file CANONICAL.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT)
    report = tc.apply_patch(p)
    assert report.action == "applied", report.conflicts
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL
    after = p.read_text(encoding="utf-8")
    # User's other tool.* sections survive intact.
    assert "[tool.ruff]" in after
    assert "[tool.pytest.ini_options]" in after
    assert "[tool.coverage.run]" in after


def test_scattered_tool_uv_apply_idempotent(tmp_path: Path) -> None:
    """Apply on already-canonical scattered pyproject is a no-op."""
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT + SCATTERED_CANONICAL_TAIL)
    sha_before = _sha(p)
    report = tc.apply_patch(p)
    assert report.action == "already"
    assert _sha(p) == sha_before


def test_scattered_tool_uv_remove_succeeds(tmp_path: Path) -> None:
    """Removal walks the cascade (drop AoT entry → del index →
    del sources → del uv) without tripping the OutOfOrderTableProxy
    sequential-delete bug. File reparses cleanly afterwards and the
    user's other ``[tool.*]`` sections survive.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT + SCATTERED_CANONICAL_TAIL)
    report = tc.remove_patch(p)
    assert report.action == "removed"
    after = p.read_text(encoding="utf-8")
    # cu130 block gone.
    assert "pytorch-cu130" not in after
    assert "[[tool.uv.index]]" not in after
    # User's other sections survive.
    assert "[tool.ruff]" in after
    assert "[tool.ruff.lint]" in after
    assert "[tool.pytest.ini_options]" in after
    # File still parses.
    tomlkit.parse(after)


def test_scattered_tool_uv_apply_then_remove_round_trip(tmp_path: Path) -> None:
    """Apply → remove on a scattered MISSING pyproject leaves a
    semantically-equivalent project (modulo the cu130 block).
    """
    p = tmp_path / "pyproject.toml"
    _write(p, SCATTERED_PROJECT)
    orig = tomlkit.parse(SCATTERED_PROJECT).unwrap()
    tc.apply_patch(p)
    tc.remove_patch(p)
    final = tomlkit.parse(p.read_text(encoding="utf-8")).unwrap()
    # All non-uv tool.* sections preserved with identical content.
    assert final["project"] == orig["project"]
    assert final["tool"]["ruff"] == orig["tool"]["ruff"]
    assert final["tool"]["pytest"] == orig["tool"]["pytest"]
    assert final["tool"]["coverage"] == orig["tool"]["coverage"]


def test_top_level_split_tool_proxy(tmp_path: Path) -> None:
    """When ``[tool.X]`` and ``[tool.Y]`` sections sandwich a non-tool
    section, ``doc.get("tool")`` itself becomes ``OutOfOrderTableProxy``
    (not just ``tool.uv``). Detection and apply must still work.
    """
    p = tmp_path / "pyproject.toml"
    content = (
        '[project]\nname = "demo"\n'
        "\n[tool.uv]\noverride-dependencies = []\n"
        "\n[other]\nx = 1\n"
        "\n[tool.ruff]\nline-length = 120\n"
    )
    _write(p, content)
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    report = tc.apply_patch(p)
    assert report.action == "applied", report.conflicts
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


# ---------------------------------------------------------------------------
# has_direct_torch_dep (#83 finding 4)
#
# uv silently ignores [tool.uv.sources] for purely-transitive deps.
# The helper must detect torch in any of the three idiomatic surfaces.
# ---------------------------------------------------------------------------


def test_has_direct_torch_dep_in_project_dependencies(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["requests", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[project].dependencies"


def test_has_direct_torch_dep_in_dependency_groups(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[dependency-groups]\n"
        'dev = ["pytest", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[dependency-groups].dev"


def test_has_direct_torch_dep_in_optional_dependencies(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[project.optional-dependencies]\n"
        'gpu = ["torch>=2.4", "triton"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[project.optional-dependencies].gpu"


def test_has_direct_torch_dep_absent(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["requests", "numpy"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is False
    assert location == ""


def test_ensure_direct_torch_dep_adds_project_dependency(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["vaultspec-rag"]\n',
    )

    report = tc.ensure_direct_torch_dep(p)

    assert report.action == "applied"
    assert report.location == "[project].dependencies"
    after = p.read_text(encoding="utf-8")
    assert '"torch>=2.4"' in after
    assert "managed-torch-direct-dependency = true" in after
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[project].dependencies"


def test_ensure_direct_torch_dep_is_noop_when_present(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["vaultspec-rag", "torch>=2.4"]\n',
    )
    before = p.read_bytes()

    report = tc.ensure_direct_torch_dep(p)

    assert report.action == "already"
    assert report.location == "[project].dependencies"
    assert p.read_bytes() == before
    assert "managed-torch-direct-dependency" not in p.read_text(encoding="utf-8")


def test_remove_managed_direct_torch_dep_removes_only_owned_entry(
    tmp_path: Path,
) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["vaultspec-rag"]\n',
    )
    tc.ensure_direct_torch_dep(p)

    report = tc.remove_managed_direct_torch_dep(p)

    assert report.action == "removed"
    after = p.read_text(encoding="utf-8")
    assert '"torch>=2.4"' not in after
    assert "managed-torch-direct-dependency" not in after


def test_remove_managed_direct_torch_dep_preserves_user_entry(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["vaultspec-rag", "torch>=2.4"]\n',
    )
    before = p.read_bytes()

    report = tc.remove_managed_direct_torch_dep(p)

    assert report.action == "skipped"
    assert p.read_bytes() == before


def test_has_direct_torch_dep_no_project_file(tmp_path: Path) -> None:
    """Missing pyproject yields ``(False, "")`` - not an exception."""
    found, location = tc.has_direct_torch_dep(tmp_path / "missing.toml")
    assert found is False
    assert location == ""


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("torch", True),
        ("torch>=2.4", True),
        ("torch >= 2.4", True),
        ("torch[cuda]>=2.4", True),
        ("torch == 2.11.0+cu130", True),
        ("torch ; sys_platform == 'linux'", True),
        ("torch @ https://download.pytorch.org/whl/cu130/torch-2.11.0.whl", True),
        ("torch (>=2.4)", True),  # PEP 508 parenthesised version specifier
        ("Torch", True),  # PEP 503 case-insensitive normalisation
        ("TORCH>=2.4", True),
        ("torchvision", False),  # prefix match must not fire
        ("torchaudio>=1.0", False),
        ("requests", False),
        ("numpy>=2.0", False),
        ("", False),
        ("not a valid PEP 508 string @!", False),  # InvalidRequirement → False
    ],
)
def test_is_torch_requirement_predicate(entry: str, expected: bool) -> None:
    """``has_direct_torch_dep`` delegates name extraction to
    :class:`packaging.requirements.Requirement`. Each case pins one
    parsing trap (extras, markers, URL form, parentheses,
    case-insensitive PEP 503 normalisation, prefix collisions like
    ``torchvision``, malformed input).
    """
    # Access the private helper directly; behaviour is part of the
    # module's contract because ``has_direct_torch_dep`` delegates.
    assert tc._is_torch_requirement(entry) is expected


def test_is_torch_requirement_rejects_non_strings() -> None:
    """tomlkit can yield non-string entries (e.g. nested tables for
    PEP 508 dict-form deps in some tooling). Predicate must be total.
    """
    assert tc._is_torch_requirement(None) is False
    assert tc._is_torch_requirement(42) is False
    assert tc._is_torch_requirement({"name": "torch"}) is False


# ---------------------------------------------------------------------------
# Edge-case TOML shapes (rolling audit findings)
# ---------------------------------------------------------------------------


def test_apply_on_empty_pyproject(tmp_path: Path) -> None:
    """An empty (zero-byte) pyproject.toml still parses to an empty
    document. Apply must materialise the full ``[tool.uv]`` hierarchy
    without crashing on missing parents.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, "")
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    report = tc.apply_patch(p)
    assert report.action == "applied"
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_apply_on_pyproject_with_only_tool_uv(tmp_path: Path) -> None:
    """Pyproject that is just ``[tool.uv]`` with no project section.
    Less common but legal - apply must not assume ``[project]`` exists.
    """
    p = tmp_path / "pyproject.toml"
    _write(p, "[tool.uv]\noverride-dependencies = []\n")
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    assert tc.apply_patch(p).action == "applied"
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_apply_preserves_blank_lines_between_sections(tmp_path: Path) -> None:
    """Blank lines and section ordering survive the patch."""
    p = tmp_path / "pyproject.toml"
    content = (
        '[project]\nname = "demo"\n\n\n'  # extra blank lines
        "[tool.ruff]\nline-length = 120\n\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    )
    _write(p, content)
    tc.apply_patch(p)
    after = p.read_text(encoding="utf-8")
    # Order preserved.
    assert after.find("[tool.ruff]") < after.find("[tool.pytest.ini_options]")


def test_remove_preserves_user_overrides_in_tool_uv(tmp_path: Path) -> None:
    """When the user has their own keys in ``[tool.uv]`` (e.g.
    ``override-dependencies``), removal must drop only our entries
    and keep their content intact, with no orphaned empty section.
    """
    p = tmp_path / "pyproject.toml"
    content = (
        PROJECT_ONLY + "\n[tool.uv]\n"
        'override-dependencies = ["urllib3<3"]\n'
        "\n[[tool.uv.index]]\n"
        'name = "pytorch-cu130"\n'
        'url = "https://download.pytorch.org/whl/cu130"\n'
        "explicit = true\n"
        "\n[tool.uv.sources]\n"
        "torch = [\n"
        '    {index = "pytorch-cu130", '
        "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"},\n"
        "]\n"
    )
    _write(p, content)
    tc.remove_patch(p)
    after = p.read_text(encoding="utf-8")
    assert "[tool.uv]" in after
    assert "override-dependencies" in after
    assert '"urllib3<3"' in after
    assert "pytorch-cu130" not in after
    tomlkit.parse(after)


def test_has_direct_torch_dep_multi_group_optional_dependencies(tmp_path: Path) -> None:
    """TEST-05 regression: when ``[project.optional-dependencies]``
    has multiple groups and torch lives in the SECOND group (not the
    first), the iteration must keep going. A future refactor that
    early-returned on first group would silently miss this.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[project.optional-dependencies]\n"
        'gpu = ["triton"]\n'
        'cuda = ["torch>=2.4", "tensorboard"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[project.optional-dependencies].cuda"


def test_has_direct_torch_dep_multi_group_dependency_groups(tmp_path: Path) -> None:
    """TEST-05 regression: same shape for PEP 735 ``[dependency-groups]``."""
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[dependency-groups]\n"
        'lint = ["ruff"]\n'
        'gpu = ["triton", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[dependency-groups].gpu"


def test_apply_scattered_pyproject_reparses_canonical(tmp_path: Path) -> None:
    """TEST-06 regression: ``apply_patch`` against a scattered
    ``[tool.uv.*]`` shape must produce TOML that re-parses cleanly
    AND lands canonical cu130 keys at the documented dotted paths.
    The existing scattered test relies on ``detect_state`` returning
    CANONICAL - which transitively re-parses, but a future refactor
    that moved the reparse-guard out of ``apply_patch`` could pass
    those tests while emitting subtly broken TOML. Pin the contract.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        'dependencies = ["vaultspec-rag", "torch>=2.4"]\n'
        "\n[tool.uv]\noverride-dependencies = []\n"
        "\n[tool.ruff]\nline-length = 120\n"
        "\n[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n',
    )
    rep = tc.apply_patch(p)
    assert rep.action == "applied"
    after = p.read_text(encoding="utf-8")
    # Re-parse the post-apply bytes directly, then assert cu130 keys
    # land at the documented dotted paths.
    parsed = tomlkit.parse(after).unwrap()
    indices = parsed["tool"]["uv"]["index"]
    assert any(
        e.get("name") == "pytorch-cu130"
        and e.get("url") == "https://download.pytorch.org/whl/cu130"
        and e.get("explicit") is True
        for e in indices
    )
    sources = parsed["tool"]["uv"]["sources"]["torch"]
    assert any(
        e.get("index") == "pytorch-cu130"
        and e.get("marker") == "sys_platform == 'linux' or sys_platform == 'win32'"
        for e in sources
    )


def test_apply_inline_array_index_conflict_message(tmp_path: Path) -> None:
    """TOML-03 regression: when the user wrote ``index = [{...}]`` (inline-
    array dotted-key form), the conflict message must describe the
    actual shape (an inline array), not say "single table". Distinct
    error text guides the user toward the right fix.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[tool.uv]\n"
        "index = [{name = 'foo', url = 'https://example.com/simple'}]\n",
    )
    assert tc.detect_state(p) == tc.TorchConfigState.CUSTOMISED
    rep = tc.apply_patch(p)
    assert rep.action == "conflict"
    # Message must mention "inline array" - not "single table".
    assert any("inline array" in c for c in rep.conflicts), rep.conflicts
    assert not any("single table" in c for c in rep.conflicts), rep.conflicts


def test_apply_appended_index_block_has_trailing_blank_line(tmp_path: Path) -> None:
    """TOML-04 regression: when apply appends to an existing
    ``[[tool.uv.index]]`` AoT and the consumer file has more
    top-level sections after it, the new block must carry a trailing
    blank line. Without that, the ``explicit = true`` line lands
    flush against the next section header - readable TOML but a
    noisy git diff.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\ndependencies = ["torch>=2.4"]\n'
        "\n[[tool.uv.index]]\n"
        'name = "pypi-mirror"\n'
        'url = "https://example.com/simple"\n'
        "explicit = false\n"
        "\n[tool.something]\n"
        'foo = "bar"\n',
    )
    tc.apply_patch(p)
    out = p.read_text(encoding="utf-8")
    # The appended cu130 block must NOT collapse into the following
    # ``[tool.something]`` header.
    assert "explicit = true\n[tool.something]" not in out, out


def test_remove_orphan_canonical_index_only(tmp_path: Path) -> None:
    """TOML-02 regression: a half-applied state with only the
    canonical ``[[tool.uv.index]]`` (no source pin) used to classify
    as CUSTOMISED and uninstall left the orphan rag-named entry
    behind. Now uninstall recognises it as half-applied and removes it.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[[tool.uv.index]]\n"
        'name = "pytorch-cu130"\n'
        'url = "https://download.pytorch.org/whl/cu130"\n'
        "explicit = true\n",
    )
    rep = tc.remove_patch(p)
    assert rep.action == "removed"
    after = p.read_text(encoding="utf-8")
    assert "pytorch-cu130" not in after
    tomlkit.parse(after)


def test_remove_orphan_canonical_source_only(tmp_path: Path) -> None:
    """Symmetric pair of the index-only orphan: when only the source
    pin is present (no canonical index), uninstall must remove it.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[tool.uv.sources]\n"
        'torch = [{index = "pytorch-cu130", '
        "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"}]\n",
    )
    rep = tc.remove_patch(p)
    assert rep.action == "removed"
    after = p.read_text(encoding="utf-8")
    assert "pytorch-cu130" not in after


def test_apply_with_existing_user_index(tmp_path: Path) -> None:
    """User has their own ``[[tool.uv.index]]`` entry. Apply must
    *append* to the existing AoT, not replace it.
    """
    p = tmp_path / "pyproject.toml"
    content = (
        PROJECT_ONLY + "\n[[tool.uv.index]]\n"
        'name = "private"\n'
        'url = "https://private.example.com/simple"\n'
    )
    _write(p, content)
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    tc.apply_patch(p)
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL
    after = p.read_text(encoding="utf-8")
    # Both indices present.
    assert "pytorch-cu130" in after
    assert "private" in after
    # And we didn't accidentally add a second cu130 entry.
    assert after.count("pytorch-cu130") == 2  # name + source.index reference


# ---------------------------------------------------------------------------
# Round 2 - real-world shapes (#83 follow-up audit)
# ---------------------------------------------------------------------------


def test_load_strips_utf8_bom(tmp_path: Path) -> None:
    """REAL-01 regression: a leading UTF-8 BOM (saved by Notepad / VS
    Code "UTF-8 with BOM" / Windows git with certain ``core.autocrlf``)
    used to crash ``tomlkit.parse`` with "Empty key at line 1". The
    fix uses ``utf-8-sig`` so the BOM is transparently stripped.
    """
    p = tmp_path / "pyproject.toml"
    p.write_bytes(b"\xef\xbb\xbf" + b'[project]\nname = "bom"\nversion = "0.1.0"\n')
    # Detect must not raise and must classify normally.
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    # Apply must succeed and produce a canonical file.
    rep = tc.apply_patch(p)
    assert rep.action == "applied"
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL


def test_apply_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """REAL-02 regression: a Windows pyproject with CRLF line endings
    used to be rewritten as LF on the very first install, causing a
    git diff to show every existing line as changed. The fix sniffs
    CR-bytes pre-parse and re-encodes after ``tomlkit.dumps``.
    """
    p = tmp_path / "pyproject.toml"
    p.write_bytes(
        b'[project]\r\nname = "crlf"\r\nversion = "0.1.0"\r\ndependencies = []\r\n'
    )
    crlf_before = p.read_bytes().count(b"\r\n")
    assert crlf_before == 4
    tc.apply_patch(p)
    crlf_after = p.read_bytes().count(b"\r\n")
    # Every original CRLF still present (and more added by the patch).
    assert crlf_after >= crlf_before
    # Sanity: no bare LF lurking in what should be CRLF-only output.
    raw = p.read_bytes()
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
    assert bare_lf == 0, f"bare LF count={bare_lf}; expected 0 in CRLF file"


def test_remove_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """Round-trip CRLF preservation: write CRLF, apply, remove -
    the file must end up with CRLF line endings throughout (not the
    LF tomlkit emits by default).
    """
    p = tmp_path / "pyproject.toml"
    p.write_bytes(
        b'[project]\r\nname = "crlf"\r\nversion = "0.1.0"\r\ndependencies = []\r\n'
    )
    tc.apply_patch(p)
    tc.remove_patch(p)
    raw = p.read_bytes()
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
    assert bare_lf == 0, raw


def test_apply_lf_file_stays_lf(tmp_path: Path) -> None:
    """Negative pair: a pure-LF file must NOT gain CRLF after apply.
    The sniff-and-restore logic must default to LF when no CRLF was
    present on disk.
    """
    p = tmp_path / "pyproject.toml"
    p.write_bytes(b'[project]\nname = "lf"\nversion = "0.1.0"\n')
    tc.apply_patch(p)
    raw = p.read_bytes()
    assert b"\r\n" not in raw, raw


def test_apply_remove_round_trip_byte_equal(tmp_path: Path) -> None:
    """BEHAV-01 regression: the ADR's symmetric-mirror promise
    requires apply → remove to leave the file *byte-identical* to its
    pre-apply content. Prior to the trailing-newline preservation in
    ``_match_trailing_newline`` the round-trip appended a stray LF.
    """
    p = tmp_path / "pyproject.toml"
    body = (
        b"[project]\n"
        b'name = "rt"\n'
        b'version = "0.0.1"\n'
        b'requires-python = ">=3.13"\n'
        b'dependencies = ["torch>=2.4"]\n'
    )
    p.write_bytes(body)
    sha_before = hashlib.sha256(p.read_bytes()).hexdigest()
    tc.apply_patch(p)
    tc.remove_patch(p)
    sha_after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha_after == sha_before, (
        f"round-trip not byte-equal: before={sha_before}, after={sha_after}; "
        f"diff={p.read_bytes()[len(body) :]!r}"
    )


def test_apply_remove_round_trip_byte_equal_no_trailing_newline(
    tmp_path: Path,
) -> None:
    """A pyproject without a final LF (less common but legal) must
    also round-trip byte-equal. Pins the second branch of
    ``_match_trailing_newline`` (zero trailing newlines).
    """
    p = tmp_path / "pyproject.toml"
    # No trailing newline.
    body = b'[project]\nname = "rt"\nversion = "0.0.1"\n'
    p.write_bytes(body.rstrip(b"\n"))
    sha_before = hashlib.sha256(p.read_bytes()).hexdigest()
    tc.apply_patch(p)
    tc.remove_patch(p)
    sha_after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha_after == sha_before


def test_apply_remove_round_trip_byte_equal_double_trailing_newline(
    tmp_path: Path,
) -> None:
    """Some POSIX projects end pyproject.toml with two trailing LFs
    (file ends with a blank line). Round-trip must preserve that.
    """
    p = tmp_path / "pyproject.toml"
    body = b'[project]\nname = "rt"\nversion = "0.0.1"\n\n'
    p.write_bytes(body)
    sha_before = hashlib.sha256(p.read_bytes()).hexdigest()
    tc.apply_patch(p)
    tc.remove_patch(p)
    sha_after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha_after == sha_before


def test_has_direct_torch_dep_in_poetry_dependencies(tmp_path: Path) -> None:
    """REAL-03: Poetry's ``[tool.poetry.dependencies]`` is
    ``Mapping[name → spec]``, not a list. The detector must see
    ``torch = "^2.4"`` as a direct dep.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[tool.poetry]\n"
        'name = "demo"\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'torch = "^2.4"\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.poetry.dependencies]"


def test_has_direct_torch_dep_in_poetry_group(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[tool.poetry]\n"
        'name = "demo"\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        "\n"
        "[tool.poetry.group.gpu.dependencies]\n"
        'torch = "^2.4"\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.poetry.group.gpu.dependencies]"


def test_has_direct_torch_dep_in_poetry_legacy_dev_dependencies(
    tmp_path: Path,
) -> None:
    """Pre-1.2 Poetry expressed dev deps as
    ``[tool.poetry.dev-dependencies]``. Poetry 1.2+ moved them under
    ``[tool.poetry.group.dev.dependencies]`` but the legacy section
    is still produced by older ``poetry add`` invocations and still
    on countless deployed pyprojects. The detector must find torch
    in the legacy section so users on those projects don't get the
    misleading "not a direct dep" warning.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[tool.poetry]\n"
        'name = "demo"\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        "\n"
        "[tool.poetry.dev-dependencies]\n"
        'pytest = "*"\n'
        'torch = "^2.4"\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.poetry.dev-dependencies]"


def test_has_direct_torch_dep_in_pdm_dev_dependencies(tmp_path: Path) -> None:
    """PDM's ``[tool.pdm.dev-dependencies]`` is the same
    ``Mapping[group → list[str]]`` shape as PEP 735.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[project]\n"
        'name = "demo"\n'
        'dependencies = ["vaultspec-rag"]\n'
        "\n"
        "[tool.pdm.dev-dependencies]\n"
        'test = ["pytest", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.pdm.dev-dependencies].test"


def test_has_direct_torch_dep_in_hatch_env_dependencies_list(tmp_path: Path) -> None:
    """Gemini round-6 finding: Hatch's
    ``[tool.hatch.envs.<env>] dependencies = [...]`` (list of PEP 508
    strings) is the most common Hatch dev-dep surface.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[tool.hatch.envs.default]\n"
        'dependencies = ["pytest", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.hatch.envs.default].dependencies"


def test_has_direct_torch_dep_in_hatch_env_extra_dependencies(tmp_path: Path) -> None:
    """Hatch ``extra-dependencies`` is a sibling key to
    ``dependencies`` and just as common in env definitions.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[tool.hatch.envs.test]\n"
        'extra-dependencies = ["torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.hatch.envs.test].extra-dependencies"


def test_has_direct_torch_dep_in_hatch_env_dependencies_table(tmp_path: Path) -> None:
    """The table form ``[tool.hatch.envs.<env>.dependencies] torch =
    "^2.4"`` is less common but still legal Hatch config - and
    conventional in projects migrated from Poetry.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        '[project]\nname = "demo"\n'
        "\n[tool.hatch.envs.gpu.dependencies]\n"
        'torch = "^2.4"\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.hatch.envs.gpu.dependencies]"


def test_has_direct_torch_dep_in_uv_dev_dependencies(tmp_path: Path) -> None:
    """uv's pre-PEP-735 ``[tool.uv].dev-dependencies`` (still common)."""
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[project]\n"
        'name = "demo"\n'
        'dependencies = ["vaultspec-rag"]\n'
        "\n"
        "[tool.uv]\n"
        'dev-dependencies = ["pytest", "torch>=2.4"]\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is True
    assert location == "[tool.uv].dev-dependencies"


def test_has_direct_torch_dep_poetry_without_torch_returns_false(
    tmp_path: Path,
) -> None:
    """Negative pair to the Poetry tests: a Poetry project without
    torch must still classify as no-direct-dep.
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[tool.poetry]\n"
        'name = "demo"\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'numpy = "*"\n',
    )
    found, location = tc.has_direct_torch_dep(p)
    assert found is False
    assert location == ""


def test_apply_on_inline_sources_form(tmp_path: Path) -> None:
    """Gemini round-2 finding: ``sources = { torch = [...] }`` inline-
    form previously classified as MISSING via the inline-aware detector
    but then crashed in ``_ensure_torch_source`` with TypeError. The
    fix accepts ``InlineTable`` symmetrically across detect/apply/remove.

    Construct a state where the inline form exists but does NOT contain
    a canonical torch entry, so apply has to mutate. (When the inline
    form already contains a canonical entry, detect returns CANONICAL
    and apply short-circuits.)
    """
    p = tmp_path / "pyproject.toml"
    _write(
        p,
        "[project]\n"
        'name = "demo"\n'
        "\n"
        "[tool.uv]\n"
        "sources = { numpy = { workspace = true } }\n",
    )
    # Detect: MISSING (cu130 not present).
    assert tc.detect_state(p) == tc.TorchConfigState.MISSING
    # Apply must NOT raise TypeError.
    rep = tc.apply_patch(p)
    assert rep.action == "applied", rep.conflicts
    # File must reparse and reach CANONICAL.
    assert tc.detect_state(p) == tc.TorchConfigState.CANONICAL
