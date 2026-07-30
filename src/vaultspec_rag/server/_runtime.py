"""Immutable request-scoped dependencies for the HTTP route surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.requests import Request

    from ..service import ServiceRegistry

__all__ = [
    "ServerRouteRuntime",
    "get_app_runtime",
    "get_request_runtime",
    "install_route_runtime",
]


@dataclass(frozen=True, slots=True)
class ServerRouteRuntime:
    """The immutable token and registry owned by one HTTP application."""

    token: str
    registry: ServiceRegistry

    def __post_init__(self) -> None:
        """Refuse route hosts that cannot authenticate their requests."""
        if not self.token:
            raise ValueError("server route runtime requires a non-empty service token")


class _RouteRuntimeState(Protocol):
    """The typed app-state slot owned by this module."""

    server_route_runtime: object


class _RuntimeApplication(Protocol):
    """The subset of a Starlette application needed to resolve the runtime."""

    state: _RouteRuntimeState


def install_route_runtime(app: Starlette, runtime: ServerRouteRuntime) -> None:
    """Install *runtime* as the HTTP application's immutable route authority."""
    runtime_app = cast("_RuntimeApplication", app)
    runtime_app.state.server_route_runtime = runtime


def get_app_runtime(app: Starlette) -> ServerRouteRuntime:
    """Resolve the runtime installed on *app*, rejecting absent or invalid state."""
    runtime_app = cast("_RuntimeApplication", app)
    try:
        runtime = runtime_app.state.server_route_runtime
    except AttributeError as exc:
        raise RuntimeError(
            "HTTP application has no valid server route runtime"
        ) from exc
    if not isinstance(runtime, ServerRouteRuntime):
        raise RuntimeError("HTTP application has no valid server route runtime")
    return runtime


def get_request_runtime(request: Request) -> ServerRouteRuntime:
    """Return the current request's route runtime or fail closed."""
    return get_app_runtime(cast("Starlette", request.app))
