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
