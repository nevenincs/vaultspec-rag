"""Reject browser authorities that cannot address this loopback service."""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


def _loopback_authority(value: str) -> tuple[str, int | None] | None:
    match = re.fullmatch(
        r"(localhost|(?:[0-9]{1,3}\.){3}[0-9]{1,3}|\[::1\])(?::([0-9]{1,5}))?",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    host, port_text = match.groups()
    host = host.lower()
    if host not in {"localhost", "[::1]"}:
        try:
            if not IPv4Address(host).is_loopback:
                return None
        except ValueError:
            return None
    port = int(port_text) if port_text is not None else None
    if port is not None and not 1 <= port <= 65535:
        return None
    return host, port


class LoopbackHTTPBoundary:
    """Enforce Host and same-origin browser checks before any route runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hosts = [v for k, v in scope["headers"] if k.lower() == b"host"]
        origins = [v for k, v in scope["headers"] if k.lower() == b"origin"]
        authority = (
            _loopback_authority(hosts[0].decode("latin-1")) if len(hosts) == 1 else None
        )
        if authority is None:
            response = JSONResponse(
                {"ok": False, "error": "invalid_host"}, status_code=403
            )
        elif len(origins) > 1 or (
            origins and not self._matching_origin(origins[0], authority, scope)
        ):
            response = JSONResponse(
                {"ok": False, "error": "invalid_origin"}, status_code=403
            )
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)

    @staticmethod
    def _matching_origin(
        raw: bytes, authority: tuple[str, int | None], scope: Scope
    ) -> bool:
        origin = raw.decode("latin-1")
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        scheme = scope.get("scheme", "http")
        if scheme not in {"http", "https"} or parsed.scheme != scheme:
            return False
        if origin != f"{scheme}://{parsed.netloc}":
            return False
        source = _loopback_authority(parsed.netloc)
        default_port = 443 if scheme == "https" else 80
        return source is not None and (source[0], source[1] or default_port) == (
            authority[0],
            authority[1] or default_port,
        )
