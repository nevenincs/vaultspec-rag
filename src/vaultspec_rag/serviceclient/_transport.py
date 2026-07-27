"""Import-light HTTP wire client for the resident RAG service.

Both the CLI and the MCP consume this one transport. It exposes two entry
points with deliberately different failure contracts, and a caller must know
which one it is using:

- :func:`_do_http_call` is the general path. It reads ``service.json`` for the
  bearer token, returns the decoded daemon JSON, and RAISES on a
  connection-level failure. The ``_try_http_*`` wrappers around it discriminate
  "service unreachable" (connection refused -> ``None``) from "live but broken"
  (a structured ``ok=False`` error dict); :func:`_is_connection_refused` walks
  the exception chain to make that call.
- :func:`_try_http_health` is the health probe, and it NEVER RAISES. It returns
  the parsed body, a structured error carrying the HTTP code when the service
  answers unhealthily, or ``None`` when it cannot be reached. Its callers sit in
  lifecycle verbs that must emit exactly one structured outcome on every exit
  path, so an escaping exception there would become a second one.

Every request from either entry point goes through one redirect-refusing opener:
this transport addresses only loopback, no service route emits a 3xx, and the
standard library would otherwise copy the bearer credential onto whatever host a
redirect named.

This module imports only stdlib, the lightweight filter validator from
``..search._validation`` (which itself imports nothing heavy), and the settings
module for the request bounds below. It loads no Torch, no models, and no
store, so importing it is import-light. Both real entry points, the CLI and the
MCP, have already loaded the settings module before they reach this one.
"""

from __future__ import annotations

import errno
import json
import logging
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from .._loopback_http import LOOPBACK_OPENER
from .._operator_commands import server_jobs_command, server_status_command
from .._source_types import PublicSourceType, SourceTypeParseError, parse_source_type
from ..config import get_config, rag_default

if TYPE_CHECKING:
    # The job-source vocabulary has one declaration, the canonical enum.
    # Annotation-only, so the client does not import the domain at runtime.
    from ..job_models import DesiredJobState, JobMode, JobSource
    from ._discovery import MachineResolution

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_HEALTH_TIMEOUT_SECONDS",
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "MAX_SERVICE_RESPONSE_BYTES",
    "ServiceUnavailableError",
    "_do_http_call",
    "_get_search_timeout",
    "_is_connection_refused",
    "_logs_route_path",
    "_timeout_diagnostics",
    "_try_http_admin",
    "_try_http_clean",
    "_try_http_code_file",
    "_try_http_create_job",
    "_try_http_delete_job",
    "_try_http_get_job",
    "_try_http_health",
    "_try_http_reindex",
    "_try_http_retry_job",
    "_try_http_search",
    "_try_http_set_job_desired_state",
    "_try_http_vault_document",
    "resolve_service_port",
]

#: Client-side request bounds. The values live in the settings defaults so the
#: settings object stays the one home for them; these names remain because
#: callers and tests import them.
DEFAULT_SEARCH_TIMEOUT_SECONDS: float = float(
    rag_default("service_search_timeout_seconds")
)
DEFAULT_ADMIN_TIMEOUT_SECONDS: float = float(
    rag_default("service_admin_timeout_seconds")
)
#: Bound for the health probe. Matches the command-line probe it replaces, so
#: repointed call sites wait exactly as long as they did before.
DEFAULT_HEALTH_TIMEOUT_SECONDS = 5.0
MAX_SERVICE_RESPONSE_BYTES = 8 * 1024 * 1024

type ReindexType = PublicSourceType | str
type ReindexInitiator = Literal["cli", "mcp"]
type DocumentSearchFilters = dict[str, str | None]
type HTTPMethod = Literal["GET", "POST", "PUT", "DELETE"]
type JobControlMode = Literal["graceful", "force"]


class ServiceUnavailableError(RuntimeError):
    """No usable service address, carrying the discovery evidence behind it.

    Raised instead of returning a bare "service down": a live singleton holder
    whose published address cannot be trusted is a different operator problem
    from a machine with nothing running, and the caller cannot tell them apart
    from an absent port alone.
    """

    def __init__(self, resolution: MachineResolution) -> None:
        self.resolution = resolution
        super().__init__(resolution.evidence())

    @property
    def is_degraded(self) -> bool:
        """Whether a live holder exists whose publication was refused."""
        return self.resolution.is_degraded

    @property
    def reason(self) -> str | None:
        """The named refusal reason, when the resolution was degraded."""
        return self.resolution.reason

    @property
    def holder_pid(self) -> int:
        """The live singleton holder, or zero when none is held."""
        return self.resolution.holder_pid


def resolve_service_port() -> int:
    """Return the live service port, or raise with the discovery evidence.

    There is deliberately no compatibility fallback here: when a holder owns
    the singleton but its pointer is untrustworthy, guessing an address would
    send the caller to a service the owner never advertised. Failing fast with
    the holder and pointer evidence is what lets a caller report the actual
    condition instead of an opaque connection failure.
    """
    from ._discovery import resolve_machine_service

    resolution = resolve_machine_service()
    if resolution.is_ready and resolution.port is not None:
        return resolution.port
    raise ServiceUnavailableError(resolution)


class ServiceResponseTooLargeError(ValueError):
    """Raised before a service response can exceed the client memory bound."""


def _read_service_response(response: Any) -> bytes:
    """Read at most one byte beyond the finite service-response ceiling."""
    raw = cast("bytes", response.read(MAX_SERVICE_RESPONSE_BYTES + 1))
    if len(raw) > MAX_SERVICE_RESPONSE_BYTES:
        raise ServiceResponseTooLargeError(
            "service response exceeded the "
            f"{MAX_SERVICE_RESPONSE_BYTES}-byte client limit"
        )
    return raw


def _is_connection_refused(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ConnectionRefusedError):
            return True
        if isinstance(reason, OSError) and getattr(reason, "errno", None) in (
            errno.ECONNREFUSED,
            getattr(errno, "WSAECONNREFUSED", 10061),
        ):
            return True
    return bool(isinstance(exc, ConnectionRefusedError))


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | socket.timeout):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, TimeoutError | socket.timeout)
    return False


def _resolve_timeout(
    timeout: float | None,
    *,
    setting: str,
    label: str,
    default: float,
) -> float:
    """Return a call bound, resolved leniently from the settings.

    An unusable configured bound - malformed, empty, non-finite or
    non-positive - degrades to the shipped default rather than raising, so an
    operator typo slows nothing down and turns no call into a crash. The
    degrade is logged; see :func:`_warn_unusable_settings`.

    The admin and search bounds resolved this identically, differing only in
    which setting they read, the word in the warning, and which default they
    fall back to.
    """
    resolved = timeout
    if timeout is None:
        try:
            resolved = float(getattr(get_config(), setting))
        except (TypeError, ValueError) as exc:
            _warn_unusable_settings(label, exc)
            return default
    if resolved is None or not math.isfinite(resolved) or resolved <= 0:
        return default
    return resolved


def _get_admin_timeout(timeout: float | None = None) -> float:
    """Return the admin-call bound."""
    return _resolve_timeout(
        timeout,
        setting="service_admin_timeout_seconds",
        label="admin",
        default=DEFAULT_ADMIN_TIMEOUT_SECONDS,
    )


def _format_timeout_seconds(timeout: float) -> str:
    value = f"{timeout:g}"
    noun = "second" if timeout == 1 else "seconds"
    return f"{value} {noun}"


def _status_file_token() -> str:
    """Return the ``service_token`` recorded in the local status file, or ``""``."""
    from ._discovery import _read_service_status

    status = _read_service_status()
    if not status:
        return ""
    token = status.get("service_token", status.get("token", ""))
    return token if isinstance(token, str) else ""


def _try_http_health(
    port: int, timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """Probe the ungated ``/health`` route, distinguishing down from unhealthy.

    This is the single owner of the health call. It deliberately does not share
    the general entry point's contract: callers here branch on a sentinel rather
    than catch an exception, because several of them sit inside lifecycle verbs
    that must emit exactly one structured outcome on every exit path, and an
    escaping exception would become a second one.

    ``/health`` is ungated, so no credential is sent and no token-recovery retry
    is needed; the request goes through the same redirect-refusing opener as
    every other call this module makes.

    Args:
        port: TCP port to probe on ``127.0.0.1``.
        timeout: Bounded maximum wait. There is no unbounded option.

    Returns:
        The parsed body when the service answers; a structured mapping carrying
        ``status`` ``"error"`` and the ``http_code`` when it answers unhealthily
        (the service is up, so this is not the same as unreachable); or ``None``
        when it cannot be reached at all. Never raises.
    """
    url = f"http://127.0.0.1:{port}/health"
    try:
        with LOOPBACK_OPENER.open(url, timeout=timeout) as resp:
            parsed: object = json.loads(_read_service_response(resp).decode("utf-8"))
        if not isinstance(parsed, dict):
            # Valid JSON that is not an object is not a health answer. Passing
            # it through would hand every caller a value they immediately treat
            # as a mapping, and the callers inside the lifecycle verbs would
            # raise where they must instead emit one structured outcome. A peer
            # answering this way is not the service, so it reads as unreachable.
            logger.debug(
                "health probe on port=%d returned a non-object body (%s)",
                port,
                type(parsed).__name__,
            )
            return None
        return cast("dict[str, Any]", parsed)
    except urllib.error.HTTPError as exc:
        # The service answered, so report the code rather than "unreachable" -
        # a caller must be able to tell a sick daemon from an absent one.
        return {"status": "error", "http_code": exc.code}
    except Exception as exc:
        # Connection refused, timeout, a refused redirect, or a body that is not
        # JSON all mean "no usable answer". The breadth is deliberate because
        # urllib raises many distinct classes here; the debug log keeps the
        # swallow observable rather than silent.
        logger.debug("health probe failed for port=%d: %s", port, exc, exc_info=True)
        return None


def _fetch_health_token(port: int, timeout: float | None = None) -> str:
    """Read the live ``service_token`` from the target port's ``/health``.

    ``/health`` is ungated and echoes the running service's per-process
    ``service_token``, so a CLI invocation that points ``--port`` at a service
    started out-of-band (e.g. by another project, under a different status
    directory) can still authenticate against the token-gated routes. Returns
    ``""`` on any failure - including connection refused - so the caller's
    normal request still runs and the existing unreachable/error handling
    applies.
    """
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with LOOPBACK_OPENER.open(
            req, timeout=timeout or DEFAULT_ADMIN_TIMEOUT_SECONDS
        ) as resp:
            data: object = json.loads(_read_service_response(resp).decode("utf-8"))
    except Exception as exc:
        if _is_timeout(exc):
            raise
        logger.debug("health token probe on port %s failed: %s", port, exc)
        return ""
    if isinstance(data, dict):
        token = cast("dict[str, object]", data).get("service_token")
        if isinstance(token, str):
            return token
    return ""


def _build_call_request(
    port: int,
    path: str,
    payload: dict[str, object] | None,
    token: str,
    *,
    method: HTTPMethod | None = None,
    extra_headers: dict[str, str] | None = None,
) -> urllib.request.Request:
    url = f"http://127.0.0.1:{port}{path}"
    headers = dict(extra_headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resolved_method: HTTPMethod = method or ("POST" if payload is not None else "GET")
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=resolved_method,
        )
    return urllib.request.Request(url, headers=headers, method=resolved_method)


def _send_call(
    req: urllib.request.Request, timeout: float | None
) -> tuple[int, dict[str, object]]:
    """Send *req*; return ``(status_code, parsed_body)``.

    HTTP error responses (e.g. a 401 from the token gate) are parsed and
    returned alongside their status code rather than raised, so the caller can
    react to a 401 by refreshing the token. Connection-level failures still
    propagate to the caller's unreachable handling.
    """
    try:
        with LOOPBACK_OPENER.open(req, timeout=timeout) as resp:
            body = cast(
                "dict[str, object]",
                json.loads(_read_service_response(resp).decode("utf-8")),
            )
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        raw = _read_service_response(e).decode("utf-8")
        try:
            return e.code, cast("dict[str, object]", json.loads(raw))
        except json.JSONDecodeError:
            detail = raw.strip() or "(empty response body)"
            return e.code, {
                "ok": False,
                "error": "http_error",
                "http_code": e.code,
                "message": (
                    f"HTTP {e.code} from {req.full_url} with a non-JSON body: "
                    f"{detail}. This usually means the request reached a service "
                    "that is not the vaultspec-rag daemon (for example the Qdrant "
                    "port). Confirm the running service with `vaultspec-rag server "
                    "status`."
                ),
            }


def _raise_deadline_exhausted(
    exc: Exception,
    *,
    stage: str,
    timeout: float | None,
    started: float,
    deadline: float | None,
) -> NoReturn:
    """Re-raise *exc* as a deadline-exhausted TimeoutError, or propagate it.

    A non-timeout failure, or a call with no deadline, propagates unchanged;
    otherwise the original is wrapped with the stage and remaining budget so
    the caller can see which leg of the exchange ran out of time.
    """
    if not _is_timeout(exc) or timeout is None:
        raise exc
    value = max(0.0, (deadline or started) - time.monotonic())
    raise TimeoutError(
        f"whole HTTP call deadline={timeout:.3f}s exhausted "
        f"during {stage}; elapsed={time.monotonic() - started:.3f}s "
        f"remaining={value:.3f}s"
    ) from exc


def _do_http_call(
    port: int,
    path: str,
    payload: dict[str, object] | None,
    timeout: float | None = None,
    *,
    method: HTTPMethod | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Call a service route, recovering the auth token on a 401.

    The token from the local status file is sent first (it may be empty or
    stale). Only if the route rejects it with 401 does the client fetch the
    live token from the target port's ungated ``/health`` and retry once. This
    keeps the happy path a single request while letting ``--port`` authenticate
    against a service started out-of-band (missing status file) or restarted
    (rotated token), without an extra round-trip when the first call succeeds.

    An omitted or ``None`` timeout resolves through the administrative timeout
    policy rather than to no bound at all, so the operator override applies here
    exactly as it does to the admin helpers. An unbounded network call has no
    defensible use here: it can wait forever on a wedged peer, and because these
    requests carry the service bearer credential, an unbounded wait is also an
    unbounded window in which that credential is in flight. A caller needing a
    different bound passes one explicitly; there is deliberately no way to ask
    for none, and a non-finite or non-positive request resolves to the default
    rather than to an immediately-expired deadline.
    """
    resolved_timeout = _get_admin_timeout(timeout)
    deadline = time.monotonic() + resolved_timeout
    started = time.monotonic()

    def remaining(stage: str) -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError(
                f"whole HTTP call deadline={resolved_timeout:.3f}s exceeded "
                f"during {stage}; elapsed={time.monotonic() - started:.3f}s "
                "remaining=0.000s"
            )
        return value

    def send(stage: str, token: str) -> tuple[int, dict[str, object]]:
        try:
            return _send_call(
                _build_call_request(
                    port,
                    path,
                    payload,
                    token,
                    method=method,
                    extra_headers=headers,
                ),
                remaining(stage),
            )
        except Exception as exc:
            _raise_deadline_exhausted(
                exc,
                stage=stage,
                timeout=resolved_timeout,
                started=started,
                deadline=deadline,
            )

    token = _status_file_token()
    status_code, result = send("initial request", token)
    remaining("initial response")

    if status_code == 401:
        try:
            fresh = _fetch_health_token(port, remaining("health-token request"))
        except Exception as exc:
            _raise_deadline_exhausted(
                exc,
                stage="health-token request",
                timeout=resolved_timeout,
                started=started,
                deadline=deadline,
            )
        remaining("health-token response")
        if fresh and fresh != token:
            logger.debug(
                "token rejected on port %s; retrying with the /health token", port
            )
            _, result = send("authenticated retry", fresh)
            remaining("authenticated retry response")
    return result


def _try_http_reindex(
    reindex_type: ReindexType,
    clean: bool,
    port: int,
    project_root: str,
    *,
    initiator_kind: ReindexInitiator,
) -> dict[str, object] | None:
    try:
        source = parse_source_type(reindex_type, allow_aliases=True)
    except SourceTypeParseError as exc:
        return exc.as_error_envelope()
    try:
        payload: dict[str, object] = {
            "type": source.value,
            "clean": clean,
            "project_root": project_root,
            "initiator_kind": initiator_kind,
        }
        res = _do_http_call(port, "/reindex", payload)
        if res is not None:
            return res
        return {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP reindex on port %s: connection refused (%s)", port, exc)
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP reindex on port {port} failed: {cls}: {exc}",
        }


def _try_http_clean(
    clean_type: ReindexType,
    port: int,
    project_root: str,
) -> dict[str, object] | None:
    """Clean one canonical domain through the resident service."""
    try:
        source = parse_source_type(clean_type, allow_aliases=True)
    except SourceTypeParseError as exc:
        return exc.as_error_envelope()
    try:
        result = _do_http_call(
            port,
            "/clean",
            {"type": source.value, "project_root": project_root},
            timeout=_get_admin_timeout(None),
        )
        return result if result is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP clean on port %s: connection refused (%s)", port, exc)
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP clean on port {port} failed: {cls}: {exc}",
        }


def _job_path(job_id: str, suffix: str = "") -> str:
    return f"/jobs/{urllib.parse.quote(job_id, safe='')}{suffix}"


def _try_http_job_call(
    port: int | None,
    path: str,
    method: HTTPMethod,
    *,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    if port is None:
        return None
    resolved_timeout = _get_admin_timeout(timeout)
    try:
        result = _do_http_call(
            port,
            path,
            payload,
            timeout=resolved_timeout,
            method=method,
            headers=headers,
        )
        return result if result is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP job call on port %s: connection refused (%s)", port, exc)
            return None
        if _is_timeout(exc):
            return {
                "ok": False,
                "error": "admin_timeout",
                "message": (
                    f"The service on port {port} did not answer within "
                    f"{_format_timeout_seconds(resolved_timeout)}. "
                    f"Deadline diagnostics: {exc}"
                ),
            }
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP job call on port {port} failed: {cls}: {exc}",
        }


def _default_job_mode() -> str:
    """Return the convergence mode a job takes when the caller names none."""
    from ..job_models import JobMode

    return JobMode.INCREMENTAL.value


def _try_http_create_job(
    source: JobSource,
    project_root: str,
    port: int | None,
    *,
    mode: JobMode | None = None,
    start_paused: bool = False,
    initiator_kind: str = "cli",
    command: str = "server_job_create",
    idempotency_key: str | None = None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    payload: dict[str, object] = {
        "operation": "index",
        "source": source,
        "project_root": project_root,
        # Resolved here, not in the signature: the enum is annotation-only in
        # this module so the client keeps the domain out of its import graph.
        "mode": mode if mode is not None else _default_job_mode(),
        "start_paused": start_paused,
        "initiator": {"kind": initiator_kind, "command": command},
    }
    headers = (
        {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
    )
    return _try_http_job_call(
        port,
        "/jobs",
        "POST",
        payload=payload,
        headers=headers,
        timeout=timeout,
    )


def _try_http_get_job(
    job_id: str,
    port: int | None,
    *,
    timeout: float | None = None,
) -> dict[str, object] | None:
    return _try_http_job_call(
        port,
        _job_path(job_id),
        "GET",
        timeout=timeout,
    )


def _try_http_set_job_desired_state(
    job_id: str,
    state: DesiredJobState,
    port: int | None,
    *,
    expected_revision: int | None = None,
    mode: JobControlMode = "graceful",
    timeout: float | None = None,
) -> dict[str, object] | None:
    payload: dict[str, object] = {"state": state, "mode": mode}
    if expected_revision is not None:
        payload["expected_revision"] = expected_revision
    return _try_http_job_call(
        port,
        _job_path(job_id, "/desired-state"),
        "PUT",
        payload=payload,
        timeout=timeout,
    )


def _try_http_retry_job(
    job_id: str,
    port: int | None,
    *,
    initiator_kind: str = "cli",
    command: str = "server_job_retry",
    timeout: float | None = None,
) -> dict[str, object] | None:
    return _try_http_job_call(
        port,
        _job_path(job_id, "/retry"),
        "POST",
        payload={"initiator": {"kind": initiator_kind, "command": command}},
        timeout=timeout,
    )


def _try_http_delete_job(
    job_id: str,
    port: int | None,
    *,
    timeout: float | None = None,
) -> dict[str, object] | None:
    return _try_http_job_call(
        port,
        _job_path(job_id),
        "DELETE",
        timeout=timeout,
    )


def _admin_url_with_root(base: str, args: dict[str, Any]) -> str:
    """Append ?project_root=... to base when args contains it."""
    project_root = args.get("project_root")
    if project_root:
        return base + "?project_root=" + urllib.parse.quote(str(project_root))
    return base


_LOGS_PARAMS = {"lines", "source", "job_id", "contains"}


def _bounded_route_path(base: str, args: dict[str, Any], allowed: set[str]) -> str:
    """Append the allowlisted, non-``None`` entries of ``args`` to ``base``."""
    params = {
        key: value
        for key, value in args.items()
        if key in allowed and value is not None
    }
    if params:
        base += "?" + urllib.parse.urlencode(params)
    return base


def _logs_route_path(args: dict[str, Any]) -> str:
    """Build the grouped JSON logs route with source and bounded filters.

    The daemon's ``/logs/json`` route returns source-tagged groups which the
    JSON-parsing ``_do_http_call`` can decode. The plaintext ``/logs`` route is
    for direct human inspection and is not an admin-transport payload.
    """
    return _bounded_route_path("/logs/json", args, _LOGS_PARAMS)


# GET admin tools that accept only an optional ``?project_root=`` query.
_GET_ROOT_ROUTES: dict[str, str] = {
    "list_projects": "/projects",
    "get_watcher_state": "/watcher",
    "get_service_state": "/service-state",
}

# POST admin tools whose full ``args`` dict is the JSON body.
_POST_BODY_ROUTES: dict[str, str] = {
    "get_code_file": "/code-file",
    "get_vault_document": "/vault-document",
    "evict_project": "/projects/evict",
    "pause_service": "/pause",
    "resume_service": "/resume",
}

_JOBS_PARAMS = {
    "controllable",
    "desired_state",
    "limit",
    "phase",
    "source",
    "trigger",
    "query",
    "failed",
    "job_id",
    "since",
    "state",
}


def _jobs_route_path(args: dict[str, Any]) -> str:
    """Build the ``/jobs`` route path with its bounded query filters."""
    return _bounded_route_path("/jobs", args, _JOBS_PARAMS)


_STORAGE_SURVEY_PARAMS = {"status", "limit", "root", "fresh"}


def _storage_survey_route_path(args: dict[str, Any]) -> str:
    """Build the ``/storage/survey`` route path with its bounded filters."""
    return _bounded_route_path("/storage/survey", args, _STORAGE_SURVEY_PARAMS)


def _resolve_admin_call(
    tool_name: str, args: dict[str, Any]
) -> tuple[str, dict[str, Any] | None] | None:
    """Resolve an admin tool to its ``(path, body)`` pair, or ``None`` if unknown."""
    if tool_name == "get_logs":
        return _logs_route_path(args), None
    if tool_name == "get_jobs":
        return _jobs_route_path(args), None
    if tool_name == "get_storage_survey":
        return _storage_survey_route_path(args), None
    if tool_name in _GET_ROOT_ROUTES:
        return _admin_url_with_root(_GET_ROOT_ROUTES[tool_name], args), None
    if tool_name in _POST_BODY_ROUTES:
        return _POST_BODY_ROUTES[tool_name], args
    if tool_name in ("start_watcher", "stop_watcher", "reconfigure_watcher"):
        verb = tool_name.split("_")[0]
        return f"/watcher/{verb}", args
    return None


def _route_admin_tool(
    tool_name: str,
    args: dict[str, Any],
    port: int,
) -> dict[str, Any] | None:
    """Map an admin tool name to an HTTP call and return the raw result."""
    raw_timeout = args.get("_timeout")
    timeout = float(raw_timeout) if isinstance(raw_timeout, int | float) else None
    args = {key: value for key, value in args.items() if key != "_timeout"}
    resolved = _resolve_admin_call(tool_name, args)
    if resolved is None:
        return {
            "ok": False,
            "error": "unknown_admin_tool",
            "message": f"Tool {tool_name} not mapped",
        }
    path, body = resolved
    return _do_http_call(port, path, body, timeout=timeout)


def _try_http_admin(
    tool_name: str,
    args: dict[str, Any],
    port: int | None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    if port is None:
        return None
    resolved_timeout = _get_admin_timeout(timeout)
    try:
        res = _route_admin_tool(tool_name, {**args, "_timeout": resolved_timeout}, port)
        return res if res is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "HTTP admin call on port %s: connection refused (%s)", port, exc
            )
            return None
        if _is_timeout(exc):
            logger.debug(
                "HTTP admin call on port %s timed out after %ss",
                port,
                resolved_timeout,
            )
            return {
                "ok": False,
                "error": "admin_timeout",
                "message": (
                    f"The service on port {port} did not answer within "
                    f"{_format_timeout_seconds(resolved_timeout)}. "
                    f"Deadline diagnostics: {exc}"
                ),
            }
        logger.debug(
            "HTTP admin call on port %s raised non-refused exception",
            port,
            exc_info=True,
        )
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP admin call on port {port} failed: {cls}: {exc}",
        }


def _try_http_code_file(
    path: str,
    project_root: str,
    port: int | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """Fetch a code file's contents from the daemon's ``/code-file`` route.

    Thin forwarder over :func:`_do_http_call` with no business logic; mirrors
    the admin-call discrimination (refused -> ``None``).
    """
    return _try_http_admin(
        "get_code_file",
        {"path": path, "project_root": project_root},
        port,
        timeout=timeout,
    )


def _try_http_vault_document(
    doc_id: str,
    project_root: str,
    port: int | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """Fetch a vault document from the daemon's ``/vault-document`` route.

    Thin forwarder over :func:`_do_http_call` with no business logic; mirrors
    the admin-call discrimination (refused -> ``None``). Empty ``project_root``
    is omitted so the daemon resolves its default root.
    """
    args: dict[str, Any] = {"doc_id": doc_id}
    if project_root:
        args["project_root"] = project_root
    return _try_http_admin(
        "get_vault_document",
        args,
        port,
        timeout=timeout,
    )


def _warn_unusable_settings(bound: str, exc: BaseException) -> None:
    """Report a settings failure that a request bound is about to absorb.

    The settings object validates every value when it is built, so the
    failure this absorbs is frequently NOT about the bound being resolved -
    one malformed variable anywhere makes the whole object unbuildable. The
    two callers must not raise: they sit under a health probe whose contract
    is that it never does, and under lifecycle verbs that must emit exactly
    one outcome. Degrading is therefore right, but degrading in silence would
    hide a rejected setting behind a request that appears to work, which is
    the failure mode the validation exists to prevent. So it degrades loudly,
    and names the real cause rather than implying the bound itself was bad.
    """
    logger.warning(
        "using the default %s bound: the settings could not be read (%s). "
        "The rejected value may belong to any setting, not this bound.",
        bound,
        exc,
    )


def _get_search_timeout(timeout: float | None) -> float:
    """Return the search-call bound."""
    return _resolve_timeout(
        timeout,
        setting="service_search_timeout_seconds",
        label="search",
        default=DEFAULT_SEARCH_TIMEOUT_SECONDS,
    )


def document_search_filters(
    *,
    source_path: str | None,
    extractor_id: str | None,
    extractor_version: str | None,
    locator_kind: str | None,
) -> DocumentSearchFilters:
    """Return the document filter mapping the service accepts.

    Three call sites - the CLI search verb and both MCP document tools - built
    this dict from the same four arguments. The keys are the schema's
    DOCUMENT_FILTER_KEYS; what was copied is the projection of arguments onto
    them, so a fifth filter would have had to be remembered in three places.
    """
    return {
        "source_path": source_path,
        "extractor_id": extractor_id,
        "extractor_version": extractor_version,
        "locator_kind": locator_kind,
    }


def _probe_unavailable(kind: str, exc: Exception) -> dict[str, object]:
    logger.debug("%s diagnostic probe failed: %s", kind, exc, exc_info=True)
    return {
        "available": False,
        "error": exc.__class__.__name__,
        "message": str(exc),
    }


def _running_jobs_summary(port: int) -> dict[str, object]:
    try:
        jobs = _do_http_call(port, "/jobs?limit=5&phase=running", None, timeout=1.0)
    except Exception as exc:
        return _probe_unavailable("jobs", exc)
    if not isinstance(jobs, dict):
        return {"available": False}
    if jobs.get("ok") is False:
        return {
            "available": False,
            "error": jobs.get("error", "service_error"),
            "message": jobs.get("message", "Jobs probe returned an error."),
        }
    raw_jobs = jobs.get("jobs")
    summary = jobs.get("summary")
    running_count: object = jobs.get("returned", 0)
    if isinstance(summary, dict):
        running_count = cast("dict[str, object]", summary).get("running", running_count)
    return {
        "available": True,
        "running_count": running_count,
        "jobs": raw_jobs if isinstance(raw_jobs, list) else [],
    }


def _health_summary(port: int) -> dict[str, object]:
    try:
        health = _do_http_call(port, "/health", None, timeout=1.0)
    except Exception as exc:
        return _probe_unavailable("health", exc)
    if not isinstance(health, dict):
        return {"available": False}
    if health.get("ok") is False:
        return {
            "available": False,
            "error": health.get("error", "service_error"),
            "message": health.get("message", "Readiness check returned an error."),
        }
    return {
        "available": True,
        "status": health.get("status", "unknown"),
        "project_count": health.get("project_count", 0),
        "backend_capabilities": health.get("backend_capabilities", {}),
    }


def _active_indexing_conflict(running_count: object) -> bool | None:
    if isinstance(running_count, bool):
        return None
    if isinstance(running_count, int):
        return running_count > 0
    if isinstance(running_count, str):
        try:
            return int(running_count) > 0
        except ValueError:
            return None
    return None


def _timeout_diagnostics(port: int, timeout: float) -> dict[str, object]:
    health = _health_summary(port)
    jobs = _running_jobs_summary(port)
    raw_caps = health.get("backend_capabilities")
    caps: dict[str, object] = (
        cast("dict[str, object]", raw_caps) if isinstance(raw_caps, dict) else {}
    )
    running_count = jobs.get("running_count", "unknown")
    strategy = caps.get("same_project_search_strategy", "unknown")
    retry_timeout = max(DEFAULT_SEARCH_TIMEOUT_SECONDS, timeout * 2)
    return {
        "ok": False,
        "error": "http_search_timeout",
        "message": (
            f"The search request to the service on port {port} timed out "
            f"after {timeout:g} seconds. The service may still be working "
            "on that request; check service status and active index jobs "
            "before retrying."
        ),
        "port": port,
        "timeout_seconds": timeout,
        "backend_capabilities": caps,
        "diagnostics": {
            "health": health,
            "jobs": jobs,
            "backpressure": {
                "same_project_search_strategy": strategy,
                "active_indexing_conflict": _active_indexing_conflict(running_count),
                "observation": "jobs endpoint snapshot",
            },
        },
        "remediation": [
            server_status_command(port),
            server_jobs_command(port),
            f"Rerun the same search with --timeout {retry_timeout:g}",
        ],
    }


def _build_http_search_payload(
    query: str,
    search_type: str,
    top_k: int,
    project_root: str,
    language: str | None,
    path: str | None,
    node_type: str | None,
    function_name: str | None,
    class_name: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    intent: str | None,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool | None,
    prefer: str | None,
    like_ids: list[str | int] | None,
    unlike_ids: list[str | int] | None,
    document_filters: DocumentSearchFilters | None,
) -> dict[str, object]:
    source = parse_source_type(search_type, allow_aliases=True)
    payload: dict[str, object] = {
        "query": query,
        "top_k": top_k,
        "project_root": project_root,
        "type": source.value,
    }
    if like_ids:
        payload["like_ids"] = list(like_ids)
    if unlike_ids:
        payload["unlike_ids"] = list(unlike_ids)
    selected_filters: dict[str, object | None] = {}
    if source in {PublicSourceType.CODE, PublicSourceType.COMBINED}:
        selected_filters.update(
            {
                "language": language,
                "path": path,
                "node_type": node_type,
                "function_name": function_name,
                "class_name": class_name,
            }
        )
        if include_paths:
            payload["include_paths"] = list(include_paths)
        if exclude_paths:
            payload["exclude_paths"] = list(exclude_paths)
        # Tri-state: only send when the caller set it explicitly, so the server
        # resolves the configured default when it is absent.
        if dedup_locales is not None:
            payload["dedup_locales"] = bool(dedup_locales)
        if prefer is not None:
            payload["prefer"] = prefer
    if source in {PublicSourceType.VAULT, PublicSourceType.COMBINED}:
        selected_filters.update(
            {
                "doc_type": doc_type,
                "feature": feature,
                "date": date,
                "tag": tag,
                "intent": intent,
            }
        )
    if source in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}:
        selected_filters.update(document_filters or {})
    for key, value in selected_filters.items():
        if value is not None:
            payload[key] = value
    return payload


def _invalid_search_service_response(port: int) -> dict[str, object]:
    """Return the stable failure envelope for a malformed search response."""
    return {
        "ok": False,
        "error": "invalid_service_response",
        "message": (
            f"HTTP search on port {port} returned an invalid service response; "
            "expected a non-empty JSON object envelope containing results or "
            "a structured error."
        ),
    }


def _search_response_envelope(response: object, port: int) -> dict[str, object]:
    """Return a valid search envelope or the stable malformed-response error."""
    if isinstance(response, dict) and response:
        envelope = cast("dict[str, object]", response)
        if envelope.get("ok") is False or isinstance(envelope.get("results"), list):
            return envelope
    return _invalid_search_service_response(port)


def _try_http_search(
    query: str,
    search_type: str,
    top_k: int,
    port: int,
    project_root: str,
    *,
    timeout: float | None = None,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    intent: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool | None = None,
    prefer: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    document_filters: DocumentSearchFilters | None = None,
) -> dict[str, object] | None:
    # Import the lightweight validator from the leaf module rather than the
    # ``..search`` package, whose __init__ pulls the heavy VaultSearcher (and
    # thus store/embeddings). ``_validation`` imports only stdlib, so this keeps
    # the service-client transport import-light.
    from ..search._validation import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        validate_search_filters,
    )

    try:
        source = parse_source_type(search_type, allow_aliases=True)
    except SourceTypeParseError as exc:
        return exc.as_error_envelope()

    if source in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED} and (
        like_ids or unlike_ids
    ):
        return {
            "ok": False,
            "error": "unsupported_feedback_for_search_type",
            "message": (
                f"feedback point ids are not supported for {source.value} search; "
                "omit like_ids and unlike_ids"
            ),
        }

    try:
        validate_search_filters(
            cast("Any", source.value),
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            source_path=(document_filters or {}).get("source_path"),
            extractor_id=(document_filters or {}).get("extractor_id"),
            extractor_version=(document_filters or {}).get("extractor_version"),
            locator_kind=(document_filters or {}).get("locator_kind"),
        )
    except InvalidFilterForSearchTypeError as exc:
        return {
            "ok": False,
            "error": "invalid_filter_for_search_type",
            "message": str(exc),
        }
    except InvalidPreferValueError as exc:
        return {"ok": False, "error": "invalid_prefer_value", "message": str(exc)}

    timeout = _get_search_timeout(timeout)
    payload = _build_http_search_payload(
        query,
        source.value,
        top_k,
        project_root,
        language,
        path,
        node_type,
        function_name,
        class_name,
        doc_type,
        feature,
        date,
        tag,
        intent,
        include_paths,
        exclude_paths,
        dedup_locales,
        prefer,
        like_ids,
        unlike_ids,
        document_filters,
    )

    try:
        response: object = _do_http_call(port, "/search", payload, timeout=timeout)
        return _search_response_envelope(response, port)
    except TimeoutError:
        logger.debug("HTTP search on port %s timed out after %ss", port, timeout)
        return _timeout_diagnostics(port, timeout)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, TimeoutError)
        ):
            return _timeout_diagnostics(port, timeout)
        if _is_connection_refused(exc):
            logger.debug("HTTP search on port %s: connection refused (%s)", port, exc)
            return None
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
            return _invalid_search_service_response(port)
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP search on port {port} failed: {cls}: {exc}",
        }
