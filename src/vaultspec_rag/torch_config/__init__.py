"""Detect, write, and remove the canonical cu130 torch block in a user's
``pyproject.toml``.

This package is the pure-logic layer for rag's ``install`` /
``uninstall`` torch-config step. It mirrors the per-resource module
pattern core follows for ``gitignore.py`` / ``gitattributes.py`` /
``mcps.py``: no Typer, no Rich, no prompts, no process side-effects
beyond a single atomic write.

Canonical block shape - see :func:`manual_snippet` for the exact
bytes rag emits (three module constants compose the shape).

The three module-level constants are the single source of truth for
that shape - apply and remove compare against them, and
``manual_snippet`` renders them verbatim. Symmetric apply/remove is
guaranteed by construction.

This module was split into a package (``torch_config/``) from a former
monolith: shared constants / enums / report
dataclasses in ``_constants``, TOML inspection + classification in
``_inspect``, mutation + the canonical-snippet builder in ``_mutate``,
direct-dep management in ``_direct_dep``, and install diagnosis in
``_diagnose``. Import each name from the module that defines it; this
package exports nothing itself.
"""
