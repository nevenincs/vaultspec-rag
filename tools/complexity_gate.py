"""Baseline-calibrated complexity gate for ``src/vaultspec_rag``.

Two checks behind a single exit code:

1. Cognitive complexity — ``flake8-cognitive-complexity`` (rule ``CCR001``).
2. Cyclomatic complexity — ``xenon`` (wraps radon; fails past a letter grade).
3. Nesting depth — ruff ``PLR1702`` (preview-only, so it is gated here with a
   scoped ``--select PLR1702 --preview`` run instead of in the main ruff
   config, where global preview mode would change stable-rule behavior).

Thresholds are BASELINE-CALIBRATED (captured 2026-06-10): each sits exactly at
the current worst offender, so the gate is green today and can only be
ratcheted DOWN by the remediation campaign. Never raise them.

Baseline (2026-06-10):

- worst cognitive complexity: 20  (tests/test_mcp_import_isolation.py)
- worst cyclomatic block:     C (15)  (cli/_render.py:_render_install_report)
- worst module grade:         C  (cli/_service_info.py)
- repository average grade:   A
- worst nesting depth:        6  (indexer/_streaming.py; ruff default is 5)

Why xenon runs with ``cwd=src``: radon's CLI feeds every ``[tool.*]`` table of
the discovered ``pyproject.toml`` into a ``configparser`` with ``%``
interpolation enabled, and the ``%(asctime)s`` log formats under
``[tool.pytest.ini_options]`` crash it (``ValueError: invalid interpolation
syntax``). xenon imports ``radon.cli`` at startup, so it inherits the crash.
Running from ``src/`` keeps ``pyproject.toml`` out of radon's config discovery.

Usage:
    uv run python tools/complexity_gate.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

# --- Baseline-calibrated thresholds (ratchet DOWN only) ---------------------
COGNITIVE_MAX = 20  # baseline worst: 20; long-term target: 15
XENON_MAX_ABSOLUTE = "C"  # baseline worst block: C (15); target: B
XENON_MAX_MODULES = "C"  # baseline worst module: C; target: B
XENON_MAX_AVERAGE = "A"  # baseline average: A; already at target


def _run(label: str, cmd: list[str], cwd: Path) -> int:
    print(f"[complexity-gate] {label}", flush=True)
    result = subprocess.run(cmd, cwd=cwd)
    verdict = "PASS" if result.returncode == 0 else "FAIL"
    print(f"[complexity-gate] {label}: {verdict}", flush=True)
    return result.returncode


def main() -> int:
    cognitive_rc = _run(
        f"cognitive complexity (CCR001 <= {COGNITIVE_MAX})",
        [
            sys.executable,
            "-m",
            "flake8",
            "--select=CCR",
            f"--max-cognitive-complexity={COGNITIVE_MAX}",
            "src",
        ],
        cwd=REPO_ROOT,
    )

    cyclomatic_rc = _run(
        "cyclomatic complexity (xenon: "
        f"absolute<={XENON_MAX_ABSOLUTE} modules<={XENON_MAX_MODULES} "
        f"average<={XENON_MAX_AVERAGE})",
        [
            sys.executable,
            "-m",
            "xenon",
            "vaultspec_rag",
            "--max-absolute",
            XENON_MAX_ABSOLUTE,
            "--max-modules",
            XENON_MAX_MODULES,
            "--max-average",
            XENON_MAX_AVERAGE,
        ],
        cwd=SRC_DIR,
    )
    if cyclomatic_rc != 0:
        print("[complexity-gate] offending blocks (radon cc, grade C and worse):")
        subprocess.run(
            [sys.executable, "-m", "radon", "cc", "vaultspec_rag", "-s", "-n", "C"],
            cwd=SRC_DIR,
        )

    # max-nested-blocks=6 comes from [tool.ruff.lint.pylint] in pyproject.toml.
    nesting_rc = _run(
        "nesting depth (ruff PLR1702 <= 6)",
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src",
            "--select",
            "PLR1702",
            "--preview",
        ],
        cwd=REPO_ROOT,
    )

    if cognitive_rc or cyclomatic_rc or nesting_rc:
        print("[complexity-gate] FAIL — see offenders above")
        return 1
    print("[complexity-gate] PASS — all complexity gates green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
