"""Bounded repository inventory and service-owned watcher enrollment."""

from __future__ import annotations

from functools import partial
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync
from starlette.responses import JSONResponse

import vaultspec_rag.server as _server

from .._git_repository import git_common_dir
from .._store_models import root_collection_prefix
from ..concurrency import limiter_stats
from ..storage_manifest import ManifestEntry, classify_root, load_manifest, record_root
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..service import ServiceRegistry

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000


def inventory_limit(raw: str | None) -> int:
    try:
        value = int(raw) if raw is not None else _DEFAULT_LIMIT
    except ValueError:
        return _DEFAULT_LIMIT
    return min(_MAX_LIMIT, max(1, value))


def _watching_roots() -> set[Path]:
    with _server._watcher_lock:
        return set(_server._watcher_tasks)


def _linked_worktrees(common: Path, limit: int) -> tuple[set[Path], int, bool]:
    """Read Git's own registered worktree paths within a bounded window."""
    roots: set[Path] = set()
    directory = common / "worktrees"
    try:
        entries = list(islice(directory.iterdir(), limit + 1))
    except OSError:
        return roots, 0, False
    for entry in entries[:limit]:
        try:
            marker = Path((entry / "gitdir").read_text(encoding="utf-8").strip())
            if not marker.is_absolute():
                marker = entry / marker
            root = marker.resolve().parent
            if git_common_dir(root) == common:
                roots.add(root)
        except (OSError, ValueError):
            continue
    return roots, min(limit, len(entries)), len(entries) > limit


def _discover_families(roots: set[Path]) -> tuple[dict[Path, Path | None], bool]:
    """Expand known roots with Git's registered siblings under one read budget."""
    families: dict[Path, Path | None] = {}
    discovered: set[Path] = set()
    discovery_truncated = len(roots) > _MAX_LIMIT
    remaining = _MAX_LIMIT
    for known in sorted(roots)[:_MAX_LIMIT]:
        common = git_common_dir(known)
        families[known] = common
        if common is None or common in discovered:
            continue
        discovered.add(common)
        siblings, inspected, truncated = _linked_worktrees(common, remaining)
        remaining -= inspected
        if common.name == ".git" and git_common_dir(common.parent) == common:
            siblings.add(common.parent)
        roots.update(siblings)
        families.update(dict.fromkeys(siblings, common))
        discovery_truncated = discovery_truncated or truncated
    return families, discovery_truncated


def _selected_roots(
    roots: set[Path], families: dict[Path, Path | None], target: Path | None
) -> list[Path]:
    selected: list[Path] = []
    for path in sorted(roots):
        common = families.get(path)
        if (
            target is None
            or path == target
            or (
                common is not None and common.name == ".git" and common.parent == target
            )
        ):
            selected.append(path)
    return selected


def _repository_row(
    path: Path,
    common: Path | None,
    entry: ManifestEntry | None,
    slot: dict[str, Any] | None,
    watching: bool | None,
) -> dict[str, object]:
    repository_root = (
        common.parent if common is not None and common.name == ".git" else None
    )
    prefix = entry.prefix if entry is not None else root_collection_prefix(path)
    return {
        "root": str(path),
        "prefix": prefix,
        "enrolled": entry is not None,
        "status": classify_root(entry or ManifestEntry(prefix, str(path), "server")),
        "repository_root": str(repository_root) if repository_root else None,
        "git_common_dir": str(common) if common else None,
        "is_worktree": path != repository_root if repository_root is not None else None,
        "watching": watching,
        "resident": (
            {"ref_count": slot["ref_count"], "idle_seconds": slot["idle_seconds"]}
            if slot is not None
            else None
        ),
        "last_indexed": entry.last_indexed or None if entry is not None else None,
        "declared_collections": list(entry.collections) if entry else [],
    }


def repository_inventory(
    registry: ServiceRegistry | None, *, root: str | None, limit: int
) -> dict[str, object]:
    """Join existing manifest, slot, watcher and Git facts without opening stores."""
    entries = {Path(entry.root): entry for entry in load_manifest().values()}
    slots = (
        {Path(str(slot["root"])): slot for slot in registry.snapshot()}
        if registry is not None
        else {}
    )
    watching: set[Path] = _watching_roots() if registry is not None else set()
    roots = set(entries) | set(slots) | watching
    families, discovery_truncated = _discover_families(roots)
    target = Path(root).resolve() if root is not None else None
    selected = _selected_roots(roots, families, target)
    rows = [
        _repository_row(
            path,
            families[path] if path in families else git_common_dir(path),
            entries.get(path),
            slots.get(path),
            path in watching if registry is not None else None,
        )
        for path in selected[:limit]
    ]
    return {
        "repositories": rows,
        "returned": len(rows),
        "total": len(selected),
        "limit": limit,
        "truncated": len(selected) > limit,
        "discovery_truncated": discovery_truncated,
        "source": "live" if registry is not None else "persisted",
        "live_available": registry is not None,
        "seats": {
            "projects": {
                "used": len(slots),
                "total": registry.max_projects or None,
                "leases_held": sum(int(slot["ref_count"]) for slot in slots.values()),
            },
            **limiter_stats(),
        }
        if registry is not None
        else None,
    }


async def repositories_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    root = request.query_params.get("root")
    if root is not None and not root.strip():
        return JSONResponse(
            {
                "ok": False,
                "error": "bad_request",
                "message": "root must be a non-empty path.",
            },
            status_code=400,
        )
    if root is not None:
        try:
            root = str(Path(root).resolve())
        except (OSError, ValueError) as exc:
            return JSONResponse(
                {"ok": False, "error": "bad_request", "message": str(exc)},
                status_code=400,
            )
    result = await run_sync(
        partial(
            repository_inventory,
            get_request_runtime(request).registry,
            root=root,
            limit=inventory_limit(request.query_params.get("limit")),
        )
    )
    return JSONResponse(result)


async def enroll_repository_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        raw_payload: object = await request.json()
        if not isinstance(raw_payload, dict):
            raise ValueError("Enrollment must be a JSON object.")
        payload = cast("dict[str, object]", raw_payload)
        raw_root = payload.get("root")
        if not isinstance(raw_root, str) or not raw_root.strip():
            raise ValueError("root must be a non-empty directory path.")
        root = Path(raw_root).resolve()
        watch = payload.get("watch", True)
        if type(watch) is not bool:
            raise ValueError("watch must be a boolean.")
        if not await run_sync(root.is_dir):
            raise ValueError("root must name an existing directory.")
    except (ValueError, OSError) as exc:
        return JSONResponse(
            {"ok": False, "error": "bad_request", "message": str(exc)},
            status_code=400,
        )
    from ..config._settings import get_config
    from ._watcher import _ensure_watcher_soon

    registry = get_request_runtime(request).registry
    if getattr(registry, "_shutting_down", False):
        return JSONResponse(
            {
                "ok": False,
                "error": "service_stopping",
                "message": "The service is stopping.",
            },
            status_code=503,
        )
    cfg = get_config()
    prefix = root_collection_prefix(root)

    def persist() -> bool:
        existing = load_manifest().get(prefix)
        record_root(
            root,
            backend="server" if cfg.effective_server_mode() else "local",
            last_indexed=None,
        )
        return existing is not None

    already = await run_sync(persist)
    if watch:
        _ensure_watcher_soon(root, registry)
    watching = root in _watching_roots()
    watcher_status = (
        "running"
        if watching
        else "pending"
        if watch and cfg.watch_enabled
        else "disabled"
    )
    return JSONResponse(
        {
            "ok": True,
            "root": str(root),
            "prefix": prefix,
            "status": "already_enrolled" if already else "enrolled",
            "watch_requested": watch,
            "watching": watching,
            "watcher_status": watcher_status,
        },
        status_code=202 if watcher_status == "pending" else 200,
    )
