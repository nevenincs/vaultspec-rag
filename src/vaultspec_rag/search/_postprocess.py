"""Result post-processing: locale dedup, chunk classification, nudges.

Pure functions and tuning constants that shape the final ranked list
after hybrid search and CrossEncoder rerank:

- :func:`_locale_variant_key` / :func:`_collapse_locale_variants`
  collapse near-tie locale-variant paths (e.g. ``locales/{en,es}.yml``)
  to a single canonical result.
- :func:`_classify_chunk_type` labels a path as ``prod`` / ``tests`` /
  ``docs`` for the ``--prefer`` score nudge.

All functions here are pure (no I/O, no realistic exception surface).
"""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ._models import SearchResult

__all__ = [
    "GLOB_FETCH_MULTIPLIER",
    "PREFER_CATEGORIES",
    "PREFER_SCORE_NUDGE",
    "_classify_chunk_type",
    "_collapse_locale_variants",
    "_locale_variant_key",
]

# When --include-path / --exclude-path are active the post-query
# fnmatch filter may discard the majority of candidates. Overfetch
# aggressively so top_k is still satisfied for common glob shapes.
# Module-level constant so it can be tuned later without changing
# the call site. See cli-path-glob ADR.
GLOB_FETCH_MULTIPLIER = 10

# Locale-variant dedup window. Two results whose paths share a
# locale stem AND whose scores are within this window collapse to
# the highest-scoring one. Tight enough that genuinely-different
# translations stay separate; loose enough that the same string in
# en/es/ca/hu collapses. See search-postprocess ADR.
_LOCALE_DEDUP_SCORE_WINDOW = 0.10

# --prefer prod/tests/docs score nudge magnitude. Roughly one
# rank-gap in a typical top-k - re-orders ties without making
# off-category results jump rank.
PREFER_SCORE_NUDGE = 0.05

# Path-extension/regex constants for locale detection.
_LOCALE_FILE_EXTS: frozenset[str] = frozenset(
    {
        "yml",
        "yaml",
        "json",
        "po",
        "properties",
        "ini",
        "toml",
    }
)
_LOCALE_CODE_RE = re.compile(r"^[a-z]{2}$")

# Chunk-type classifier. Order = precedence (tests > docs > prod).
# Implemented as segment / basename / extension checks instead of
# fnmatch globs because ``fnmatch`` lacks ``**`` and would require
# enumerating each tree depth explicitly.
_TESTS_DIR_NAMES: frozenset[str] = frozenset({"tests", "test", "spec", "__tests__"})
_TESTS_BASENAME_PATTERNS: tuple[str, ...] = ("test_*", "*_test.*", "*_spec.*")
_DOCS_DIR_NAMES: frozenset[str] = frozenset({"docs", "doc"})
_DOCS_BASENAME_PATTERNS: tuple[str, ...] = ("readme*", "changelog*")
_DOCS_FILE_EXTS: frozenset[str] = frozenset({"md", "rst", "adoc"})
PREFER_CATEGORIES: tuple[str, ...] = ("prod", "tests", "docs")


def _locale_variant_key(path: str) -> str | None:
    """Return a stem shared across locale variants, ``None`` otherwise.

    Recognised shapes:

    - ``<dir>/<lang>.<ext>``       - e.g. ``locales/en.yml``
    - ``<dir>/<lang>/<name>.<ext>`` - e.g. ``i18n/en/messages.po``
    - ``<name>.<lang>.<ext>``      - e.g. ``messages.en.po``

    where ``<ext>`` is in ``_LOCALE_FILE_EXTS`` and ``<lang>`` is a
    2-letter ISO 639 code (matched via ``_LOCALE_CODE_RE``).

    Two results with the same returned key are candidate locale
    variants of each other and collapse during dedup when their
    scores are within ``_LOCALE_DEDUP_SCORE_WINDOW``.

    Pure function - no I/O, no realistic exception surface.
    """
    parts = path.rsplit(".", 1)
    if len(parts) != 2:
        return None
    stem, ext = parts
    if ext.lower() not in _LOCALE_FILE_EXTS:
        return None
    segments = stem.split("/")
    if not segments:
        return None
    last = segments[-1]
    # Shape A: ``.../<lang>.<ext>`` - e.g. ``locales/en.yml``.
    # Key is the parent directory.
    if _LOCALE_CODE_RE.match(last):
        return "/".join(segments[:-1]) + f"/*.{ext}"
    # Shape B: ``.../<lang>/<name>.<ext>`` - e.g. ``i18n/en/messages.po``.
    # Key is the grandparent directory plus the filename.
    if len(segments) >= 2 and _LOCALE_CODE_RE.match(segments[-2]):
        return "/".join(segments[:-2]) + f"/*/{last}.{ext}"
    # Shape C: ``<name>.<lang>.<ext>`` - e.g. ``messages.en.po``.
    name_parts = last.rsplit(".", 1)
    if len(name_parts) == 2 and _LOCALE_CODE_RE.match(name_parts[1]):
        return "/".join(segments[:-1]) + f"/{name_parts[0]}.*.{ext}"
    return None


def _classify_chunk_type(path: str) -> Literal["prod", "tests", "docs"]:
    """Classify a project-relative ``path`` for --prefer score nudging.

    Precedence: ``tests`` > ``docs`` > ``prod``. A file under
    ``tests/docs/`` is reported as ``tests`` because the user's
    intent when running tests is the dominant signal.

    Pure function - no I/O, no realistic exception surface.
    """
    segments = path.split("/")
    basename = segments[-1].lower() if segments else ""

    if any(seg in _TESTS_DIR_NAMES for seg in segments[:-1]):
        return "tests"
    if any(fnmatch.fnmatch(basename, pat) for pat in _TESTS_BASENAME_PATTERNS):
        return "tests"

    if any(seg in _DOCS_DIR_NAMES for seg in segments[:-1]):
        return "docs"
    if any(fnmatch.fnmatch(basename, pat) for pat in _DOCS_BASENAME_PATTERNS):
        return "docs"
    ext = basename.rsplit(".", 1)[-1] if "." in basename else ""
    if ext in _DOCS_FILE_EXTS:
        return "docs"

    return "prod"


def _group_locale_variants(results: list[SearchResult]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for index, result in enumerate(results):
        key = _locale_variant_key(result.path)
        if key is None:
            continue
        grouped.setdefault(key, []).append(index)
    return grouped


def _find_collapsed_variants(
    grouped: dict[str, list[int]], results: list[SearchResult]
) -> tuple[set[int], dict[int, list[str]]]:
    drop: set[int] = set()
    collapsed_variants: dict[int, list[str]] = {}
    for indices in grouped.values():
        if len(indices) < 2:
            continue
        # Highest-scoring entry wins. Stable sort on (-score,
        # original_index) keeps ranking deterministic for ties.
        ranked = sorted(
            indices,
            key=lambda idx: (-results[idx].score, idx),
        )
        winner = ranked[0]
        winner_score = results[winner].score
        collapsed_paths: list[str] = []
        for other in ranked[1:]:
            if winner_score - results[other].score <= _LOCALE_DEDUP_SCORE_WINDOW:
                drop.add(other)
                collapsed_paths.append(results[other].path)
        if collapsed_paths:
            collapsed_variants[winner] = collapsed_paths
    return drop, collapsed_variants


def _collapse_locale_variants(
    results: list[SearchResult],
) -> list[SearchResult]:
    """Collapse near-tie locale-variant paths to the highest scorer.

    Groups results by ``_locale_variant_key(result.path)`` -
    non-locale paths and singletons pass through unchanged. Within
    each group, the highest-scoring result is the canonical
    winner; lower-scoring results within
    ``_LOCALE_DEDUP_SCORE_WINDOW`` of the winner collapse into it
    (their paths are recorded for transparency). Results outside
    the window survive - they're treated as genuinely different
    content that happens to share a locale stem.

    Order preserved: the canonical result keeps the winner's
    original index in the input list so the overall ranking is
    not destabilised. Pure function; no I/O.
    """
    if not results:
        return results

    grouped = _group_locale_variants(results)
    if not grouped:
        return results

    drop, collapsed_variants = _find_collapsed_variants(grouped, results)
    if not drop:
        return results

    out: list[SearchResult] = []
    for index, result in enumerate(results):
        if index in drop:
            continue
        if index in collapsed_variants:
            # Annotate the surviving snippet so the consumer sees
            # which locale variants collapsed into this entry.
            variants = ", ".join(collapsed_variants[index])
            tag = f" [locale variants: {variants}]"
            result.snippet = (result.snippet + tag) if result.snippet else tag.lstrip()
        out.append(result)
    return out
