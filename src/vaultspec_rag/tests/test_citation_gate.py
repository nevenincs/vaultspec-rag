"""Guard tests for the Code Stands Alone citation gate.

The gate is the mechanical half of the no-dev-metadata rule, and a gate that
returns clean on a live violation is worse than no gate: it converts "nobody
checked" into "the check passed". These tests therefore assert the gate can see
each shape it claims to catch, not merely that it runs.

Every case builds a throwaway source tree and scans that, so a shape can be
introduced and its detection asserted without ever mutating the checkout. The
final case is the only one pointed at the live tree, and it is a regression
guard on the tree rather than evidence about the gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATE_PATH = _REPO_ROOT / "tools" / "citation_gate.py"


def _load_gate() -> ModuleType:
    """Import the gate from ``tools/``, which is not an installed package."""
    spec = importlib.util.spec_from_file_location("_citation_gate", _GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load_gate()


def _slugs(findings: list[tuple[str, int, str, str]]) -> list[str]:
    return [slug for _rel, _line, slug, _text in findings]


def _texts(findings: list[tuple[str, int, str, str]]) -> list[str]:
    return [text for _rel, _line, _slug, text in findings]


def test_dated_stem_without_a_document_type_suffix_is_a_citation(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A bare dated stem is the form a document is actually cited by in prose.

    Requiring a trailing ``-adr``/``-plan`` segment let this whole shape through
    while the gate reported clean. Asserted on the exact slug and the exact
    matched text: several patterns share the failure message, so a looser
    assertion would pass on whichever one happened to fire.
    """
    source = tmp_path / "module.py"
    source.write_text(
        '"""Worker docstring.\n\n'
        "See ADR ``2026-06-02-index-perf-hardening`` for the rationale.\n"
        '"""\n',
        encoding="utf-8",
    )

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert "dated-vault-stem" in _slugs(findings)
    assert "2026-06-02-index-perf-hardening" in _texts(findings)


def test_dated_stem_is_reported_on_its_own_line_of_a_module_docstring(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The module docstring is the file's first statement, and it is scanned.

    The reported line must land on the offending line inside the docstring, not
    on the docstring's opening quote - a finding that points at line 1 of every
    module sends the reader to the wrong place.
    """
    source = tmp_path / "module.py"
    source.write_text(
        '"""Line one.\n\nLine three.\nSee ``2026-06-02-index-perf-hardening``.\n"""\n',
        encoding="utf-8",
    )

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert [(line, slug) for _rel, line, slug, _text in findings] == [
        (4, "dated-vault-stem")
    ]


@pytest.mark.parametrize(
    ("body", "label"),
    [
        ('class C:\n    """Doc 2026-06-02-index-perf-hardening."""\n', "class"),
        ('def f() -> None:\n    """Doc 2026-06-02-index-perf-hardening."""\n', "def"),
        (
            'async def f() -> None:\n    """Doc 2026-06-02-index-perf-hardening."""\n',
            "async def",
        ),
        ("# 2026-06-02-index-perf-hardening decided this\nx = 1\n", "comment"),
    ],
)
def test_every_prose_surface_is_scanned(
    gate: ModuleType, tmp_path: Path, body: str, label: str
) -> None:
    source = tmp_path / "module.py"
    source.write_text(body, encoding="utf-8")

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert "dated-vault-stem" in _slugs(findings), f"{label} prose was not scanned"


def test_a_vault_shaped_string_value_is_data_and_never_a_citation(
    gate: ModuleType, tmp_path: Path
) -> None:
    """Fixture filenames are values the indexer is tested against, not pointers.

    This is the carve-out the prose-only scan exists to make. If the gate ever
    starts matching string values, the corpus the indexer is tested against
    fails the gate wholesale.
    """
    source = tmp_path / "module.py"
    source.write_text(
        'FIXTURE = "2026-06-02-index-perf-hardening-adr.md"\n'
        'PATHS = ["adr/2026-06-02-index-perf-hardening.md"]\n',
        encoding="utf-8",
    )

    assert gate.scan_file(source, repo_root=tmp_path) == []


def test_a_plain_date_and_a_numeric_date_range_are_not_stems(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The stem tail must carry a letter, so a date alone stays legible in prose.

    Prose is allowed to say when something happened. Only a kebab feature tail
    turns a date into a document identifier.
    """
    source = tmp_path / "module.py"
    source.write_text(
        '"""Measured 2026-06-02, re-measured over 2026-06-02-2026-07-01."""\n',
        encoding="utf-8",
    )

    assert gate.scan_file(source, repo_root=tmp_path) == []


def test_the_tools_surface_gates_on_citations(gate: ModuleType, tmp_path: Path) -> None:
    """``tools/`` is tracked source and must fail the gate, not just leak-scan.

    It was walked for workstation-path leaks only, so a citation sitting in a
    tool was unreachable by the gate that exists to find it. Asserted through
    ``collect_findings`` because the miss was in which surfaces the walk visits,
    which no per-file scan can observe.
    """
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "helper.py").write_text(
        '"""Helper. See ``2026-06-02-index-perf-hardening``."""\n', encoding="utf-8"
    )

    active, _deferred, _leaks, _smells = gate.collect_findings(
        package, repo_root=tmp_path, tools_root=tools
    )

    assert [(rel, slug) for rel, _line, slug, _text in active] == [
        ("tools/helper.py", "dated-vault-stem")
    ]


def test_the_checkout_carries_no_active_citation_or_identity_leak(
    gate: ModuleType,
) -> None:
    """Regression guard on the tree, not evidence about the gate.

    The cases above are what establish the gate can go red; this one only
    asserts the live checkout is on the clean side of it.
    """
    active, _deferred, leaks, _smells = gate.collect_findings(
        _REPO_ROOT / "src" / "vaultspec_rag"
    )

    assert active == [], f"active development-record citation(s): {active}"
    assert leaks == [], f"workstation-identity path leak(s): {leaks}"
