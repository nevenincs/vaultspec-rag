"""Ignore-spec collection and compilation for the codebase indexer.

Pure functions that gather the hardcoded, ``.gitignore``, and
``.vaultragignore`` exclusion patterns for a project root and compile them
into ``pathspec`` matchers. Split out of ``_codebase_indexer`` so the scan's
ignore handling lives apart from the GPU chunk/embed pipeline; the
``CodebaseIndexer`` methods delegate here unchanged.
"""

from __future__ import annotations

import logging
import os
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
    fixed_patterns: list[str] = [
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
    patterns: list[str] = []
    import pathspec

    fixed_spec = pathspec.GitIgnoreSpec.from_lines(fixed_patterns)
    root_str = str(root_dir)
    for dirpath, dirs, files in os.walk(root_dir, topdown=True, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
        dirs.sort()
        dirs[:] = [
            dirname
            for dirname in dirs
            if not fixed_spec.match_file(
                f"{dirname}/" if rel_dir == "." else f"{rel_dir}/{dirname}/"
            )
        ]
        if ".gitignore" not in files:
            continue
        gitignore = root_dir / (
            ".gitignore" if rel_dir == "." else f"{rel_dir}/.gitignore"
        )
        try:
            lines = gitignore.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.debug("gitignore %s unreadable; skipping: %s", gitignore, exc)
            continue
        process_gitignore_lines(lines, gitignore.parent.relative_to(root_dir), patterns)
    # Project-authored negations must not reopen directories declared above as
    # always excluded. Keeping the fixed rules last makes that invariant true
    # both for this pruned discovery walk and the final production scan spec.
    return [*patterns, *fixed_patterns]


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
