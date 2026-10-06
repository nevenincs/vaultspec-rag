"""Stand a script in for the qdrant binary the supervisor executes.

The supervisor runs its binary with no arguments, so a test that needs the
child to behave a particular way - abort on a named collection, serve without
asking for a key - cannot hand it a script directly. This writes the script
beside a launcher the supervisor can execute as-is, and stages the states a
binary on disk can be met in.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ..qdrant_runtime._constants import BinarySource, ResolvedBinary
from ..qdrant_runtime._provision import file_sha256

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# A server that becomes ready and answers the data plane by one policy, started
# the way the real binary is: no arguments, everything from the environment the
# supervisor built. ENFORCE decides whether it asks for the key it was given.
#
# It serves only while every process above it lives. The supervisor's child is
# the launcher, not this interpreter - a shell on Windows, with the virtual
# environment's own launcher beneath that. A stop ends that whole tree, which
# has its own tests; watching its ancestors is what keeps this process from
# holding the port and the output pipe after a run in which the stop failed.
FAKE_SERVER = """
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import psutil

ENFORCE = {enforce}
KEY = os.environ.get("QDRANT__SERVICE__API_KEY", "")
PORT = int(os.environ["QDRANT__SERVICE__HTTP_PORT"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        refused = (
            ENFORCE
            and self.path == "/collections"
            and self.headers.get("api-key") != KEY
        )
        body = b"{{}}"
        self.send_response(401 if refused else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("127.0.0.1", PORT), Handler)
server.timeout = 0.1
ancestors = psutil.Process().parents()
print("listening", flush=True)
while all(ancestor.is_running() for ancestor in ancestors):
    server.handle_request()
"""


def fake_qdrant_launcher_path(tmp_path: Path, name: str = "fake_qdrant") -> Path:
    """Return where :func:`fake_qdrant_binary` writes the launcher called *name*.

    For a script that has to name its own launcher before the launcher exists.
    """
    suffix = ".bat" if sys.platform == "win32" else ".sh"
    return tmp_path / f"{name}-launcher" / f"{name}{suffix}"


def fake_qdrant_binary(
    tmp_path: Path,
    source: str,
    name: str = "fake_qdrant",
    *,
    launcher_exits_first: bool | None = None,
) -> Path:
    """Write a fake qdrant 'binary' the supervisor can exec as ``[binary]``.

    The launcher is written where :func:`fake_qdrant_launcher_path` says: in
    a directory that holds nothing else, the way a managed install's
    executable sits in its version directory. A managed binary with anything
    beside it is refused, and the script is such a thing.

    Args:
        tmp_path: Where the script is written, and the launcher's directory
            is made.
        source: The script's source.
        name: The stem both files share.
        launcher_exits_first: The shape of the process tree. ``None`` is the
            ordinary one: on POSIX the launcher becomes the script. ``False``
            keeps the launcher as a separate process that waits for the
            script, the way a wrapper around a real server does. ``True``
            starts the script and lets the launcher exit, leaving the script
            running with no parent of its own.
    """
    script = tmp_path / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    run = f'"{sys.executable}" "{script}"'
    launcher = fake_qdrant_launcher_path(tmp_path, name)
    launcher.parent.mkdir(exist_ok=True)
    if sys.platform == "win32":
        # A batch file is always a separate process: the shell that reads it.
        line = f'@start "" /B {run}' if launcher_exits_first else f"@{run}"
        launcher.write_text(f"{line}\r\n", encoding="utf-8")
        return launcher
    line = {None: f"exec {run}", False: f"{run}\ntrue", True: f"{run} &"}[
        launcher_exits_first
    ]
    launcher.write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


@contextmanager
def unreadable(path: Path) -> Generator[None]:
    """Keep the file at *path* from being opened to be hashed, for the block.

    On Windows another handle holds it open for writing, which the hold that
    hashes a binary does not share with. Elsewhere its permissions deny its
    owner any access, which stops everyone but the superuser - so a run as
    the superuser fails here and does not pass having stopped nothing.
    """
    if sys.platform == "win32":
        with path.open("r+b"):
            yield
        return
    if os.geteuid() == 0:
        pytest.fail("permissions do not stop the superuser reading a file")
    mode = path.stat().st_mode
    path.chmod(0)
    try:
        yield
    finally:
        path.chmod(mode)


def unpinned(path: Path) -> ResolvedBinary:
    """Present *path* to a supervisor the way the operator binary settings do.

    A stand-in is not a release executable, so no committed digest can apply
    to it. An operator binary is held to the digest its operator declares
    instead, and a test handing over its own script is that operator: the
    digest declared here is the file's own, as it stands now. A path that
    names no file is given none, and so can never be spawned.
    """
    declared = file_sha256(path) if path.is_file() else ""
    return ResolvedBinary(
        path=path, source=BinarySource.OPERATOR_SETTING, sha256=declared
    )
