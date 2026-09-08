"""The complexity gate and its advisory counterpart.

This is the one dimension whose behaviour is more than a command line, which is
why it is an instrument rather than a row in :mod:`dev.toolchain`. Two things
make it so:

* ``xenon`` resolves module names from the working directory, so it must run
  from ``src/``. The shell expressed that as ``Push-Location``/``Pop-Location``
  around the call.
* When the gate fails, ``radon`` re-runs to print WHICH functions breached it,
  and the gate's own exit code - not radon's - is what propagates. A shell
  pipeline gets this wrong by default, because the last command's status wins.

Splitting the gate from the audit is deliberate. The gate measures PRODUCTION
code; the audit measures the test tree and never fails. The worst scores in
this tree belong to guard tests that walk the AST of every module to prove a
structural invariant - branch count and nesting are what those tests ARE, so
gating them at a production threshold would price the guard out rather than
simplify it.
"""

from __future__ import annotations

import argparse

from dev.runner import UTF8, run

#: The shipped package, as a repository-root-relative path.
PACKAGE = "src/vaultspec_rag"

#: The package's import name, which is how xenon and radon address it once the
#: working directory is ``src/``.
MODULE = "vaultspec_rag"

#: Maintainability thresholds. These are xenon's own rank letters: no single
#: block worse than C, no module worse than C, and a project average of A.
XENON_LIMITS = (
    "--max-absolute",
    "C",
    "--max-modules",
    "C",
    "--max-average",
    "A",
)

#: The test tree, excluded from the production gate by xenon's own pattern
#: form. See the module docstring for why.
XENON_EXCLUDE = ("-e", f"{MODULE}/tests/*")


def _uv_run(*argv: str) -> list[str]:
    """Build an argument vector that runs a tool from the environment."""
    return ["uv", "run", "--no-sync", *argv]


def _advisory(finding_exit: int, *argv: str, from_src: bool = False) -> list[str]:
    """Wrap a scanner so its findings do not gate but its breakage does.

    Args:
        finding_exit: The status this scanner uses to mean "I found something".
        *argv: The scanner command line.
        from_src: True when the scanner runs with ``src/`` as the working
            directory, which the runner path has to reach back out of.

    Returns:
        The argument vector to execute.
    """
    runner = "../tools/advisory.py" if from_src else "tools/advisory.py"
    return _uv_run(
        "python",
        runner,
        "--finding-exit",
        str(finding_exit),
        "--",
        *argv,
    )


def gate() -> int:
    """Gate production complexity, explaining any breach before failing.

    Returns:
        The complexity tools' exit code. When xenon fails, radon runs to name
        the offending blocks, but XENON's status is what propagates - a
        diagnostic must never be able to turn a red gate green.
    """
    code = run(_uv_run("complexipy", PACKAGE), UTF8)
    if code != 0:
        return code

    xenon_code = run(_uv_run("xenon", MODULE, *XENON_LIMITS, *XENON_EXCLUDE), cwd="src")
    if xenon_code != 0:
        run(_uv_run("radon", "cc", MODULE, "-s", "-n", "C"), cwd="src")
    return xenon_code


def audit() -> int:
    """Report test-tree complexity; findings do not gate, breakage does.

    Both scanners run through ``tools/advisory.py``, which maps their own
    findings-exit-code onto success and propagates every other status. Simply
    returning 0 here would also swallow a bad config, an unparsable file, or a
    scanner that is not installed - making a dimension that has stopped running
    indistinguishable from a clean one.

    Returns:
        0 when both scanners ran and reported only findings, otherwise the
        first non-zero status that was not a findings code.
    """
    worst = run(_advisory(1, "complexipy", f"{PACKAGE}/tests", "--failed"), UTF8)
    code = run(_advisory(1, "xenon", MODULE, *XENON_LIMITS, from_src=True), cwd="src")
    return worst or code


MODES = {"gate": gate, "audit": audit}


def main(argv: list[str] | None = None) -> int:
    """Dispatch one complexity mode and return its exit code.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The exit code of the selected mode.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.complexity",
        description="Measure cyclomatic and cognitive complexity.",
    )
    parser.add_argument("mode", nargs="?", default="gate", choices=[*MODES])
    args = parser.parse_args(argv)
    return MODES[args.mode]()


if __name__ == "__main__":
    raise SystemExit(main())
