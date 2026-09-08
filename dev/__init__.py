"""The development harness: the `just` verbs and every instrument they drive.

Nothing here ships in the wheel.

:mod:`dev.toolchain` is the registry - it declares each verb and target, so the
justfile is a thin delegate and a target cannot exist without being declared.
:mod:`dev.runner` holds the process primitives both depend on, and imports only
the standard library, so the harness behaves identically on every platform.

This package replaced roughly 350 lines of backslash-joined PowerShell
``switch`` blocks in the justfile and the ``scripts/run-just-recipe.ps1`` shim
that executed them.
"""

from __future__ import annotations

import os
import sys

# Windows starts a Python process with its streams bound to the ANSI codepage
# (cp1252 on a stock installation), so ONE box-drawing character or accented
# identifier - in a tool's output, or in the command line this harness echoes
# before running it - raises UnicodeEncodeError and takes the recipe down with
# it. The failure belongs to Python, not the shell: it reproduces identically
# under `cmd` and under `pwsh`, so no choice of `set windows-shell` avoids it
# and the fix has to live here.
#
# Both halves are load bearing. Reconfiguring this process's own streams covers
# everything the harness itself prints; exporting PYTHONIOENCODING covers every
# Python child it spawns, which is most of the toolchain. An explicit value from
# the operator or a caller wins, so a deliberate override still works.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8")
