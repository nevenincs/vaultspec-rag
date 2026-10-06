"""Workspace resolution and bootstrap helpers for enrollment commands."""

from __future__ import annotations

from pathlib import Path

from vaultspec_core.config.workspace import (
    resolve_workspace,
)
from vaultspec_core.core.types import (
    init_paths,
)

from .._plain_directory import ensure_plain_directory, require_plain_parents
from .._workspace_layout import (
    VAULT_DATA_DIR,
    VAULT_DIR,
    WORKSPACE_DIR,
    workspace_directories,
)
from ..builtins import list_builtins

__all__ = [
    "_ensure_workspace_dirs",
    "_init_core_context",
    "_require_plain_workspace",
    "_resolve_target",
]


def _resolve_target(path: Path | None, *, bootstrap: bool) -> Path:
    """Resolve the install target to an absolute workspace path.

    When ``bootstrap`` is True, this pre-creates the bare minimum
    directories core's ``resolve_workspace`` requires (``target/``,
    ``.vault/``, ``.vaultspec/``). It does NOT call
    :func:`vaultspec_core.core.types.init_paths` - that's deferred to
    the ``sync_provider`` call site via :func:`_init_core_context`.

    Why deferred: ``init_paths`` materialises core's
    ``.vaultspec/providers.json`` manifest as a side effect, which a
    later ``vaultspec-core install`` interprets as "already
    installed" and refuses to proceed without ``--upgrade`` /
    ``--force``. That contradicts rag's companion-package contract
    (rag is independent of core; both should cohabit cleanly without
    one blocking the other). COHAB-01.

    When ``bootstrap`` is False (dry-run path), only the path itself
    is resolved and no filesystem mutation occurs.

    An existing ``.vault`` or ``.vaultspec`` that is a link is refused rather
    than accepted as already present: a directory link satisfies "exists" and
    would carry everything created beneath it outside the target.
    """
    target = (path or Path.cwd()).resolve()
    if not bootstrap:
        return target
    target.mkdir(parents=True, exist_ok=True)
    ensure_plain_directory(target, VAULT_DIR)
    ensure_plain_directory(target, WORKSPACE_DIR)
    return target


def _require_plain_workspace(target: Path) -> None:
    """Refuse a workspace whose directories are reached through a link.

    Install and uninstall build every path they write or remove by joining a
    name onto the target, so a linked ``.vault`` or ``.vaultspec`` - or a
    linked directory beneath one - carries those mutations outside the
    selected root. This covers every directory either verb works inside and
    holds for every run, whichever components it skips: skipping a component
    narrows what is written, not where a write may land.

    Raises:
        LinkedDirectoryError: A workspace directory is a link or not a
            directory.
    """
    reached = (
        VAULT_DATA_DIR,
        *(WORKSPACE_DIR / relative for relative in list_builtins()),
    )
    for relative in reached:
        require_plain_parents(target, target / relative)


def _init_core_context(target: Path) -> None:
    """Initialise core's runtime context just before a ``sync_provider``
    call. Scoped here (instead of in :func:`_resolve_target`) so the
    manifest write is paired 1:1 with an actual core API invocation -
    rag never seeds a manifest just for being instantiated. COHAB-01.
    """
    layout = resolve_workspace(target_override=target)
    init_paths(layout)


def _ensure_workspace_dirs(target: Path, *, dry_run: bool) -> list[str]:
    """Idempotently create the directories rag needs to operate.

    rag is fully self-sufficient: it never assumes core has already
    bootstrapped the workspace. The dirs created here are exactly the
    minimum rag's enrollment requires; core's ``install_run`` will
    create the same dirs (and more) without conflict.
    """
    needed = [target / relative for relative in workspace_directories()]
    created: list[str] = []
    for d in needed:
        require_plain_parents(target, d)
        if d.is_dir():
            continue
        if not dry_run:
            ensure_plain_directory(target, d.relative_to(target))
        created.append(str(d.relative_to(target)).replace("\\", "/"))
    return created
