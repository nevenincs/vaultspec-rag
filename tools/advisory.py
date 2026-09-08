#!/usr/bin/env python
"""Run an advisory scanner: findings do not gate, a broken scanner does.

An advisory audit dimension reports leads to confirm rather than verdicts, so a
finding must not fail the build. The way that was expressed here -- appending
``; exit 0`` to the scanner's command line -- also swallowed every OTHER reason
the scanner could exit non-zero: a bad config, an unparsable file, a tool that
is not installed at all. A dimension that cannot report its own breakage is
indistinguishable from one that is clean, which is the failure mode the
repository's own audit commentary warns about.

This runner keeps the advisory contract and drops the swallow. It maps the exit
codes a scanner uses to say "I found something" onto success, and propagates
every other non-zero status unchanged, so a crashed or absent scanner still
fails the recipe that invoked it.

Usage::

    python tools/advisory.py --finding-exit 1 -- bandit -c pyproject.toml -r src

``--finding-exit`` may be repeated; ``vulture`` uses 3, most others use 1.
"""

from __future__ import annotations

import subprocess
import sys


def parse_args(argv: list[str]) -> tuple[frozenset[int], list[str]]:
    """Split ``argv`` into the finding exit codes and the command to run.

    Args:
        argv: Arguments after the program name.

    Returns:
        The exit codes that mean "findings reported", and the command argv.

    Raises:
        ValueError: If the ``--`` separator or the command is missing.
    """
    finding_exits: set[int] = set()
    index = 0
    while index < len(argv) and argv[index] != "--":
        if argv[index] != "--finding-exit":
            raise ValueError(f"unexpected argument {argv[index]!r} before '--'")
        finding_exits.add(int(argv[index + 1]))
        index += 2
    if index >= len(argv):
        raise ValueError("missing '--' separator before the command")
    command = argv[index + 1 :]
    if not command:
        raise ValueError("no command given after '--'")
    return frozenset(finding_exits or {1}), command


def verdict(returncode: int, finding_exits: frozenset[int]) -> int:
    """Return the runner's exit code for a scanner that exited ``returncode``."""
    if returncode == 0 or returncode in finding_exits:
        return 0
    return returncode


def main(argv: list[str] | None = None) -> int:
    """Run the scanner and return the advisory verdict."""
    try:
        finding_exits, command = parse_args(sys.argv[1:] if argv is None else argv)
    except (ValueError, IndexError) as error:
        print(f"advisory: {error}", file=sys.stderr)
        return 2

    try:
        proc = subprocess.run(command, check=False)
    except OSError as error:
        # An absent scanner is a broken dimension, never a clean one.
        print(f"advisory: cannot run {command[0]!r}: {error}", file=sys.stderr)
        return 127

    status = verdict(proc.returncode, finding_exits)
    if status == 0 and proc.returncode != 0:
        print(
            f"advisory: {command[0]} reported findings (exit {proc.returncode}); "
            "this dimension is advisory and does not gate.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
