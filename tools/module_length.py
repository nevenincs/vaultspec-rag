"""Module length (LOC) report for ``src/vaultspec_rag``.

Ruff has no module-length rule, so this script provides the signal. It is
REPORT-ONLY by default (always exits 0): the current baseline far exceeds any
sane threshold and the remediation campaign owns the fix.

Baseline (2026-06-10):

- longest module overall:  tests/test_cli.py            2225 lines
- longest non-test module: indexer/_codebase_indexer.py 1170 lines

Pass ``--gate`` to turn the threshold into a failing check once the ratchet
campaign starts (suggested first gate: 1200, then 800, settling at 500).

Usage:
    uv run python tools/module_length.py [--threshold N] [--top N] [--gate]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "vaultspec_rag"

DEFAULT_THRESHOLD = 1000
DEFAULT_TOP = 15


def collect_module_lengths(root: Path) -> list[tuple[int, Path]]:
    lengths: list[tuple[int, Path]] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        with path.open("rb") as handle:
            line_count = sum(1 for _ in handle)
        lengths.append((line_count, path))
    lengths.sort(key=lambda item: item[0], reverse=True)
    return lengths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"LOC threshold used to flag modules (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"how many of the longest modules to list (default {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="exit non-zero when any module exceeds the threshold",
    )
    args = parser.parse_args()

    lengths = collect_module_lengths(PACKAGE_DIR)
    offenders = [item for item in lengths if item[0] > args.threshold]

    mode = "GATE" if args.gate else "REPORT-ONLY"
    print(f"[module-length] {mode} — threshold {args.threshold} lines")
    print(f"[module-length] top {args.top} longest modules:")
    for line_count, path in lengths[: args.top]:
        rel = path.relative_to(REPO_ROOT).as_posix()
        marker = "  OVER" if line_count > args.threshold else ""
        print(f"  {line_count:>6}  {rel}{marker}")
    print(
        f"[module-length] {len(offenders)} of {len(lengths)} modules exceed "
        f"{args.threshold} lines"
    )

    if args.gate and offenders:
        print("[module-length] FAIL — modules above threshold")
        return 1
    if offenders and not args.gate:
        print("[module-length] findings recorded; report-only mode never fails")
    return 0


if __name__ == "__main__":
    sys.exit(main())
