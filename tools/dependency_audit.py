#!/usr/bin/env python
"""uv-native dependency vulnerability audit gate.

Wraps ``uv audit`` -- uv's native, preview-feature OSV scanner -- so the
supply-chain gate is uv-managed end to end and never shells out to pip.

The wrapper exists because the gate's verdict must not depend on a preview
tool's exit-code behaviour. ``uv audit`` shipped for a long stretch exiting
``0`` even when it printed advisories (vaultspec-core's copy of this gate
documents the same defect), and it is still a preview feature whose contract
can move again. This wrapper therefore derives the verdict from BOTH the exit
code and the reported summary, and fails closed:

* clean summary AND exit 0  -> pass
* anything else             -> fail

so a future uv that returns to exiting 0 on findings cannot silently un-gate
this repository. ``verdict`` is a pure function so that behaviour is covered by
a test rather than only by a live network run.

Suppressions belong here, each with a comment naming the advisory and why it is
tolerated. Prefer ``--ignore-until-fixed`` (self-expiring) over a bare
``--ignore``; ``IGNORED`` below is for advisories that have no upstream fix at
all.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Advisory IDs this gate tolerates. Every entry needs a comment naming the
#: advisory, why it cannot be fixed, and what would make it removable.
#: Deliberately empty: torch 2.13.0 resolved GHSA-rrmf-rvhw-rf47 (CVE-2025-3000)
#: and lifted the transitive setuptools pin past the PYSEC-2026-3447 fix.
IGNORED: frozenset[str] = frozenset()

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Summary lines uv prints when the locked tree carries no advisories.
_CLEAN_MARKERS = (
    "Found no known vulnerabilit",
    "Found 0 known vulnerabilit",
)


def verdict(output: str, returncode: int) -> int:
    """Return the gate's exit code for one ``uv audit`` run.

    Args:
        output: The combined stdout/stderr of the ``uv audit`` process.
        returncode: That process's exit status.

    Returns:
        ``0`` only when uv both exited cleanly and reported no advisories;
        ``1`` otherwise.
    """
    clean_summary = any(marker in output for marker in _CLEAN_MARKERS)
    if clean_summary and returncode == 0:
        return 0
    return 1


def explain(output: str, returncode: int) -> str:
    """Return the failure line for a non-passing run, for the operator."""
    if returncode == 0:
        return (
            "ERROR: uv audit exited 0 without reporting a clean tree. Treating "
            "this as a finding: a preview tool that reports advisories and "
            "exits 0 would otherwise leave this gate unable to fail."
        )
    if any(marker in output for marker in _CLEAN_MARKERS):
        return (
            f"ERROR: uv audit reported a clean tree but exited {returncode}; "
            "the audit itself failed to complete."
        )
    return "ERROR: uv audit reported vulnerability findings."


def main() -> int:
    """Run ``uv audit`` over the locked tree and return the gate's exit code."""
    argv = [
        "uv",
        "audit",
        "--locked",
        "--preview-features",
        "audit",
        *(arg for vid in sorted(IGNORED) for arg in ("--ignore", vid)),
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=_REPO_ROOT,
        )
    except OSError as error:
        # A missing or unrunnable `uv` is a broken gate, never a pass.
        print(f"ERROR: cannot run uv audit: {error}", file=sys.stderr)
        return 127

    output = proc.stdout + proc.stderr
    print(output, end="" if output.endswith("\n") else "\n")

    status = verdict(output, proc.returncode)
    if status != 0:
        print(explain(output, proc.returncode), file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
