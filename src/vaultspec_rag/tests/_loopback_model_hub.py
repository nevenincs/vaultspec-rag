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

Only the hub's URL layout lives here. The sockets, and every way a transfer
can go wrong on one, belong to the shared loopback source module: a test that
wants a file's transfer to fail hands this hub one of that module's responders
for a repository's weight file.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING

from ..config._types import EnvVar
from ._loopback_tls import plain_loopback_sources

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Generator
    from pathlib import Path

    from ._http_stubs import QuietHandler

__all__ = ["WEIGHT_FILE", "LoopbackModelHub", "loopback_model_hub", "weight_bytes"]

_COMMIT = "0123456789abcdef0123456789abcdef01234567"

#: The hub client's own cache-location variable. The product never reads it -
#: the client does - so this stand-in is its only reader here.
_HUB_CACHE_ENV = "HF_HUB_CACHE"

#: The one file large enough to arrive in several chunks, and so the one a
#: test interferes with.
WEIGHT_FILE = "model.safetensors"

#: One snapshot's worth of files: what the completeness probe requires of an
#: ordinary repository.
_FILES: dict[str, bytes] = {
    "config.json": b"{}",
    "tokenizer.json": b"{}",
    WEIGHT_FILE: bytes(range(256)) * (1 << 10),
}


def weight_bytes() -> bytes:
    """Return the weight file every repository here serves.

    For a responder that sends part of it before interfering.
    """
    return _FILES[WEIGHT_FILE]


@dataclass
class LoopbackModelHub:
    """A running stand-in hub, what it serves, and what it has been asked.

    Attributes:
        repos: The repository ids this hub has; any other is answered the way
            the real hub answers an unknown repository.
        endpoint: The base URL to hand the hub client.
        requests: ``(method, path)`` for every request received, in order.
        declared_weight_size: Per repository, the size to declare for the
            weight file in place of its real one. The hub client sizes a
            download from this record before it fetches anything.
        weight_responders: Per repository, a responder that takes over the
            ``GET`` of the weight file. Absent, the file is served whole, or
            from the offset a ``Range`` header names.
        resumed_from: The offset of every weight-file ``GET`` that asked for
            the rest of a file it already held part of.
        commits: Per repository, the commit it is at, in place of the one
            fixed commit every other repository here shares. A repository is
            answered at its commit whether it is asked for by that id or as
            the default branch, which is what lets this hub stand in for a
            mirror serving a pinned release.
        files: Per repository, the files it holds, in place of the ordinary
            set. What a mirror serves under a pinned commit is the mirror's
            choice, and this is where a test makes that choice.
    """

    repos: tuple[str, ...]
    endpoint: str = ""
    requests: list[tuple[str, str]] = field(default_factory=list)
    commits: dict[str, str] = field(default_factory=dict)
    files: dict[str, dict[str, bytes]] = field(default_factory=dict)
    declared_weight_size: dict[str, int] = field(default_factory=dict)
    weight_responders: dict[str, Callable[[QuietHandler], None]] = field(
        default_factory=dict
    )
    resumed_from: list[int] = field(default_factory=list)

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

    def respond(self, handler: QuietHandler) -> None:
        """Answer one hub request, or refuse it the way the hub would."""
        path = handler.path.split("?", 1)[0]
        self.requests.append((handler.command, path))
        for repo in self.repos:
            commit = self._commit(repo)
            if path in {
                f"/api/models/{repo}",
                f"/api/models/{repo}/revision/main",
                f"/api/models/{repo}/revision/{commit}",
            }:
                _send_json(handler, self._record(repo))
                return
            if path == f"/api/models/{repo}/tree/{commit}":
                _send_json(handler, self._tree(repo))
                return
            prefix = f"/{repo}/resolve/{commit}/"
            name = path.removeprefix(prefix)
            if path.startswith(prefix) and name in self._held(repo):
                self._send_file(handler, repo, name)
                return
        code = "RevisionNotFound" if "/revision/" in path else "RepoNotFound"
        handler.send_response(HTTPStatus.NOT_FOUND)
        handler.send_header("X-Error-Code", code)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _commit(self, repo: str) -> str:
        return self.commits.get(repo, _COMMIT)

    def _held(self, repo: str) -> dict[str, bytes]:
        return self.files.get(repo, _FILES)

    def _size(self, repo: str, name: str) -> int:
        if name == WEIGHT_FILE and repo in self.declared_weight_size:
            return self.declared_weight_size[repo]
        return len(self._held(repo)[name])

    def _record(self, repo: str) -> dict[str, object]:
        return {
            "id": repo,
            "modelId": repo,
            "sha": self._commit(repo),
            "private": False,
            "siblings": [
                {"rfilename": name, "size": self._size(repo, name)}
                for name in self._held(repo)
            ],
        }

    def _tree(self, repo: str) -> list[dict[str, object]]:
        return [
            {
                "type": "file",
                "path": name,
                "size": self._size(repo, name),
                "oid": hashlib.sha1(content, usedforsecurity=False).hexdigest(),
            }
            for name, content in self._held(repo).items()
        ]

    def _send_file(self, handler: QuietHandler, repo: str, name: str) -> None:
        content = self._held(repo)[name]
        takeover = self.weight_responders.get(repo)
        if name == WEIGHT_FILE and handler.command == "GET" and takeover is not None:
            takeover(handler)
            return
        # The client resumes a partial file by asking for the rest of it.
        offset = _range_start(handler.headers.get("Range"))
        if offset and name == WEIGHT_FILE and handler.command == "GET":
            self.resumed_from.append(offset)
        body = content[offset:]
        handler.send_response(HTTPStatus.PARTIAL_CONTENT if offset else HTTPStatus.OK)
        handler.send_header("ETag", f'"{hashlib.sha256(content).hexdigest()}"')
        handler.send_header("X-Repo-Commit", self._commit(repo))
        if offset:
            handler.send_header(
                "Content-Range", f"bytes {offset}-{len(content) - 1}/{len(content)}"
            )
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)


def _range_start(header: str | None) -> int:
    """Return the first byte a ``Range: bytes=N-`` header asks for, else zero."""
    if header is None or not header.startswith("bytes="):
        return 0
    start = header.removeprefix("bytes=").split("-", 1)[0]
    return int(start) if start.isdigit() else 0


def _send_json(handler: QuietHandler, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


@contextmanager
def loopback_model_hub(repos: Collection[str]) -> Generator[LoopbackModelHub]:
    """Serve complete snapshots of *repos* on loopback for the block.

    Plain HTTP: the hub client takes whatever scheme its endpoint variable
    names, so no certificate has to be minted or trusted for it.
    """
    hub = LoopbackModelHub(repos=tuple(repos))
    with plain_loopback_sources() as sources:
        hub.endpoint = sources.serve(hub.respond, tls=False).url()
        yield hub
