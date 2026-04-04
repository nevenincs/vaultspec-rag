"""Workspace layout resolution for vaultspec-rag.

Mirrors the logic from vaultspec core to ensure consistent directory detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "GitInfo",
    "LayoutMode",
    "WorkspaceError",
    "WorkspaceLayout",
    "discover_git",
    "resolve_workspace",
]


class LayoutMode(Enum):
    """How the layout was resolved."""

    STANDALONE = "standalone"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class GitInfo:
    """Discovered git repository metadata.

    Attributes:
        git_dir: Path to the .git directory or .gt container.
        repo_root: Root of the git repository.
        is_worktree: Whether this is a linked worktree.
        is_bare: Whether the repository is bare.
        worktree_root: Root of the worktree, if is_worktree is True.
        container_root: Root of the .gt container, if is_bare is True.
    """

    git_dir: Path
    repo_root: Path
    is_worktree: bool
    is_bare: bool
    worktree_root: Path | None
    container_root: Path | None


@dataclass(frozen=True)
class WorkspaceLayout:
    """Fully resolved, validated workspace paths.

    Attributes:
        target_dir: The root directory of the workspace.
        vault_dir: Path to the .vault directory within target_dir.
        vaultspec_dir: Path to the .vaultspec framework directory within target_dir.
        mode: How the layout was resolved (EXPLICIT or STANDALONE).
        git: Discovered git repository metadata, if any.
    """

    target_dir: Path
    vault_dir: Path
    vaultspec_dir: Path
    mode: LayoutMode
    git: GitInfo | None


def _strip_unc(path: Path) -> Path:
    """Strip Windows \\\\?\\ UNC prefix if present.

    Args:
        path: Path that may have a Windows UNC prefix.

    Returns:
        Path with the UNC prefix removed if it was present, otherwise unchanged.
    """
    s = str(path)
    if s.startswith("\\\\?\\"):
        return Path(s[4:])
    return path


def _parse_git_pointer(git_path: Path) -> Path | None:
    """Parse a .git file containing gitdir: <path>.

    Args:
        git_path: Path to a .git file (not directory).

    Returns:
        Resolved path to the actual git directory, or None if parsing fails.
    """
    try:
        content = git_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None

    if not content.startswith("gitdir:"):
        return None

    raw = content[len("gitdir:") :].strip()
    target = Path(raw)

    if not target.is_absolute():
        target = (git_path.parent / target).resolve()
    else:
        target = target.resolve()

    return _strip_unc(target)


def _walk_up_for_git(start: Path) -> tuple[Path, bool] | None:
    """Walk up from start looking for .git (file or directory).

    Args:
        start: Starting path from which to walk upward.

    Returns:
        Tuple of (git_path, is_file) where is_file indicates if .git is a file
        (worktree) or directory (normal repo), or None if no .git found.
    """
    current = start.resolve()
    current = _strip_unc(current)

    while True:
        dot_git = current / ".git"
        if dot_git.exists():
            return (dot_git, dot_git.is_file())

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def discover_git(start: Path) -> GitInfo | None:
    """Walk up from start to find and classify the git repository.

    Checks for .gt bare container first, then walks up to find .git directory
    or file, classifying it as a normal repository, linked worktree, or bare repo.

    Args:
        start: Starting path from which to walk upward.

    Returns:
        GitInfo object with repository metadata if found, otherwise None.
    """
    resolved_start = _strip_unc(start.resolve())

    # Check for .gt/ container
    current = resolved_start
    while True:
        gt = current / ".gt"
        if gt.is_dir():
            return GitInfo(
                git_dir=gt,
                repo_root=current,
                is_worktree=False,
                is_bare=True,
                worktree_root=None,
                container_root=current,
            )
        parent = current.parent
        if parent == current:
            break
        current = parent

    result = _walk_up_for_git(resolved_start)
    if result is None:
        return None

    dot_git, is_file = result

    if not is_file:
        return GitInfo(
            git_dir=dot_git,
            repo_root=dot_git.parent,
            is_worktree=False,
            is_bare=False,
            worktree_root=None,
            container_root=None,
        )

    real_git_dir = _parse_git_pointer(dot_git)
    if real_git_dir is None:
        return None

    worktree_root = dot_git.parent

    # Standard linked worktree detection
    if real_git_dir.parent.name == "worktrees":
        main_git_dir = real_git_dir.parent.parent
        return GitInfo(
            git_dir=real_git_dir,
            repo_root=main_git_dir.parent,
            is_worktree=True,
            is_bare=False,
            worktree_root=worktree_root,
            container_root=None,
        )

    return GitInfo(
        git_dir=real_git_dir,
        repo_root=worktree_root,
        is_worktree=True,
        is_bare=False,
        worktree_root=worktree_root,
        container_root=None,
    )


class WorkspaceError(Exception):
    """Raised when workspace layout validation fails."""


def _validate(layout: WorkspaceLayout) -> None:
    """Validate a resolved WorkspaceLayout.

    Args:
        layout: WorkspaceLayout to validate.

    Raises:
        WorkspaceError: If vaultspec_dir does not exist or target_dir is invalid.
    """
    if not layout.vaultspec_dir.is_dir():
        raise WorkspaceError(
            f"vaultspec_dir does not exist or is not a directory: "
            f"{layout.vaultspec_dir}\n"
            f"Ensure your --target directory contains a .vaultspec/ folder.",
        )

    if not layout.target_dir.exists():
        raise WorkspaceError(
            f"target_dir does not exist: {layout.target_dir}\n"
            f"Provide a valid directory via --target.",
        )


def resolve_workspace(
    *,
    target_override: Path | None = None,
    framework_dir_name: str = ".vaultspec",
    cwd: Path | None = None,
) -> WorkspaceLayout:
    """Resolve the complete workspace layout.

    Resolves workspace in EXPLICIT mode (if target_override is provided) or
    STANDALONE mode (via git detection or cwd fallback). Validates that the
    resolved layout contains required directories before returning.

    Args:
        target_override: Explicit target directory. If provided,
            uses EXPLICIT mode.
        framework_dir_name: Name of the framework directory
            within target (default: ``".vaultspec"``).
        cwd: Current working directory for git detection
            (default: ``Path.cwd()``).

    Returns:
        WorkspaceLayout with resolved and validated paths.

    Raises:
        WorkspaceError: If vaultspec_dir or target_dir validation fails.
    """
    effective_cwd = (cwd or Path.cwd()).resolve()
    effective_cwd = _strip_unc(effective_cwd)

    # EXPLICIT mode
    if target_override is not None:
        target_dir = target_override.resolve()
        target_dir = _strip_unc(target_dir)
        layout = WorkspaceLayout(
            target_dir=target_dir,
            vault_dir=target_dir / ".vault",
            vaultspec_dir=target_dir / framework_dir_name,
            mode=LayoutMode.EXPLICIT,
            git=discover_git(target_dir),
        )
        _validate(layout)
        return layout

    # git detection
    git = discover_git(effective_cwd)
    if git is not None:
        root = git.container_root if git.container_root is not None else git.repo_root
        root = _strip_unc(root)
        layout = WorkspaceLayout(
            target_dir=root,
            vault_dir=root / ".vault",
            vaultspec_dir=root / framework_dir_name,
            mode=LayoutMode.STANDALONE,
            git=git,
        )
        _validate(layout)
        return layout

    # fallback
    root = effective_cwd
    layout = WorkspaceLayout(
        target_dir=root,
        vault_dir=root / ".vault",
        vaultspec_dir=root / framework_dir_name,
        mode=LayoutMode.STANDALONE,
        git=None,
    )
    _validate(layout)
    return layout
