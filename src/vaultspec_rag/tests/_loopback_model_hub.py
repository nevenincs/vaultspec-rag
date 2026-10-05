"""A loopback stand-in for the Hugging Face Hub that serves real snapshots.

The hub client fetches a snapshot in three kinds of request: the repository's
revision record, its file tree at that commit, and then a ``HEAD`` and a
``GET`` per file. This answers exactly those, over plain HTTP on loopback, for
a fixed set of small repositories whose files satisfy the product's own
completeness probe. Nothing about the client is replaced: a process pointed at
it through the hub's own endpoint variable downloads with the shipped client,
into whatever cache it was given.

The client reads its endpoint and cache location once, when it is first
imported, so the process that downloads has to be started with both in its
environment. :meth:`LoopbackModelHub.child_environment` builds that.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..config._types import EnvVar
from ._http_stubs import QuietHandler

if TYPE_CHECKING:
    from collections.abc import Collection, Generator
    from pathlib import Path

_COMMIT = "0123456789abcdef0123456789abcdef01234567"

#: The hub client's own cache-location variable. The product never reads it -
#: the client does - so this stand-in is its only reader here.
_HUB_CACHE_ENV = "HF_HUB_CACHE"

#: One snapshot's worth of files: what the completeness probe requires of an
#: ordinary repository, with a weight file large enough to arrive in chunks.
_FILES: dict[str, bytes] = {
    "config.json": b"{}",
    "tokenizer.json": b"{}",
    "model.safetensors": b"\0" * (256 << 10),
}


@dataclass
class LoopbackModelHub:
    """A running stand-in hub and what it has been asked.

    Attributes:
        endpoint: The base URL to hand the hub client.
        requests: ``(method, path)`` for every request received, in order.
    """

    endpoint: str
    requests: list[tuple[str, str]] = field(default_factory=list)

    def downloads_of(self, repo: str) -> list[str]:
        """Return the file names fetched with ``GET`` from *repo*."""
        prefix = f"/{repo}/resolve/"
        return [
            path.rsplit("/", 1)[-1]
            for method, path in self.requests
            if method == "GET" and path.startswith(prefix)
        ]

    def child_environment(self, cache: Path) -> dict[str, str]:
        """Build the environment for a process that downloads from this hub.

        The hub's offline switches are removed rather than inherited: a suite
        that runs offline would otherwise refuse the request before it left
        the client.
        """
        env = dict(os.environ)
        for switch in (EnvVar.HF_HUB_OFFLINE.value, EnvVar.TRANSFORMERS_OFFLINE.value):
            env.pop(switch, None)
        env[EnvVar.HF_ENDPOINT.value] = self.endpoint
        env[_HUB_CACHE_ENV] = str(cache)
        return env


def _send(
    handler: http.server.BaseHTTPRequestHandler,
    body: bytes,
    headers: dict[str, str],
) -> None:
    handler.send_response(http.HTTPStatus.OK)
    for name, value in headers.items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def _handler_for(
    hub: LoopbackModelHub, repos: Collection[str]
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Hub(QuietHandler):
        def do_HEAD(self) -> None:
            self._answer()

        def do_GET(self) -> None:
            self._answer()

        def _answer(self) -> None:
            path = self.path.split("?", 1)[0]
            hub.requests.append((self.command, path))
            for repo in repos:
                if path == f"/api/models/{repo}/revision/main":
                    record = {
                        "id": repo,
                        "modelId": repo,
                        "sha": _COMMIT,
                        "private": False,
                        "siblings": [{"rfilename": name} for name in _FILES],
                    }
                    _send(
                        self,
                        json.dumps(record).encode("utf-8"),
                        {"Content-Type": "application/json"},
                    )
                    return
                if path == f"/api/models/{repo}/tree/{_COMMIT}":
                    tree = [
                        {
                            "type": "file",
                            "path": name,
                            "size": len(content),
                            "oid": hashlib.sha1(
                                content, usedforsecurity=False
                            ).hexdigest(),
                        }
                        for name, content in _FILES.items()
                    ]
                    _send(
                        self,
                        json.dumps(tree).encode("utf-8"),
                        {"Content-Type": "application/json"},
                    )
                    return
                prefix = f"/{repo}/resolve/{_COMMIT}/"
                content = _FILES.get(path.removeprefix(prefix))
                if path.startswith(prefix) and content is not None:
                    _send(
                        self,
                        content,
                        {
                            "ETag": f'"{hashlib.sha256(content).hexdigest()}"',
                            "X-Repo-Commit": _COMMIT,
                        },
                    )
                    return
            self.send_response(http.HTTPStatus.NOT_FOUND)
            self.end_headers()

    return _Hub


@contextmanager
def loopback_model_hub(repos: Collection[str]) -> Generator[LoopbackModelHub]:
    """Serve complete snapshots of *repos* on loopback for the block."""
    hub = LoopbackModelHub(endpoint="")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(hub, repos))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    hub.endpoint = f"http://127.0.0.1:{int(server.server_address[1])}"
    try:
        yield hub
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
