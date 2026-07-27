"""Validated compatibility adapters over canonical ``POST /jobs`` creation.

``/reindex`` and ``/clean`` predate the canonical jobs resource and stay as
independent-per-domain adapters: each admits and creates its own job through
the same validation and admission pipeline :mod:`._routes` exposes for the
canonical resource, so a partial failure in one domain (e.g. ``code``) never
blocks the others in a ``combined`` request. That pipeline is reached through
function-local imports here to avoid a module-load cycle with ``._routes``,
which imports ``reindex_route``/``clean_route`` for its route table.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse

import vaultspec_rag.server as _m

from .._source_types import PublicSourceType, SourceTypeParseError, parse_source_type
from ._auth import require_token
from ._utils import ProjectRootRequiredError, _resolve_root

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..indexer._codebase_indexer import CodeIndexPreflight

logger = logging.getLogger("vaultspec_rag.server")

__all__ = ["clean_route", "reindex_route"]


def _preprocess_preflight(
    root: Path,
    admission: CodeIndexPreflight | None = None,
) -> dict[str, object]:
    """Report whether *root*'s preprocess hooks will run, before indexing.

    The ``/reindex`` route returns ``queued`` before the background job runs,
    so a non-interactive client otherwise has no way to know whether the root's
    document-preprocessing hooks will fire. This
    mirrors the ``server start`` operator notice as JSON: whether the root ships
    a preprocess configuration, its resolved rule count, the effective mode,
    and whether hooks will run under it (``off`` skips; ``default`` runs).

    Code jobs project rule count, mode, and execution state from the same
    structured scan used for admission. The file-presence field is retained as
    non-authoritative compatibility metadata. Vault jobs do not run this code
    admission scan, so their legacy informational response keeps its bounded,
    CPU-only configuration read.
    """
    from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

    config_present = (root / PREPROCESS_CONFIG_FILENAME).is_file()
    if admission is not None:
        scan = admission.scan
        return {
            "config_present": config_present,
            "rule_count": scan.preprocess_rule_count,
            "mode": scan.preprocess_mode,
            "hooks_will_run": scan.hooks_will_run,
        }

    from ..config._settings import get_config
    from ..indexer._preprocess_config import (
        PreprocessConfigError,
        load_preprocess_rules,
    )

    mode = get_config().preprocess_mode
    rule_count = 0
    if config_present:
        try:
            # strict resolves the true rule count regardless of the kill
            # switch, so the count reported is the config's own, not a
            # mode-gated zero.
            rule_count = len(load_preprocess_rules(root, strict=True).rules)
        except PreprocessConfigError:
            rule_count = 0
    hooks_will_run = config_present and rule_count > 0 and mode != "off"
    return {
        "config_present": config_present,
        "rule_count": rule_count,
        "mode": mode,
        "hooks_will_run": hooks_will_run,
    }


def _reindex_sources(source_type: PublicSourceType) -> tuple[PublicSourceType, ...]:
    """Expand the combined compatibility source into independent domains."""
    if source_type is not PublicSourceType.COMBINED:
        return (source_type,)
    return (
        PublicSourceType.VAULT,
        PublicSourceType.CODE,
        PublicSourceType.DOCUMENT,
    )


def _reindex_failure(*, error_kind: str, detail: str) -> dict[str, object]:
    """Return one stable failed-domain response."""
    return {
        "ok": False,
        "job_id": None,
        "error_kind": error_kind,
        "detail": detail,
        "outcome": {
            "status": "error",
            "code": error_kind,
            "message": detail,
        },
    }


async def _validate_reindex_domains(
    request: Request,
    payload: dict[str, object],
    source_type: PublicSourceType,
    *,
    clean: bool,
) -> tuple[list[tuple[PublicSourceType, Any]], dict[str, dict[str, object]]]:
    """Validate every requested domain without collapsing combined admission."""
    from ._routes import InvalidJobRequestError, validated_index_request

    validated: list[tuple[PublicSourceType, Any]] = []
    failures: dict[str, dict[str, object]] = {}
    for source in _reindex_sources(source_type):
        canonical_payload = {
            **payload,
            "operation": "index",
            "source": source.value,
            "mode": "rebuild" if clean else "incremental",
            "start_paused": False,
        }
        try:
            request_parts = await validated_index_request(
                request,
                canonical_payload,
                idempotency_suffix=(
                    source.value if source_type is PublicSourceType.COMBINED else None
                ),
            )
        except InvalidJobRequestError as exc:
            if source_type is not PublicSourceType.COMBINED:
                raise
            failures[source.value] = _reindex_failure(
                error_kind=exc.code,
                detail=str(exc),
            )
        else:
            validated.append((source, request_parts))
    return validated, failures


async def _create_reindex_domains(
    validated: list[tuple[PublicSourceType, Any]],
    source_type: PublicSourceType,
    domain_responses: dict[str, dict[str, object]],
) -> tuple[Path | None, CodeIndexPreflight | None]:
    """Create independently validated jobs and retain per-domain failures."""
    from ..job_models import JobOutcomeStatus
    from ..jobs import get_job_manager
    from ._routes import activate_index_job, index_admission_preflight

    manager = get_job_manager()
    first_root: Path | None = None
    first_admission: CodeIndexPreflight | None = None
    for source, request_parts in validated:
        spec, initiator, start_paused, idempotency_key, admission = request_parts
        try:
            outcome = await _run_in_thread(
                partial(
                    manager.create,
                    spec,
                    initiator,
                    start_paused=start_paused,
                    idempotency_key=idempotency_key,
                )
            )
            outcome = await activate_index_job(outcome, admission)
        except Exception as exc:
            if source_type is not PublicSourceType.COMBINED:
                raise
            logger.exception("Combined reindex failed for %s", source.value)
            domain_responses[source.value] = _reindex_failure(
                error_kind=type(exc).__name__,
                detail=str(exc) or type(exc).__name__,
            )
            continue
        ok = outcome.status is not JobOutcomeStatus.ERROR
        domain: dict[str, object] = {
            "ok": ok,
            "job_id": outcome.job.id if outcome.job is not None else None,
            "error_kind": None if ok else outcome.code,
            "detail": outcome.message,
            "outcome": outcome.to_dict(),
        }
        if admission is not None:
            domain["admission"] = index_admission_preflight(admission)
        domain_responses[source.value] = domain
        if outcome.job is not None:
            first_root = Path(str(outcome.job.spec.project_root))
        if (
            first_admission is None
            and source is PublicSourceType.CODE
            and admission is not None
        ):
            first_admission = cast("CodeIndexPreflight", admission)
    return first_root, first_admission


async def reindex_route(request: Request) -> JSONResponse:
    """Validated compatibility adapter over canonical ``POST /jobs`` creation."""
    from ._routes import (
        InvalidJobRequestError,
        job_error,
        job_outcome_status,
        job_payload,
    )

    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await job_payload(request, required=True)
        try:
            source_type = parse_source_type(
                payload.get("type", PublicSourceType.VAULT.value),
                allow_aliases=False,
            )
        except SourceTypeParseError as exc:
            return job_error(
                "create",
                "invalid_job_spec",
                str(exc),
                extra={"error": exc.error_kind, **exc.as_payload()},
            )
        clean = payload.get("clean", False)
        if type(clean) is not bool:
            raise InvalidJobRequestError(
                "invalid_job_spec",
                "clean must be a boolean when provided.",
            )
        validated, domain_responses = await _validate_reindex_domains(
            request,
            payload,
            source_type,
            clean=clean,
        )
    except InvalidJobRequestError as exc:
        return job_error("create", exc.code, str(exc))

    first_root, first_admission = await _create_reindex_domains(
        validated,
        source_type,
        domain_responses,
    )

    if first_root is not None:
        _m._ensure_watcher_soon(first_root)
    if source_type is PublicSourceType.COMBINED:
        successes = sum(bool(item["ok"]) for item in domain_responses.values())
        return JSONResponse(
            {
                "ok": successes == len(domain_responses),
                "partial": 0 < successes < len(domain_responses),
                "status": (
                    "queued"
                    if successes == len(domain_responses)
                    else "partial"
                    if successes
                    else "failed"
                ),
                "domains": domain_responses,
            },
            status_code=200 if successes else 409,
        )

    domain = domain_responses[source_type.value]
    if not domain["ok"]:
        outcome_payload = cast("dict[str, object]", domain["outcome"])
        return JSONResponse(
            {**outcome_payload, "ok": False, "error": domain["error_kind"]},
            status_code=job_outcome_status(str(domain["error_kind"])),
        )
    assert first_root is not None
    response: dict[str, object] = {
        "ok": True,
        "job_id": domain["job_id"],
        "status": "queued",
        "preprocess": _preprocess_preflight(first_root, first_admission),
        "outcome": domain["outcome"],
    }
    if "admission" in domain:
        response["admission"] = domain["admission"]
    return JSONResponse(response)


async def clean_route(request: Request) -> JSONResponse:
    """Clean one canonical index domain or all domains independently."""
    from ._routes import InvalidJobRequestError, job_payload, job_string

    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        payload = await job_payload(request, required=True)
        try:
            source_type = parse_source_type(
                payload.get("type", PublicSourceType.COMBINED.value),
                allow_aliases=False,
            )
        except SourceTypeParseError as exc:
            return JSONResponse(exc.as_error_envelope(), status_code=400)
        raw_root = job_string(payload, "project_root")
        root = _resolve_root(raw_root)
    except (ProjectRootRequiredError, ValueError, InvalidJobRequestError) as exc:
        return JSONResponse(
            {"ok": False, "error": "invalid_clean_request", "message": str(exc)},
            status_code=400,
        )

    import vaultspec_rag

    sources = (
        (
            PublicSourceType.VAULT,
            PublicSourceType.CODE,
            PublicSourceType.DOCUMENT,
        )
        if source_type is PublicSourceType.COMBINED
        else (source_type,)
    )
    domains: dict[str, dict[str, object]] = {}
    for source in sources:
        try:
            cleared = await _run_in_thread(
                partial(vaultspec_rag.clean, root, clean_type=source.value)
            )
        except Exception as exc:
            logger.exception("Index clean failed for %s", source.value)
            domains[source.value] = {
                "ok": False,
                "cleared": [],
                "error_kind": type(exc).__name__,
                "detail": str(exc),
            }
        else:
            domains[source.value] = {
                "ok": True,
                "cleared": cleared,
                "error_kind": None,
                "detail": None,
            }
    successes = sum(bool(item["ok"]) for item in domains.values())
    return JSONResponse(
        {
            "ok": successes == len(domains),
            "partial": 0 < successes < len(domains),
            "domains": domains,
        },
        status_code=200 if successes else 409,
    )
