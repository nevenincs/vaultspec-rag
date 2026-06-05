"""Workspace resolution and bootstrap helpers for enrollment commands."""

from __future__ import annotations

from pathlib import Path

from vaultspec_core.config.workspace import resolve_workspace
from vaultspec_core.core.types import init_paths


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
    """
    target = (path or Path.cwd()).resolve()
    if not bootstrap:
        return target
    target.mkdir(parents=True, exist_ok=True)
    (target / ".vault").mkdir(exist_ok=True)
    (target / ".vaultspec").mkdir(exist_ok=True)
    return target


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
    needed = [
        target / ".vault",
        target / ".vault" / "data",
        target / ".vaultspec",
        target / ".vaultspec" / "rules",
        target / ".vaultspec" / "rules" / "rules",
        target / ".vaultspec" / "rules" / "mcps",
    ]
    created: list[str] = []
    for d in needed:
        if d.is_dir():
            continue
        if not dry_run:
            d.mkdir(parents=True, exist_ok=True)
        created.append(str(d.relative_to(target)).replace("\\", "/"))
    return created
