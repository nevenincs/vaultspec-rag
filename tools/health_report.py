"""Aggregate code-health report for ``src/vaultspec_rag``.

Prints one readable report covering every health dimension, grouping the worst
offenders per dimension. ALWAYS exits 0 — this is the measurement instrument
for the remediation campaign, not a gate. Gates live in:

- ``[tool.complexipy]``         (cognitive complexity, baseline-calibrated)
- ``[tool.pylint]``             (module length + class shape, baseline-calibrated)
- ``[tool.ruff.lint]``          (function-size limits, at upstream defaults)
- ``ty`` / ``basedpyright``     (type checking, gating)

Every gate is configured declaratively in ``pyproject.toml`` and invoked
directly by a ``just lint`` recipe. This module is the one place that
composes them, and it exists to rank offenders across dimensions — not to
re-implement any threshold, which would let the report and the gate disagree.
Thresholds this report names are therefore READ from pyproject.toml rather
than restated in a string literal, which is how three of them went stale.

Dimensions reported here:

1. Cyclomatic complexity   (radon ``cc`` — worst blocks)
2. Cognitive complexity    (complexipy — worst functions)
3. Function-size limits    (ruff PLR091x/PLR1702 vs upstream DEFAULTS)
4. Module length           (physical LOC — longest modules)
5. Maintainability index   (radon ``mi`` — lowest-ranked modules)
6. Strict type checking    (basedpyright strict — report-only)

radon is used through its Python API (``radon.complexity`` /
``radon.metrics``) rather than its CLI: the CLI feeds every ``[tool.*]`` table
of pyproject.toml into a ``%``-interpolating configparser and crashes on the
pytest log formats. The API path has no config discovery.

Usage:
    uv run python tools/health_report.py [--top N] [--fast]

``--fast`` skips the basedpyright section (it is the slowest by far).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

from complexipy import file_complexity
from radon.complexity import cc_rank, cc_visit
from radon.metrics import mi_rank, mi_visit
from rich.console import Console
from rich.markup import escape
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "vaultspec_rag"

COGNITIVE_REPORT_FLOOR = 10  # report functions above this, whatever the gate is

console = Console()


def _gate_limit(table: str, key: str) -> int:
    """Read one numeric gate threshold out of pyproject.toml.

    Read rather than restated. Every threshold this report names went stale
    the first time its gate was ratcheted: it announced a cognitive ceiling of
    25 against a configured 20, a module ceiling of 3400 against 3000, and a
    ``[tool.ruff.lint.pylint]`` baseline table that had been deleted in favour
    of upstream defaults. A label nobody can trust is worse than no label.
    """
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for segment in table.split("."):
        config = config[segment]
    return int(config[key])


def _python_files() -> list[Path]:
    return [
        path
        for path in sorted(PACKAGE_DIR.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _section(title: str, mode: str) -> None:
    """Rule off one dimension, naming the gate that owns it.

    Both arguments are escaped: a mode line names its gate's pyproject table,
    and rich reads a bare ``[tool.complexipy]`` as a style tag and drops it,
    so the label silently lost the very thing it was there to point at.
    """
    console.rule(f"[bold]{escape(title)}[/bold]  [dim]({escape(mode)})[/dim]")


def report_cyclomatic(top: int) -> None:
    _section(
        "Cyclomatic complexity (radon cc)",
        "gated by xenon at absolute<=C modules<=C average<=A",
    )
    blocks: list[tuple[int, str, str]] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for block in cc_visit(source):
            blocks.append((block.complexity, block.name, _rel(path)))
    blocks.sort(reverse=True)

    table = Table(show_header=True, header_style="bold")
    table.add_column("CC", justify="right")
    table.add_column("Grade")
    table.add_column("Block")
    table.add_column("Module")
    for complexity, name, module in blocks[:top]:
        table.add_row(str(complexity), cc_rank(complexity), name, module)
    console.print(table)


def report_cognitive(top: int) -> None:
    """Rank the worst cognitive-complexity functions across the whole tree.

    The gate in ``[tool.complexipy]`` measures production only; this reports
    the test tree alongside it, because the two populations differ enough that
    collapsing them hides which one a hotspot belongs to.
    """
    _section(
        "Cognitive complexity (complexipy)",
        "production gated at "
        f"{_gate_limit('tool.complexipy', 'max-complexity-allowed')} via "
        f"[tool.complexipy]; reporting > {COGNITIVE_REPORT_FLOOR} "
        "across the whole tree",
    )
    findings: list[tuple[int, str, str]] = []
    for path in _python_files():
        scope = "test" if "tests" in path.parts else "prod"
        for function in file_complexity(str(path)).functions:
            if function.complexity > COGNITIVE_REPORT_FLOOR:
                findings.append(
                    (
                        function.complexity,
                        scope,
                        f"{_rel(path)}:{function.line_start} {function.name}",
                    )
                )
    findings.sort(reverse=True)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Cognitive", justify="right")
    table.add_column("Scope")
    table.add_column("Module:line Function")
    for value, scope, location in findings[:top]:
        table.add_row(str(value), scope, location)
    console.print(table)


def report_function_limits(top: int) -> None:
    """Rank functions against ruff's UPSTREAM PLR091x limits, not the gate's.

    The limits are forced below rather than inherited from ``[tool.ruff]``.
    Today that changes nothing - the loosened override table was deleted and
    the gate runs these rules at upstream defaults - but pinning them here
    keeps the ranking honest if an override table is ever reintroduced.
    """
    _section(
        "Function-size limits (ruff PLR091x / PLR1702 vs upstream defaults)",
        "PLR0911/0912/0913/0915 gated at upstream defaults by `just lint "
        "python`; PLR1702 by `just lint nesting`",
    )
    defaults = {
        "lint.pylint.max-args": 5,
        "lint.pylint.max-returns": 6,
        "lint.pylint.max-branches": 12,
        "lint.pylint.max-statements": 50,
        "lint.pylint.max-nested-blocks": 5,
    }
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "src",
        "--select",
        "PLR0911,PLR0912,PLR0913,PLR0915,PLR1702",
        "--preview",
        "--output-format",
        "json",
        "--exit-zero",
    ]
    for key, value in defaults.items():
        cmd.extend(["--config", f"{key}={value}"])
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    diagnostics = json.loads(result.stdout or "[]")

    value_pattern = re.compile(r"\((\d+) > \d+\)")
    findings: list[tuple[int, str, str, str]] = []
    counts: Counter[str] = Counter()
    for item in diagnostics:
        counts[item["code"]] += 1
        match = value_pattern.search(item["message"])
        value = int(match.group(1)) if match else 0
        module = Path(item["filename"]).resolve()
        location = f"{_rel(module)}:{item['location']['row']}"
        findings.append((value, item["code"], item["message"], location))
    findings.sort(reverse=True)

    summary = ", ".join(f"{code}={count}" for code, count in sorted(counts.items()))
    console.print(f"violations vs upstream defaults: {summary or 'none'}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Rule")
    table.add_column("Message")
    table.add_column("Module:line")
    for value, code, message, location in findings[:top]:
        table.add_row(str(value), code, message, location)
    console.print(table)


def report_module_length(top: int) -> None:
    _section(
        "Module length (physical LOC)",
        "gated by pylint C0302 via [tool.pylint.format] "
        f"(ceiling {_gate_limit('tool.pylint.format', 'max-module-lines')})",
    )
    lengths: list[tuple[int, str]] = []
    for path in _python_files():
        with path.open("rb") as handle:
            lengths.append((sum(1 for _ in handle), _rel(path)))
    lengths.sort(reverse=True)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Lines", justify="right")
    table.add_column("Module")
    for line_count, module in lengths[:top]:
        table.add_row(str(line_count), module)
    console.print(table)


def report_maintainability(top: int) -> None:
    _section(
        "Maintainability index (radon mi)",
        "report-only (informational ranking, lower is worse)",
    )
    scores: list[tuple[float, str]] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        scores.append((mi_visit(source, multi=True), _rel(path)))
    scores.sort()

    table = Table(show_header=True, header_style="bold")
    table.add_column("MI", justify="right")
    table.add_column("Rank")
    table.add_column("Module")
    for score, module in scores[:top]:
        table.add_row(f"{score:.2f}", mi_rank(score), module)
    console.print(table)


def report_strict_types(top: int) -> None:
    _section(
        "Strict type checking (basedpyright strict)",
        "report-only until the remediation campaign; ty remains the gate",
    )
    executable = shutil.which("basedpyright")
    if executable is None:
        console.print(
            "[yellow]basedpyright not found on PATH — run "
            "`uv sync --locked --group dev`[/yellow]"
        )
        return
    result = subprocess.run(
        [executable, "--outputjson"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        console.print("[red]basedpyright produced no parseable output[/red]")
        console.print(result.stderr[:2000])
        return

    summary = payload.get("summary", {})
    console.print(
        f"files analyzed: {summary.get('filesAnalyzed', '?')}  "
        f"errors: {summary.get('errorCount', '?')}  "
        f"warnings: {summary.get('warningCount', '?')}"
    )
    per_file: Counter[str] = Counter()
    for diagnostic in payload.get("generalDiagnostics", []):
        if diagnostic.get("severity") == "error":
            per_file[diagnostic.get("file", "?")] += 1

    table = Table(show_header=True, header_style="bold")
    table.add_column("Errors", justify="right")
    table.add_column("Module")
    for file_name, count in per_file.most_common(top):
        module = Path(file_name)
        label = _rel(module) if module.is_absolute() else file_name
        table.add_row(str(count), label)
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="worst offenders to list per dimension (default 10)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the basedpyright section (slowest dimension)",
    )
    args = parser.parse_args()

    console.print(
        "[bold]vaultspec-rag code-health report[/bold] "
        "[dim](measurement only — always exits 0)[/dim]"
    )
    report_cyclomatic(args.top)
    report_cognitive(args.top)
    report_function_limits(args.top)
    report_module_length(args.top)
    report_maintainability(args.top)
    if args.fast:
        console.print("[dim]strict-type section skipped (--fast)[/dim]")
    else:
        report_strict_types(args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
