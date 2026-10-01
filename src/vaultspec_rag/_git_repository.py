"""Read-only Git repository-family identity shared by service and indexing."""

from __future__ import annotations

from pathlib import Path


def git_common_dir(root: Path) -> Path | None:
    """Resolve the shared Git directory without spawning a Git process.

    Unreadable or unrecognized layouts return no identity. This describes
    repository affinity and never grants indexing or storage authority.
    """
    marker = root / ".git"
    try:
        if marker.is_dir():
            return marker.resolve()
        if not marker.is_file():
            return None
        for line in marker.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("gitdir:"):
                continue
            gitdir = Path(line[len("gitdir:") :].strip())
            if not gitdir.is_absolute():
                gitdir = root / gitdir
            gitdir = gitdir.resolve()
            commondir_file = gitdir / "commondir"
            if commondir_file.is_file():
                common = Path(commondir_file.read_text(encoding="utf-8").strip())
                if not common.is_absolute():
                    common = gitdir / common
                return common.resolve()
            return gitdir
    except OSError:
        return None
    return None
