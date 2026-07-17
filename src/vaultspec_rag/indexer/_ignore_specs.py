"""Ignore-spec collection and compilation for the codebase indexer.

Pure functions that gather the hardcoded, ``.gitignore``, and
``.vaultragignore`` exclusion patterns for a project root and compile them
into ``pathspec`` matchers. Split out of ``_codebase_indexer`` so the scan's
ignore handling lives apart from the GPU chunk/embed pipeline; the
``CodebaseIndexer`` methods delegate here unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    import pathspec

logger = logging.getLogger(__name__)


def collect_gitignore_patterns(root_dir: pathlib.Path) -> list[str]:
    """Collect the hardcoded and ``.gitignore``-sourced exclusion patterns.

    Walks all ``.gitignore`` files in the project tree (the single tree
    walk on any index run), prefixing each pattern by the file's relative
    directory so nested patterns resolve from the project root. Returns the
    raw pattern list so both the compiled spec and the membership epoch can
    be built from one traversal.
    """
    from ..config import get_config

    cfg = get_config()
    patterns: list[str] = [
        # Always exclude these directories.
        ".venv/",
        ".git/",
        ".vault/",
        ".vaultspec/",
        "node_modules/",
        "__pycache__/",
        # Agent worktree clones duplicate the real source verbatim;
        # indexing them floods results with identical-score duplicates.
        ".claude/worktrees/",
        f"{cfg.data_dir}/",
    ]
    for gitignore in root_dir.rglob(".gitignore"):
        try:
            lines = gitignore.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.debug("gitignore %s unreadable; skipping: %s", gitignore, exc)
            continue
        rel_dir = gitignore.parent.relative_to(root_dir)
        process_gitignore_lines(lines, rel_dir, patterns)
    return patterns


def process_gitignore_lines(
    lines: list[str],
    rel_dir: pathlib.Path,
    patterns: list[str],
) -> None:
    rel_dir_str = str(rel_dir)
    prefix = rel_dir_str.replace(chr(92), "/")
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if rel_dir_str == ".":
            patterns.append(stripped)
        else:
            if stripped.startswith("!"):
                # Negation must stay at the start: !subdir/pattern
                inner = stripped[1:].lstrip("/")
                patterns.append(f"!{prefix}/{inner}")
            else:
                patterns.append(f"{prefix}/{stripped.lstrip('/')}")


def collect_vaultragignore_patterns(root_dir: pathlib.Path) -> list[str]:
    """Collect the root ``.vaultragignore`` patterns (excluding ``--exclude``).

    CLI ``--exclude`` entries are deliberately omitted: they are ephemeral
    and non-persisting, so folding them into the membership epoch would make
    it thrash between an ad-hoc CLI run and the resident service.
    """
    patterns: list[str] = []
    ignore_file = root_dir / ".vaultragignore"
    if ignore_file.is_file():
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
            patterns.extend(
                line.strip()
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            )
        except OSError as exc:
            logger.debug(
                ".vaultragignore at %s unreadable; using --exclude only: %s",
                ignore_file,
                exc,
            )
    return patterns


def build_vaultragignore_spec(
    root_dir: pathlib.Path,
    extra_excludes: list[str],
) -> pathspec.GitIgnoreSpec | None:
    """Build a pathspec from ``.vaultragignore`` and CLI ``--exclude`` patterns.

    Reads patterns from the ``.vaultragignore`` file at the project
    root (if it exists) and merges any ``extra_excludes`` passed via
    the constructor.  Returns ``None`` when no patterns are present.

    Returns:
        A compiled ``GitIgnoreSpec``, or ``None`` if there are no
        patterns to apply.
    """
    import pathspec

    patterns = [*collect_vaultragignore_patterns(root_dir), *extra_excludes]
    if not patterns:
        return None
    return pathspec.GitIgnoreSpec.from_lines(patterns)
