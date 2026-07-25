"""Module length (LOC) gate and report for ``src/vaultspec_rag``.

Ruff has no module-length rule, so this script provides the signal. It FAILS
by default: a module longer than :data:`ENFORCED_CEILING` exits non-zero. The
ceiling is a ratchet, not a target - it sits just above the longest module the
tree currently has, so length can never grow past where it already is, and
every extraction lowers the next rung.

:data:`RATCHET_TARGET` is where modules should end up. The distance between
the two is the outstanding work, and the census below records it rather than
leaving it implied by a single passing number.

Census (2026-07-25, 434 modules):

- longest module overall:  tests/integration/test_install.py  3398 lines
- longest non-test module: job_manager.py                     2990 lines

    over 3400:    0 modules   <- the enforced ceiling; the tree meets it
    over 3000:    1 module
    over 2000:    9 modules
    over 1200:   34 modules
    over 1000:   49 modules
    over  800:   63 modules
    over  500:  113 modules   <- the ratchet target

Lowering ``ENFORCED_CEILING`` is the ratchet: drop it to just above the new
longest module whenever an extraction lands, and refresh the census in the
same change so the remaining distance stays visible.

Usage:
    uv run python tools/module_length.py [--threshold N] [--top N]
                                         [--census] [--report-only]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "vaultspec_rag"

#: Longest module the tree is permitted to hold. Exceeding it fails the gate.
ENFORCED_CEILING = 3400

#: Length modules should settle at. Everything above it is outstanding work.
RATCHET_TARGET = 500

#: Rungs the census reports, so the shape of the remaining work is visible
#: rather than collapsed into one pass/fail bit.
CENSUS_RUNGS = (3400, 3000, 2000, 1200, 1000, 800, 500)

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


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _print_census(lengths: list[tuple[int, Path]], threshold: int) -> None:
    """Report how many modules sit above each rung of the ratchet."""
    print(f"[module-length] census over {len(lengths)} modules:")
    for rung in CENSUS_RUNGS:
        over = sum(1 for line_count, _ in lengths if line_count > rung)
        marker = ""
        if rung == threshold:
            marker = "  <- enforced ceiling"
        elif rung == RATCHET_TARGET:
            marker = "  <- ratchet target"
        print(f"    over {rung:>5}: {over:>4} modules{marker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=int,
        default=ENFORCED_CEILING,
        help=f"LOC ceiling enforced by the gate (default {ENFORCED_CEILING})",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"how many of the longest modules to list (default {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help=f"list every module longer than {RATCHET_TARGET} lines",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="report without failing, even when modules exceed the ceiling",
    )
    args = parser.parse_args()

    lengths = collect_module_lengths(PACKAGE_DIR)
    offenders = [item for item in lengths if item[0] > args.threshold]

    mode = "REPORT-ONLY" if args.report_only else "GATE"
    print(f"[module-length] {mode} - ceiling {args.threshold} lines")
    print(f"[module-length] top {args.top} longest modules:")
    for line_count, path in lengths[: args.top]:
        marker = "  OVER" if line_count > args.threshold else ""
        print(f"  {line_count:>6}  {_relative(path)}{marker}")

    _print_census(lengths, args.threshold)

    if args.census:
        outstanding = [item for item in lengths if item[0] > RATCHET_TARGET]
        print(
            f"[module-length] full census - {len(outstanding)} modules above "
            f"the {RATCHET_TARGET}-line target:"
        )
        for line_count, path in outstanding:
            print(f"  {line_count:>6}  {_relative(path)}")

    print(
        f"[module-length] {len(offenders)} of {len(lengths)} modules exceed "
        f"the {args.threshold}-line ceiling"
    )

    if offenders:
        for line_count, path in offenders:
            print(f"[module-length] OVER CEILING: {line_count} {_relative(path)}")
        if args.report_only:
            print("[module-length] report-only mode never fails")
            return 0
        print(
            "[module-length] FAIL - a module grew past the ceiling. Extract a "
            "collaborator, or raise the ceiling only with the census refreshed."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
