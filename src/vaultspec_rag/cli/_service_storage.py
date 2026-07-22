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

    from ..storage_ops import (
        DeleteResult,
        MigrateResult,
        PruneResult,
        ReconcileBatch,
    )
    from ..storage_survey import NamespaceSurvey

_SURVEY_CMD = "server.storage.survey"
_DELETE_CMD = "server.storage.delete"
_PRUNE_CMD = "server.storage.prune"
_MIGRATE_CMD = "server.storage.migrate"
_RECONCILE_CMD = "server.storage.reconcile"


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


def _emit_survey_json(
    surveys: list[NamespaceSurvey], queried_root: dict[str, str] | None = None
) -> None:
    from ..storage_survey import is_temp_rooted

    data: dict[str, object] = {
        "namespaces": [
            {
                "prefix": s.prefix,
                "root": s.root,
                "status": s.status,
                "collections": s.collections,
                "points": s.points,
                "footprint_bytes": s.footprint_bytes,
                "temp_rooted": is_temp_rooted(s.root),
            }
            for s in surveys
        ],
        "returned": len(surveys),
        "total": len(surveys),
    }
    if queried_root is not None:
        data["queried_root"] = queried_root
    _emit_json(True, _SURVEY_CMD, data=data)


def _print_survey(surveys: list[NamespaceSurvey]) -> None:
    from ..storage_survey import is_temp_rooted

    if not surveys:
        typer.echo("No matching namespaces.")
        return
    counts = {
        status: sum(1 for s in surveys if s.status == status)
        for status in ("orphaned", "unknown", "unverifiable", "live")
    }
    temp_count = sum(1 for s in surveys if is_temp_rooted(s.root))
    total = _human_size(sum(s.footprint_bytes for s in surveys))
    summary = (
        f"{len(surveys)} namespaces  (orphaned={counts['orphaned']} "
        f"unknown={counts['unknown']} unverifiable={counts['unverifiable']} "
        f"live={counts['live']})  {total} on disk"
    )
    if temp_count:
        summary += f"  [{temp_count} temp-rooted]"
    typer.echo(summary)
    for s in surveys:
        root = s.root if s.root is not None else "(unattributable)"
        marker = "  [temp]" if is_temp_rooted(s.root) else ""
        typer.echo(
            f"  {s.status:<8} {s.prefix}  {s.points:>8} pts  "
            f"{_human_size(s.footprint_bytes):>9}  {root}{marker}"
        )
    if temp_count:
        typer.echo(
            "Temp-rooted namespaces are usually leaked test/demo harness "
            "indexes; reclaim with: vaultspec-rag server storage delete "
            "--root <dir> --yes"
        )


def _survey_from_service(
    root: str | None = None, fresh: bool = False
) -> tuple[list[NamespaceSurvey], dict[str, str] | None] | None:
    """Fetch the survey from a running service, or ``None`` if it is down.

    The survey is the one read-only storage surface the service owns
    (``service-domain-owns-operability``): when a daemon is up, the CLI reads
    its ``/storage/survey`` route so operator and MCP see one classification.
    A refused connection returns ``None`` so the caller falls back to the
    CLI-direct path; a live-but-error response (e.g. a non-server-mode 409)
    also returns ``None`` so the direct path renders the proper message.
    With ``root``, the route narrows to that root's namespace and its
    ``queried_root`` (the service-computed prefix) is returned alongside.
    """
    from ..serviceclient import _try_http_admin
    from ..storage_survey import NamespaceSurvey
    from ._service_status import _default_service_port

    args: dict[str, object] = {"root": root} if root else {}
    if fresh:
        args["fresh"] = "true"
    result = _try_http_admin("get_storage_survey", args, _default_service_port())
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
        entry_root = entry.get("root")
        collections = entry.get("collections")
        names = (
            [str(c) for c in cast("list[object]", collections)]
            if isinstance(collections, list)
            else []
        )
        surveys.append(
            NamespaceSurvey(
                prefix=str(entry.get("prefix", "")),
                root=entry_root if isinstance(entry_root, str) else None,
                status=str(entry.get("status", "")),
                collections=names,
                points=int(cast("int", entry.get("points", 0) or 0)),
                footprint_bytes=int(cast("int", entry.get("footprint_bytes", 0) or 0)),
            )
        )
    raw_queried = result.get("queried_root")
    queried_root: dict[str, str] | None = None
    if isinstance(raw_queried, dict):
        queried = cast("dict[str, object]", raw_queried)
        queried_root = {
            "root": str(queried.get("root", "")),
            "prefix": str(queried.get("prefix", "")),
        }
    return surveys, queried_root


@server_storage_app.command(
    "survey",
    help=(
        "List stored RAG namespaces classified as live, orphaned, or unknown; "
        "--root looks up one root's collection prefix and namespace."
    ),
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
    root: str | None = typer.Option(
        None,
        "--root",
        help=(
            "Narrow to one root's namespace and report its authoritative "
            "collection prefix (works even for a root not yet indexed)."
        ),
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help=(
            "Force the service to recompute the survey instead of answering "
            "from its cached snapshot (slower; walks every namespace)."
        ),
    ),
) -> None:
    """Survey the managed server's per-root index namespaces.

    Service-first: when a daemon is running, the survey comes from its
    ``/storage/survey`` route so operator, CLI, and MCP share one
    classification. When no service answers, the CLI opens its own client to
    the managed server directly (the same path the destructive verbs use).
    With ``--root``, both paths resolve the root through the one
    ``root_collection_prefix`` derivation and report it as ``queried_root``.
    """
    if root is not None:
        import pathlib

        # Resolve against the operator's cwd BEFORE dispatch: the daemon would
        # otherwise resolve a relative path against its own inherited cwd,
        # silently disagreeing with the CLI-direct fallback.
        root = str(pathlib.Path(root).resolve())
    queried_root: dict[str, str] | None = None
    # The CLI-direct fallback below always computes live, so --fresh only
    # needs to reach the service path.
    fetched = _survey_from_service(root, fresh=fresh)
    if fetched is not None:
        surveys, queried_root = fetched
    else:
        from ..storage_ops import gather_survey, server_storage_collections_dir

        surveys = _run_storage_op(
            _SURVEY_CMD,
            json_mode,
            lambda c: gather_survey(c, server_storage_collections_dir()),
        )
        if root is not None:
            import pathlib

            from ..store import root_collection_prefix

            prefix = root_collection_prefix(root)
            queried_root = {
                "root": str(pathlib.Path(root).resolve()),
                "prefix": prefix,
            }
            surveys = [s for s in surveys if s.prefix == prefix]
    if orphaned_only:
        surveys = [s for s in surveys if s.status == "orphaned"]
    if unknown_only:
        surveys = [s for s in surveys if s.status == "unknown"]
    if json_mode:
        _emit_survey_json(surveys, queried_root)
    else:
        if queried_root is not None:
            typer.echo(
                f"Queried root: {queried_root['root']}  "
                f"prefix: {queried_root['prefix']}"
            )
        _print_survey(surveys)


# -- delete -----------------------------------------------------------------


def _render_delete(
    result: DeleteResult,
    json_mode: bool,
    queried_root: dict[str, str] | None = None,
) -> None:
    if json_mode:
        data: dict[str, object] = {
            "prefix": result.prefix,
            "status": result.status,
            "collections": result.collections,
            "reason": result.reason,
        }
        if queried_root is not None:
            data["queried_root"] = queried_root
        _emit_json(True, _DELETE_CMD, data=data)
        return
    if queried_root is not None:
        typer.echo(
            f"Queried root: {queried_root['root']}  prefix: {queried_root['prefix']}"
        )
    if result.status == "already_absent":
        typer.echo(f"Namespace {result.prefix} already absent; nothing to delete.")
    elif result.status == "skipped":
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
    help=(
        "Delete one named RAG namespace, addressed by its r{hash}_ prefix "
        "or by --root (the sanctioned per-root teardown for harnesses)."
    ),
)
def storage_delete(
    prefix: str | None = typer.Argument(
        None, help="The namespace prefix to delete (r{hash}_)."
    ),
    root: str | None = typer.Option(
        None,
        "--root",
        help=(
            "Address the namespace by its source root path instead of the "
            "prefix; an already-absent namespace is a success (exit 0)."
        ),
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
    """Delete a single per-root namespace from the managed server.

    ``--root`` resolves the path against the operator's cwd and derives the
    prefix through the one real ``root_collection_prefix`` derivation - the
    same normalization registration uses - so a test harness can tear down
    exactly the namespace it registered without knowing the hash. A vanished
    namespace reports ``already_absent`` and exits 0 in both modes, making
    teardown idempotent.
    """
    import dataclasses

    from ..storage_ops import delete_prefix

    if (prefix is None) == (root is None):
        _emit_or_echo_error(
            _DELETE_CMD,
            "bad_request",
            "Provide exactly one of the prefix argument or --root.",
            2,
            json_mode=json_mode,
        )
    queried_root: dict[str, str] | None = None
    if root is not None:
        import pathlib

        from ..store import root_collection_prefix

        resolved = str(pathlib.Path(root).resolve())
        prefix = root_collection_prefix(resolved)
        queried_root = {"root": resolved, "prefix": prefix}
    target = cast("str", prefix)
    _require_yes_for_json(_DELETE_CMD, json_mode, yes)
    preview = dry_run or not yes
    result = _run_storage_op(
        _DELETE_CMD,
        json_mode,
        lambda c: delete_prefix(
            c, target, dry_run=preview, allow_unknown=allow_unknown
        ),
    )
    if result.status == "skipped" and result.reason == "no_such_namespace":
        # Idempotent teardown: the requested end state (namespace gone)
        # already holds, so this is a success, not a fault a broker or
        # harness should retry.
        result = dataclasses.replace(result, status="already_absent", reason=None)
    _render_delete(result, json_mode, queried_root)
    # A non-dry preview that found a target exits non-zero to signal "not applied".
    if not dry_run and not yes and result.status == "would_remove":
        raise typer.Exit(1)


# -- prune ------------------------------------------------------------------


def _render_prune(
    result: PruneResult,
    json_mode: bool,
    debris_result: PruneResult | None = None,
) -> None:
    if json_mode:
        data: dict[str, object] = {
            "results": [
                {"prefix": r.prefix, "status": r.status, "reason": r.reason}
                for r in result.results
            ],
            "skipped_unknown": result.skipped_unknown,
            "reclaimed_bytes": result.reclaimed_bytes,
            "dry_run": result.dry_run,
        }
        if debris_result is not None:
            data["debris"] = {
                "results": [
                    {"name": r.prefix, "status": r.status, "reason": r.reason}
                    for r in debris_result.results
                ],
                "reclaimed_bytes": debris_result.reclaimed_bytes,
            }
        _emit_json(True, _PRUNE_CMD, data=data)
        return
    verb = "Would reclaim" if result.dry_run else "Reclaimed"
    typer.echo(
        f"{verb} {len(result.results)} orphaned namespaces "
        f"({_human_size(result.reclaimed_bytes)}); "
        f"{len(result.skipped_unknown)} unknown left untouched."
    )
    for r in result.results:
        typer.echo(f"  {r.status:<12} {r.prefix}")
    if debris_result is not None:
        typer.echo(
            f"{verb} {len(debris_result.results)} debris collection dirs "
            f"({_human_size(debris_result.reclaimed_bytes)})."
        )
        for r in debris_result.results:
            typer.echo(f"  {r.status:<12} {r.prefix}")


@server_storage_app.command(
    "prune",
    help="Reclaim every orphaned RAG namespace (source root gone).",
)
def storage_prune(
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the prune."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    debris: bool = typer.Option(
        False,
        "--debris",
        help=(
            "Also remove config-less collection dirs left behind by "
            "crashes (unloadable by the server; filesystem delete)."
        ),
    ),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON for scripts."),
) -> None:
    """Reclaim all orphaned namespaces; never touches unknown or live ones."""
    from ..storage_ops import (
        prune_debris,
        prune_orphaned,
        server_storage_collections_dir,
    )

    _require_yes_for_json(_PRUNE_CMD, json_mode, yes)
    preview = dry_run or not yes
    storage_dir = server_storage_collections_dir()
    result = _run_storage_op(
        _PRUNE_CMD,
        json_mode,
        lambda c: prune_orphaned(c, dry_run=preview, storage_dir=storage_dir),
    )
    debris_result = (
        _run_storage_op(
            _PRUNE_CMD,
            json_mode,
            lambda c: prune_debris(c, storage_dir, dry_run=preview),
        )
        if debris
        else None
    )
    _render_prune(result, json_mode, debris_result)
    applied_anything = bool(result.results) or bool(
        debris_result.results if debris_result is not None else []
    )
    if not dry_run and not yes and applied_anything:
        raise typer.Exit(1)


# -- reconcile --------------------------------------------------------------


def _batch_status(result: ReconcileBatch) -> str:
    """Machine-readable outcome for one reconcile pass.

    A broker keys on this, so a preview must never read as an applied
    change, and a pass that only issued updates must not claim the
    reclamation it has not observed.
    """
    if not result.results:
        return "already_converged"
    if result.dry_run:
        return "preview"
    if any(r.status == "reconciled" for r in result.results):
        return "applied"
    return "issued"


def _render_reconcile(result: ReconcileBatch, json_mode: bool) -> None:
    if json_mode:
        _emit_json(
            True,
            _RECONCILE_CMD,
            data={
                "results": [
                    {
                        "collection": r.collection,
                        "status": r.status,
                        "segments_before": r.segments_before,
                        "segments_after": r.segments_after,
                        "bytes_before": r.bytes_before,
                        "bytes_after": r.bytes_after,
                        "reclaimed_bytes": r.reclaimed_bytes,
                        "reason": r.reason,
                    }
                    for r in result.results
                ],
                "drifted_remaining": result.drifted_remaining,
                "reclaimed_bytes": result.reclaimed_bytes,
                "dry_run": result.dry_run,
                "status": _batch_status(result),
            },
        )
        return
    if not result.results:
        typer.echo("Every collection is already at the bounded geometry.")
        return
    # The verb has to follow what actually happened: an unwaited run has
    # converged nothing, and calling it "Reconciled ... 0.0B reclaimed" reads
    # as a failed reconcile rather than an unobserved one.
    converged = sum(1 for r in result.results if r.status == "reconciled")
    if result.dry_run:
        verb = "Would reconcile"
    elif converged:
        verb = "Reconciled"
    else:
        verb = "Started reconcile on"
    typer.echo(
        f"{verb} {len(result.results)} collections "
        f"({_human_size(result.reclaimed_bytes)} reclaimed); "
        f"{result.drifted_remaining} still converging."
    )
    for r in result.results:
        detail = ""
        if r.status == "reconciled":
            detail = (
                f"{r.segments_before}->{r.segments_after} segments, "
                f"{_human_size(r.reclaimed_bytes)} freed"
            )
        elif r.reason:
            detail = r.reason
        typer.echo(f"  {r.status:<16} {r.collection:<32} {detail}")


@server_storage_app.command(
    "reconcile",
    help="Shrink existing collections to the bounded segment geometry.",
)
def storage_reconcile(
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the reconcile."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changing."),
    limit: int = typer.Option(
        0,
        "--limit",
        help="Max collections to reconcile (0 = every drifted collection).",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help=(
            "Wait for the optimizer to converge before reporting. With "
            "--no-wait the updates are issued and reclamation is reported "
            "by a later run, since mid-flight sizes are meaningless."
        ),
    ),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON for scripts."),
) -> None:
    """Converge pre-existing collections onto the bounded geometry.

    Non-destructive: no point is moved or deleted and the collection stays
    queryable throughout. Collections already at target are skipped, so
    running this on a converged backend is a no-op success.
    """
    from ..config import get_config
    from ..storage_ops import reconcile_collections, server_storage_collections_dir

    _require_yes_for_json(_RECONCILE_CMD, json_mode, yes)
    preview = dry_run or not yes
    cfg = get_config()
    storage_dir = server_storage_collections_dir()
    result = _run_storage_op(
        _RECONCILE_CMD,
        json_mode,
        lambda c: reconcile_collections(
            c,
            storage_dir=storage_dir,
            cap=limit if limit > 0 else _UNCAPPED_RECONCILE,
            budget_s=float(cfg.storage_reconcile_budget_seconds),
            dry_run=preview,
            wait=wait,
        ),
    )
    _render_reconcile(result, json_mode)
    if not dry_run and not yes and result.results:
        raise typer.Exit(1)


# A cap large enough to mean "every drifted collection" for an operator-driven
# run; the scheduled cycle keeps its small per-cycle cap.
_UNCAPPED_RECONCILE = 1_000_000


# -- migrate ----------------------------------------------------------------


def _local_store_path(root: str) -> Path:
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    return Path(root).expanduser() / str(cfg.data_dir) / str(cfg.qdrant_dir)


def _migrate_name_map(root: str, *, to_server: bool) -> dict[str, str]:
    """Map source collection names to target names for the given direction."""
    from .. import store_schema
    from ..store import root_collection_prefix

    prefix = root_collection_prefix(root)
    bases = store_schema.collection_names()
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
