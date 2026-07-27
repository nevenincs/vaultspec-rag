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

from .._units import human_bytes
from ._app import JsonMode, server_storage_app
from ._progress import StartupStatusReporter
from ._render import _emit_json, _emit_json_error_and_exit, _plain_line

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
        _plain_line(message)
        raise typer.Exit(2)
    return cfg.effective_qdrant_url


def _run_storage_op[T](
    command: str,
    json_mode: bool,
    fn: Callable[[QdrantClient], T],
) -> T:
    """Open a client to the managed server, run ``fn``, exit 3 if unreachable.

    The client does not signal an unreachable server with ``OSError``: it wraps
    the transport failure in its own ``ResponseHandlingException``, which is a
    plain ``Exception``. Catching only the builtin types let that escape, and a
    ``--json`` invocation then printed a traceback to stderr and NOTHING to
    stdout - zero envelopes on an exit path, which is the one thing the
    structured-outcome contract forbids, and unparseable for the broker the flag
    exists to serve. Every API-level failure is caught for the same reason: no
    exit path from a ``--json`` verb may leave stdout empty.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.http.exceptions import ApiException, ResponseHandlingException

    url = _resolve_server_url(command, json_mode)
    client = QdrantClient(url=url)
    try:
        return fn(client)
    except (OSError, RuntimeError, ResponseHandlingException) as exc:
        message = (
            f"Could not reach the managed Qdrant server at {url}. Start the "
            "service with `vaultspec-rag server start`."
        )
        if json_mode:
            _emit_json_error_and_exit(command, "service_not_running", message, 3)
        _plain_line(message)
        raise typer.Exit(3) from exc
    except ApiException as exc:
        # Reached the server but it refused the call. Distinct from unreachable
        # so the operator is not sent to start a service that is already up.
        message = f"The managed Qdrant server at {url} rejected the request: {exc}"
        if json_mode:
            _emit_json_error_and_exit(command, "storage_request_failed", message, 1)
        _plain_line(message)
        raise typer.Exit(1) from exc
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
                "models": s.models,
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
    total = human_bytes(sum(s.footprint_bytes for s in surveys))
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
            f"{human_bytes(s.footprint_bytes):>9}  {root}{marker}"
        )
        # Named only when the namespace holds more than one distinct model,
        # which is the state worth an operator's attention: the collections
        # under one root disagree about what built them. A single model, or
        # none recorded, adds a line per namespace that says nothing.
        distinct = sorted(set(s.models.values()))
        if len(distinct) > 1:
            typer.echo(f"           mixed embedding models: {', '.join(distinct)}")
    unstamped = sum(1 for s in surveys if not s.models)
    if unstamped:
        typer.echo(
            f"{unstamped} namespace(s) predate model stamping; what produced "
            "them is unknown until they are next rebuilt"
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

    The survey is the one read-only storage surface the service owns: when a
    daemon is up, the CLI reads its ``/storage/survey`` route so operator and
    MCP see one classification.
    A refused connection returns ``None`` so the caller falls back to the
    CLI-direct path; a live-but-error response (e.g. a non-server-mode 409)
    also returns ``None`` so the direct path renders the proper message.
    With ``root``, the route narrows to that root's namespace and its
    ``queried_root`` (the service-computed prefix) is returned alongside.
    """
    from ..serviceclient._discovery import _default_service_port
    from ..serviceclient._transport import _try_http_admin
    from ..storage_survey import NamespaceSurvey

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
    json_mode: JsonMode = False,
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
    # A survey counts points and walks the storage tree for every namespace,
    # which is minutes on a large backend. Reporting stays inside this block;
    # the table renders once it closes, so no result line can land inside a
    # live frame.
    with StartupStatusReporter(json_mode=json_mode) as progress:
        progress.announce("Surveying stored index namespaces...")
        progress.stage("Asking the running service for its survey...")
        # The CLI-direct fallback below always computes live, so --fresh only
        # needs to reach the service path.
        fetched = _survey_from_service(root, fresh=fresh)
        if fetched is not None:
            surveys, queried_root = fetched
        else:
            from ..storage_ops import gather_survey, server_storage_collections_dir

            progress.stage("No service answered; reading the store directly...")
            surveys = _run_storage_op(
                _SURVEY_CMD,
                json_mode,
                lambda c: gather_survey(
                    c,
                    server_storage_collections_dir(),
                    on_progress=progress.stage,
                ),
            )
            if root is not None:
                import pathlib

                from .._store_models import root_collection_prefix

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
    json_mode: JsonMode = False,
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

        from .._store_models import root_collection_prefix

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
        f"({human_bytes(result.reclaimed_bytes)}); "
        f"{len(result.skipped_unknown)} unknown left untouched."
    )
    for r in result.results:
        typer.echo(f"  {r.status:<12} {r.prefix}")
    if debris_result is not None:
        typer.echo(
            f"{verb} {len(debris_result.results)} debris collection dirs "
            f"({human_bytes(debris_result.reclaimed_bytes)})."
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
    json_mode: JsonMode = False,
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
    # A prune surveys the whole backend before it reclaims anything, so the
    # silent part is the survey, not the deletes.
    with StartupStatusReporter(json_mode=json_mode) as progress:
        progress.announce("Reclaiming orphaned index namespaces...")
        result = _run_storage_op(
            _PRUNE_CMD,
            json_mode,
            lambda c: prune_orphaned(
                c,
                dry_run=preview,
                storage_dir=storage_dir,
                on_progress=progress.stage,
            ),
        )
        if debris:
            progress.stage("Scanning for debris collection dirs...")
            debris_result = _run_storage_op(
                _PRUNE_CMD,
                json_mode,
                lambda c: prune_debris(c, storage_dir, dry_run=preview),
            )
        else:
            debris_result = None
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
    # converged nothing, and calling it "Reconciled ... 0 B reclaimed" reads
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
        f"({human_bytes(result.reclaimed_bytes)} reclaimed); "
        f"{result.drifted_remaining} still converging."
    )
    for r in result.results:
        detail = ""
        if r.status == "reconciled":
            detail = (
                f"{r.segments_before}->{r.segments_after} segments, "
                f"{human_bytes(r.reclaimed_bytes)} freed"
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
    json_mode: JsonMode = False,
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
    # With --wait (the default) each collection is held on until its optimizer
    # settles, up to the configured per-collection budget, so a full pass over
    # a drifted backend is the longest-running storage verb there is.
    with StartupStatusReporter(json_mode=json_mode) as progress:
        progress.announce("Reconciling collection geometry...")
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
                on_progress=progress.stage,
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
    """Map source collection names to target names for the given direction.

    The code entry resolves its SOURCE name through the root's served pointer
    rather than deriving it. A root that has published a rebuild serves
    ``<derived>_g<generation>``, so keying on the derived name alone copies
    either a superseded generation or nothing at all - migrating stale code
    data, or silently migrating none of it.

    The TARGET stays the derived base name in both directions. The target
    store has no pointer of its own, so it resolves to the derived name, and
    landing there means the migrated index is served immediately without
    carrying the source's generation history across.
    """
    from .. import store_schema
    from .._store_models import resolve_served_code_collection, root_collection_prefix

    prefix = root_collection_prefix(root)
    bases = store_schema.collection_names()

    def _source(base: str) -> str:
        derived = base if to_server else f"{prefix}{base}"
        if base != store_schema.CODE_COLLECTION:
            return derived
        return resolve_served_code_collection(root, derived)

    if to_server:
        return {_source(base): f"{prefix}{base}" for base in bases}
    return {_source(base): base for base in bases}


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
    json_mode: JsonMode = False,
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
    # A real migrate copies every point of every collection across two
    # backends; naming the collection in flight is the only signal that
    # distinguishes a large copy from a stalled one.
    try:
        with StartupStatusReporter(json_mode=json_mode) as progress:
            progress.announce(f"Migrating {root} to the {to_backend} backend...")
            results = migrate_collections(
                src, dst, name_map, dry_run=preview, on_progress=progress.stage
            )
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
    # Provenance first, then attribution: the carry reads the source home, and
    # the re-key rewrites it.
    _carry_identity_on_migrate(root, to_backend, local_path, name_map, preview, results)
    _rekey_manifest_on_migrate(root, to_backend, preview, results)
    _render_migrate(results, json_mode)
    if not dry_run and not yes and any(r.status == "would_migrate" for r in results):
        raise typer.Exit(1)


def _carry_identity_on_migrate(
    root: str,
    to_backend: str,
    local_path: Path,
    name_map: dict[str, str],
    preview: bool,
    results: list[MigrateResult],
) -> None:
    """Move each migrated collection's identity record onto its target name.

    A migrate copies vectors through the raw client, which stamps nothing, so
    without this the destination reads ``unverifiable`` despite the source's
    provenance being known. Skipped on a preview; best-effort, so a bookkeeping
    hiccup never fails an applied data move - a namespace that loses its record
    degrades to ``unverifiable``, which is the safe direction.
    """
    if preview:
        return
    from ..storage_ops import carry_migrated_identity

    try:
        carry_migrated_identity(
            root,
            name_map=name_map,
            to_backend=to_backend,
            local_dir=local_path,
            results=results,
        )
    except Exception as exc:  # best-effort provenance; never fail an applied move
        typer.echo(f"Note: migrated data but could not carry its identity: {exc}")


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
    from .._store_models import root_collection_prefix
    from ..storage_manifest import rekey_prefix

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
    _plain_line(message)
    raise typer.Exit(code)
