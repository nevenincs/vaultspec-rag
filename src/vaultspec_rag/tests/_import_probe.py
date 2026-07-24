"""Shared runner for the fresh-interpreter import guards.

Several rules in this project are about what a module must NOT drag in: the
chunk worker must not reach torch, storage maintenance must not reach the CLI
lifecycle, the error taxonomy must reach neither, and the stdio watchdog must
reach neither torch nor mcp. Each is checked the same way, and the way is the
load-bearing part - so it lives here once rather than being restated per guard.
"""

from __future__ import annotations

import subprocess
import sys

__all__ = ["assert_fresh_import_excludes", "import_probe_source"]


def import_probe_source(
    *modules: str,
    forbidden: tuple[str, ...] = ("torch",),
    setup: str = "",
) -> str:
    """Build probe source that imports *modules* and forbids *forbidden*.

    The scan is the part worth centralising: a guard that matched only the
    exact name would miss ``torch.nn`` and report clean on an import chain that
    had loaded half the library, so every forbidden name is matched as a package
    prefix too. Building it here means a new guard cannot get that subtly wrong
    by retyping it.

    Args:
        modules: Dotted module names the child imports, in order.
        forbidden: Names that must be absent from the child's ``sys.modules``,
            matched exactly or as a package prefix.
        setup: Optional source run before the imports, for a probe that needs
            the environment arranged first.

    Returns:
        Source for :func:`assert_fresh_import_excludes`.
    """
    imports = "".join(f"import {name}\n" for name in modules)
    return (
        "import sys\n"
        f"{setup}"
        f"{imports}"
        f"forbidden = {forbidden!r}\n"
        "found = sorted(\n"
        "    m\n"
        "    for m in sys.modules\n"
        "    if any(m == f or m.startswith(f + '.') for f in forbidden)\n"
        ")\n"
        "assert not found, found\n"
    )


def assert_fresh_import_excludes(script: str) -> None:
    """Run one import probe in a fresh interpreter and require it to pass.

    The probe MUST run out-of-process. This interpreter's ``sys.modules`` is
    polluted by every test that ran before it, so an in-process check would
    happily pass on a module some earlier test had already imported - a green
    result that proves nothing, which is the exact false confidence these
    guards exist to prevent. Reusing this runner is what keeps that property
    from being lost the next time a guard is added by copying a neighbour.

    Args:
        script: Source for the child interpreter. It imports the modules under
            test, collects the forbidden names it finds in ``sys.modules``, and
            asserts that collection is empty, so a violation exits non-zero and
            names the offending modules on stderr.
    """
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    # stderr carries the child's AssertionError, whose payload is the list of
    # forbidden modules that loaded - the failure names the offender rather
    # than reporting only a bad exit status.
    assert proc.returncode == 0, proc.stderr
