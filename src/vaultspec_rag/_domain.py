"""Single source of truth for classifying a path into a noise domain.

A code chunk's *domain* is a coarse, purely path-derived label used to filter
and rank search noise: ``prod`` is the production surface a caller usually
wants; the other labels name the recurring noise classes a large polyglot repo
accretes (tests, docs, locale tables, generated and vendored trees, and the
transient worktree clones that echo the real source verbatim).

This module is deliberately dependency-free - stdlib ``fnmatch``/``re`` only,
no project imports, no ``torch`` - so it is safe to import from the codebase
indexer's spawn-worker chain (``index-workers-stay-cpu-only``) and to call once
per chunk at index time. The same function backs the query-time fallback when a
chunk predates the ``domain`` payload, so the index-side and query-side labels
can never drift.

It supersedes the three-category ``_classify_chunk_type`` in the search
post-processing module, which now delegates here.
"""

from __future__ import annotations

import fnmatch
import re
from itertools import pairwise
from typing import Literal

__all__ = ["DOMAINS", "NOISE_DOMAINS", "Domain", "classify_domain"]

Domain = Literal["prod", "tests", "docs", "locale", "generated", "vendored", "worktree"]

# Declaration order is the public order (prod first); not the precedence order.
DOMAINS: tuple[Domain, ...] = (
    "prod",
    "tests",
    "docs",
    "locale",
    "generated",
    "vendored",
    "worktree",
)

# Every domain except the production surface. The default noise set the profile
# draws from; ``prod`` is never noise.
NOISE_DOMAINS: frozenset[Domain] = frozenset(DOMAINS) - {"prod"}

# Transient clone trees that duplicate the real source: agent worktrees under
# ``.claude/worktrees/`` and native git worktrees under ``.git/worktrees/``.
# Matched as a path-segment pair so an unrelated dir literally named
# ``worktrees`` elsewhere does not trip it.
_WORKTREE_PARENTS: frozenset[str] = frozenset({".claude", ".git"})
_WORKTREE_SEGMENT = "worktrees"

# Dependency / build output trees checked into or sitting beside the source.
_VENDOR_DIR_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        "vendor",
        "third_party",
        "thirdparty",
        ".venv",
        "venv",
        "site-packages",
        "bower_components",
        "dist",
        "build",
        ".tox",
        "eggs",
    }
)

# Machine-emitted trees and files.
_GENERATED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "generated",
        "__generated__",
        ".next",
        ".nuxt",
    }
)
_GENERATED_BASENAME_PATTERNS: tuple[str, ...] = (
    "*.min.js",
    "*.min.css",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.pb.go",
    "*.g.dart",
    "*.generated.*",
)

# Test trees and files (mirrors the prior ``_classify_chunk_type`` rules).
_TESTS_DIR_NAMES: frozenset[str] = frozenset({"tests", "test", "spec", "__tests__"})
_TESTS_BASENAME_PATTERNS: tuple[str, ...] = (
    "test_*",
    "*_test.*",
    "*_spec.*",
    "conftest.py",
)

# Localisation tables.
_LOCALE_DIR_NAMES: frozenset[str] = frozenset(
    {"locales", "locale", "i18n", "translations", "lang"}
)
_LOCALE_FILE_EXTS: frozenset[str] = frozenset(
    {"yml", "yaml", "json", "po", "properties", "ini", "toml"}
)
_LANG_CODE_RE = re.compile(r"^[a-z]{2}$")

# Documentation.
_DOCS_DIR_NAMES: frozenset[str] = frozenset({"docs", "doc"})
_DOCS_BASENAME_PATTERNS: tuple[str, ...] = ("readme*", "changelog*", "license*")
_DOCS_FILE_EXTS: frozenset[str] = frozenset({"md", "rst", "adoc"})


def _is_worktree(segments: list[str]) -> bool:
    for parent, child in pairwise(segments):
        if parent in _WORKTREE_PARENTS and child == _WORKTREE_SEGMENT:
            return True
    return False


def _is_locale(dir_segments: list[str], basename: str) -> bool:
    if any(seg in _LOCALE_DIR_NAMES for seg in dir_segments):
        return True
    # A ``<lang>.<ext>`` or ``<name>.<lang>.<ext>`` file with a known i18n
    # extension - e.g. ``en.yml`` or ``messages.en.po``.
    parts = basename.rsplit(".", 1)
    if len(parts) != 2:
        return False
    stem, ext = parts
    if ext.lower() not in _LOCALE_FILE_EXTS:
        return False
    if _LANG_CODE_RE.match(stem.lower()):
        return True
    tail = stem.rsplit(".", 1)
    return len(tail) == 2 and bool(_LANG_CODE_RE.match(tail[1].lower()))


def _is_docs(dir_segments: list[str], basename: str) -> bool:
    if any(seg in _DOCS_DIR_NAMES for seg in dir_segments):
        return True
    if any(fnmatch.fnmatch(basename, pat) for pat in _DOCS_BASENAME_PATTERNS):
        return True
    ext = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    return ext in _DOCS_FILE_EXTS


def classify_domain(path: str) -> Domain:
    """Classify a project-relative ``path`` into one coarse noise domain.

    Pure and path-only - no I/O, no realistic exception surface. Separators are
    normalised so a Windows-style path classifies identically to its POSIX form.

    Precedence (first match wins): ``worktree`` (a clone tree is noise whatever
    it contains) > ``vendored`` > ``generated`` > ``tests`` > ``locale`` >
    ``docs`` > ``prod`` (the default). The ordering puts the most
    duplicate/derivative trees first so an inner ``src/`` inside a worktree
    clone is still classed ``worktree``, not ``prod``.
    """
    normalised = path.replace("\\", "/").strip("/")
    segments = normalised.split("/") if normalised else []
    dir_segments = segments[:-1]
    basename = segments[-1].lower() if segments else ""

    if _is_worktree(segments):
        return "worktree"
    if any(seg in _VENDOR_DIR_NAMES for seg in dir_segments):
        return "vendored"
    if any(seg in _GENERATED_DIR_NAMES for seg in dir_segments):
        return "generated"
    if any(fnmatch.fnmatch(basename, pat) for pat in _GENERATED_BASENAME_PATTERNS):
        return "generated"
    if any(seg in _TESTS_DIR_NAMES for seg in dir_segments):
        return "tests"
    if any(fnmatch.fnmatch(basename, pat) for pat in _TESTS_BASENAME_PATTERNS):
        return "tests"
    if _is_locale(dir_segments, basename):
        return "locale"
    if _is_docs(dir_segments, basename):
        return "docs"
    return "prod"
