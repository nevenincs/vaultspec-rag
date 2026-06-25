"""CLI commands for the ``server storage`` group.

Thin adapters over the service-domain ``storage_ops`` functions. ``survey``
is a read-only, bounded view classifying every per-root namespace
(live / orphaned / unknown) via the persisted prefix-to-root manifest.
``delete`` removes one named namespace and ``prune`` reclaims every
orphaned namespace; both are dry-run-first, require ``--yes`` to apply,
emit ``--json`` (which requires ``--yes``), and exit 3 when the server is
unreachable. Neither ever touches an ``unknown`` (unattributable)
namespace - the safe default that makes accidental out-of-scope deletion
impossible without an explicit manifest attribution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import typer

from ._app import server_storage_app
from ._render import _emit_json, _emit_json_error_and_exit

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from qdrant_client import QdrantClient

    from ..storage_ops import DeleteResult, MigrateResult, PruneResult
    from ..storage_survey import NamespaceSurvey

_SURVEY_CMD = "server.storage.survey"
_DELETE_CMD = "server.storage.delete"
_PRUNE_CMD = "server.storage.prune"
_MIGRATE_CMD = "server.storage.migrate"


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def _resolve_server_url(command: str, json_mode: bool) -> str:
    """Return the managed Qdrant URL, or exit 2 if server mode is off."""
    from ..config import get_config

    cfg = get_config()
    if not cfg.effective_server_mode():
        message = (
            "Storage operations require server mode. Local-only stores have a "
            "single namespace and nothing to reconcile."
        )
        if json_mode:
            _emit_json_error_and_exit(command, "server_mode_required", message, 2)
        typer.echo(message)
        raise typer.Exit(2)
    return str(getattr(cfg, "qdrant_url", "") or f"http://127.0.0.1:{cfg.qdrant_port}")


def _run_storage_op[T](
    command: str,
    json_mode: bool,
    fn: Callable[[QdrantClient], T],
) -> T:
    """Open a client to the managed server, run ``fn``, exit 3 if unreachable."""
    from qdrant_client import QdrantClient

    url = _resolve_server_url(command, json_mode)
    client = QdrantClient(url=url)
    try:
        return fn(client)
    except (OSError, RuntimeError) as exc:
        message = (
            f"Could not reach the managed Qdrant server at {url}. Start the "
            "service with `vaultspec-rag server start`."
        )
        if json_mode:
            _emit_json_error_and_exit(command, "service_not_running", message, 3)
        typer.echo(message)
        raise typer.Exit(3) from exc
    finally:
        client.close()


def _require_yes_for_json(command: str, json_mode: bool, yes: bool) -> None:
    """Enforce that ``--json`` is paired with ``--yes`` (no prompt in a stream)."""
    if json_mode and not yes:
        _emit_json_error_and_exit(
            command,
            "json_requires_yes",
            "--json requires --yes so no confirmation prompt corrupts the stream.",
            2,
        )


# -- survey -----------------------------------------------------------------


def _emit_survey_json(surveys: list[NamespaceSurvey]) -> None:
    _emit_json(
        True,
        _SURVEY_CMD,
        data={
            "namespaces": [
                {
                    "prefix": s.prefix,
                    "root": s.root,
                    "status": s.status,
                    "collections": s.collections,
                    "points": s.points,
                    "footprint_bytes": s.footprint_bytes,
                }
                for s in surveys
            ],
            "total": len(surveys),
        },
    )


def _print_survey(surveys: list[NamespaceSurvey]) -> None:
    if not surveys:
        typer.echo("No matching namespaces.")
        return
    counts = {
        status: sum(1 for s in surveys if s.status == status)
        for status in ("orphaned", "unknown", "unverifiable", "live")
    }
    total = _human_size(sum(s.footprint_bytes for s in surveys))
    typer.echo(
        f"{len(surveys)} namespaces  (orphaned={counts['orphaned']} "
        f"unknown={counts['unknown']} unverifiable={counts['unverifiable']} "
        f"live={counts['live']})  {total} on disk"
    )
    for s in surveys:
        root = s.root if s.root is not None else "(unattributable)"
        typer.echo(
            f"  {s.status:<8} {s.prefix}  {s.points:>8} pts  "
            f"{_human_size(s.footprint_bytes):>9}  {root}"
        )


def _survey_from_service() -> list[NamespaceSurvey] | None:
    """Fetch the survey from a running service, or ``None`` if it is down.

    The survey is the one read-only storage surface the service owns
    (``service-domain-owns-operability``): when a daemon is up, the CLI reads
    its ``/storage/survey`` route so operator and MCP see one classification.
    A refused connection returns ``None`` so the caller falls back to the
    CLI-direct path; a live-but-error response (e.g. a non-server-mode 409)
    also returns ``None`` so the direct path renders the proper message.
    """
    from ..serviceclient import _try_http_admin
    from ..storage_survey import NamespaceSurvey
    from ._service_status import _default_service_port

    result = _try_http_admin("get_storage_survey", {}, _default_service_port())
    if not result or result.get("ok") is False:
        return None
    raw = result.get("namespaces")
    if not isinstance(raw, list):
        return None
    surveys: list[NamespaceSurvey] = []
    for item in cast("list[object]", raw):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, object]", item)
        root = entry.get("root")
        collections = entry.get("collections")
        names = (
            [str(c) for c in cast("list[object]", collections)]
            if isinstance(collections, list)
            else []
        )
        surveys.append(
            NamespaceSurvey(
                prefix=str(entry.get("prefix", "")),
                root=root if isinstance(root, str) else None,
                status=str(entry.get("status", "")),
                collections=names,
                points=int(cast("int", entry.get("points", 0) or 0)),
                footprint_bytes=int(cast("int", entry.get("footprint_bytes", 0) or 0)),
            )
        )
    return surveys


@server_storage_app.command(
    "survey",
    help="List stored RAG namespaces classified as live, orphaned, or unknown.",
)
def storage_survey(
    json_mode: bool = typer.Option(
        False, "--json", help="Emit JSON for scripts instead of human text."
    ),
    orphaned_only: bool = typer.Option(
        False, "--orphaned", help="Show only orphaned namespaces (prune candidates)."
    ),
    unknown_only: bool = typer.Option(
        False, "--unknown", help="Show only unattributable (unknown) namespaces."
    ),
) -> None:
    """Survey the managed server's per-root index namespaces.

    Service-first: when a daemon is running, the survey comes from its
    ``/storage/survey`` route so operator, CLI, and MCP share one
    classification. When no service answers, the CLI opens its own client to
    the managed server directly (the same path the destructive verbs use).
    """
    surveys = _survey_from_service()
    if surveys is None:
        from ..storage_ops import gather_survey, server_storage_collections_dir

        surveys = _run_storage_op(
            _SURVEY_CMD,
            json_mode,
            lambda c: gather_survey(c, server_storage_collections_dir()),
        )
    if orphaned_only:
        surveys = [s for s in surveys if s.status == "orphaned"]
    if unknown_only:
        surveys = [s for s in surveys if s.status == "unknown"]
    if json_mode:
        _emit_survey_json(surveys)
    else:
        _print_survey(surveys)


# -- delete -----------------------------------------------------------------


def _render_delete(result: DeleteResult, json_mode: bool) -> None:
    if json_mode:
        _emit_json(
            True,
            _DELETE_CMD,
            data={
                "prefix": result.prefix,
                "status": result.status,
                "collections": result.collections,
                "reason": result.reason,
            },
        )
        return
    if result.status == "skipped":
        typer.echo(f"Skipped {result.prefix}: {result.reason}")
    elif result.status == "would_remove":
        typer.echo(
            f"Would remove {result.prefix} "
            f"({len(result.collections)} collections). Re-run with --yes."
        )
    elif result.status == "removed":
        typer.echo(f"Removed {result.prefix} ({len(result.collections)} collections).")
    else:
        typer.echo(f"Failed {result.prefix}: {result.reason}")


@server_storage_app.command(
    "delete",
    help="Delete one named RAG namespace (its r{hash}_ prefix).",
)
def storage_delete(
    prefix: str = typer.Argument(
        ..., help="The namespace prefix to delete (r{hash}_)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the deletion."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON for scripts."),
    allow_unknown: bool = typer.Option(
        False,
        "--allow-unknown",
        help="Permit deleting a prefix the manifest cannot attribute (dangerous).",
    ),
) -> None:
    """Delete a single per-root namespace from the managed server."""
    from ..storage_ops import delete_prefix

    _require_yes_for_json(_DELETE_CMD, json_mode, yes)
    preview = dry_run or not yes
    result = _run_storage_op(
        _DELETE_CMD,
        json_mode,
        lambda c: delete_prefix(
            c, prefix, dry_run=preview, allow_unknown=allow_unknown
        ),
    )
    _render_delete(result, json_mode)
    # A non-dry preview that found a target exits non-zero to signal "not applied".
    if not dry_run and not yes and result.status == "would_remove":
        raise typer.Exit(1)


# -- prune ------------------------------------------------------------------


def _render_prune(result: PruneResult, json_mode: bool) -> None:
    if json_mode:
        _emit_json(
            True,
            _PRUNE_CMD,
            data={
                "results": [
                    {"prefix": r.prefix, "status": r.status, "reason": r.reason}
                    for r in result.results
                ],
                "skipped_unknown": result.skipped_unknown,
                "reclaimed_bytes": result.reclaimed_bytes,
                "dry_run": result.dry_run,
            },
        )
        return
    verb = "Would reclaim" if result.dry_run else "Reclaimed"
    typer.echo(
        f"{verb} {len(result.results)} orphaned namespaces "
        f"({_human_size(result.reclaimed_bytes)}); "
        f"{len(result.skipped_unknown)} unknown left untouched."
    )
    for r in result.results:
        typer.echo(f"  {r.status:<12} {r.prefix}")


@server_storage_app.command(
    "prune",
    help="Reclaim every orphaned RAG namespace (source root gone).",
)
def storage_prune(
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the prune."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON for scripts."),
) -> None:
    """Reclaim all orphaned namespaces; never touches unknown or live ones."""
    from ..storage_ops import prune_orphaned, server_storage_collections_dir

    _require_yes_for_json(_PRUNE_CMD, json_mode, yes)
    preview = dry_run or not yes
    result = _run_storage_op(
        _PRUNE_CMD,
        json_mode,
        lambda c: prune_orphaned(
            c, dry_run=preview, storage_dir=server_storage_collections_dir()
        ),
    )
    _render_prune(result, json_mode)
    if not dry_run and not yes and result.results:
        raise typer.Exit(1)


# -- migrate ----------------------------------------------------------------


def _local_store_path(root: str) -> Path:
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    return Path(root).expanduser() / str(cfg.data_dir) / str(cfg.qdrant_dir)


def _migrate_name_map(root: str, *, to_server: bool) -> dict[str, str]:
    """Map source collection names to target names for the given direction."""
    from ..store import VaultStore, root_collection_prefix

    prefix = root_collection_prefix(root)
    bases = (VaultStore.TABLE_NAME, VaultStore.CODE_TABLE_NAME)
    if to_server:
        return {base: f"{prefix}{base}" for base in bases}
    return {f"{prefix}{base}": base for base in bases}


def _render_migrate(results: list[MigrateResult], json_mode: bool) -> None:
    if json_mode:
        _emit_json(
            True,
            _MIGRATE_CMD,
            data={
                "results": [
                    {
                        "source": r.source,
                        "target": r.target,
                        "status": r.status,
                        "points": r.points,
                        "reason": r.reason,
                    }
                    for r in results
                ]
            },
        )
        return
    for r in results:
        suffix = f" ({r.reason})" if r.reason else ""
        typer.echo(f"  {r.status:<14} {r.source} -> {r.target}  {r.points} pts{suffix}")


@server_storage_app.command(
    "migrate",
    help="Migrate a root's index between local and server backends.",
)
def storage_migrate(
    root: str = typer.Argument(..., help="The workspace root whose index to migrate."),
    to_backend: str = typer.Option(
        ..., "--to", help="Target backend: 'server' or 'local'."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the migration."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without copying."),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON for scripts."),
) -> None:
    """Copy a root's namespaced collections between the local and server stores."""
    from qdrant_client import QdrantClient

    from ..storage_ops import migrate_collections

    _require_yes_for_json(_MIGRATE_CMD, json_mode, yes)
    if to_backend not in ("server", "local"):
        _emit_or_echo_error(
            _MIGRATE_CMD,
            "invalid_target",
            "Use --to server or --to local.",
            2,
            json_mode,
        )
    to_server = to_backend == "server"
    url = _resolve_server_url(_MIGRATE_CMD, json_mode)
    name_map = _migrate_name_map(root, to_server=to_server)
    # Data-safety: the local store path must resolve inside the root (rejects
    # traversal / symlink escape from a crafted data-dir config) before we open
    # or write any on-disk store.
    from ..storage_safety import StorageSafetyError, resolve_within

    local_path = _local_store_path(root)
    try:
        resolve_within(local_path, root)
    except StorageSafetyError as exc:
        _emit_or_echo_error(
            _MIGRATE_CMD, "unsafe_path", f"Refusing migrate: {exc}", 2, json_mode
        )
    local = QdrantClient(path=str(local_path))
    server = QdrantClient(url=url)
    src, dst = (local, server) if to_server else (server, local)
    preview = dry_run or not yes
    try:
        results = migrate_collections(src, dst, name_map, dry_run=preview)
    except (OSError, RuntimeError) as exc:
        _emit_or_echo_error(
            _MIGRATE_CMD,
            "migrate_failed",
            f"Migration failed: {exc}",
            1,
            json_mode,
        )
        raise typer.Exit(1) from exc
    finally:
        local.close()
        server.close()
    _rekey_manifest_on_migrate(root, to_backend, preview, results)
    _render_migrate(results, json_mode)
    if not dry_run and not yes and any(r.status == "would_migrate" for r in results):
        raise typer.Exit(1)


def _rekey_manifest_on_migrate(
    root: str,
    to_backend: str,
    preview: bool,
    results: list[MigrateResult],
) -> None:
    """Re-key the root's manifest entry to the new backend after a real migrate.

    The prefix is derived from the resolved root, so a backend change keeps
    the same key but must update ``backend`` (and carry the prefix forward)
    so a later survey attributes the migrated data to the right backend
    instead of leaving a stale ``server`` label on a now-local root. Skipped
    on a preview and when nothing actually migrated; best-effort, so a
    manifest hiccup never fails an applied data move.
    """
    if preview or not any(r.status == "migrated" for r in results):
        return
    from ..storage_manifest import rekey_prefix
    from ..store import root_collection_prefix

    try:
        prefix = root_collection_prefix(root)
        rekey_prefix(prefix, root=root, backend=to_backend)
    except Exception as exc:  # best-effort attribution; never fail an applied move
        typer.echo(f"Note: migrated data but could not update the manifest: {exc}")


def _emit_or_echo_error(
    command: str, error: str, message: str, code: int, json_mode: bool
) -> None:
    """Emit a JSON error or echo it, then exit with ``code``."""
    if json_mode:
        _emit_json_error_and_exit(command, error, message, code)
    typer.echo(message)
    raise typer.Exit(code)
