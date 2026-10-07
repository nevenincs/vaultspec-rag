"""The browser launcher the monitor's render tests drive, on a page that fails.

Every render test asks its questions of a page the launcher reported ready.
A page whose own script could not be fetched finishes loading with nothing
drawn, and each question then waits out its full deadline on a blank
document. So "ready" has to mean the page loaded, and a load that failed has
to be tried again before it is given up on.

No doubles: a real loopback server hands a real installed browser a page whose
script it refuses to serve.

MUTATION PROOF, in one uninterrupted sequence and restored: with the launcher
made to report ready on the first load whatever happened to it,
``test_a_page_whose_script_failed_to_load_is_loaded_again`` fails on the
``drawn`` assertion, and ``test_a_page_that_never_loads_is_a_startup_failure``
fails because the browser reported ready; restoring it passes both.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from tools.monitor.smoke import installed_browser

from .test_monitor_browser_render import Browser

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.unit

_PAGE = (
    b"<!doctype html><html><head><title>launcher</title></head>"
    b'<body><div id="root"></div>'
    b'<script type="module" src="/app.js"></script></body></html>'
)
_SCRIPT = b"document.getElementById('root').appendChild(document.createElement('p'));"
_DRAWN = "document.getElementById('root').childElementCount > 0"


class _Page(ThreadingHTTPServer):
    """Serve the page, dropping the script's first *dropped* requests."""

    def __init__(self, dropped: int) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.dropped = dropped
        self.script_requests = 0
        self.counting = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        server = cast("_Page", self.server)
        if self.path == "/app.js":
            with server.counting:
                server.script_requests += 1
                drop = server.script_requests <= server.dropped
            if drop:
                # Refused outright and by status, so the browser has nothing
                # it may quietly ask for again: a dropped connection it
                # sometimes retries on its own, and then nothing has failed.
                self._answer(503, "text/plain", b"unavailable")
                return
            self._answer(200, "text/javascript", _SCRIPT)
        elif self.path == "/":
            self._answer(200, "text/html", _PAGE)
        else:
            self._answer(204, "text/plain", b"")

    def _answer(self, status: int, kind: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _served(dropped: int) -> Generator[_Page]:
    page = _Page(dropped)
    thread = threading.Thread(target=page.serve_forever, daemon=True)
    thread.start()
    try:
        yield page
    finally:
        page.shutdown()
        page.server_close()
        thread.join(timeout=10)


@contextmanager
def _launched(
    url: str, tmp_path: Path
) -> Generator[tuple[subprocess.Popen[str], queue.Queue[str], Path]]:
    """Run the launcher against *url*; yield it, its answers and its error log."""
    root = Path(__file__).resolve().parents[3]
    node = shutil.which("node")
    assert node is not None, "the enrolled monitor Node runtime is required"
    try:
        executable = str(installed_browser())
    except RuntimeError as error:
        pytest.skip(str(error))
    log = tmp_path / "browser-errors.log"
    with log.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [
                node,
                str(root / "dev/monitor-browser.mjs"),
                executable,
                str(tmp_path / "profile"),
                url,
            ],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdout is not None
        answers: queue.Queue[str] = queue.Queue()

        def read_answers() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                if line.startswith("{"):
                    answers.put(line)

        reader = threading.Thread(target=read_answers, daemon=True)
        reader.start()
        try:
            yield process, answers, log
        finally:
            if process.poll() is None and process.stdin:
                process.stdin.write('{"operation":"close"}\n')
                process.stdin.flush()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            if process.stdin:
                process.stdin.close()
            reader.join(timeout=10)
            process.stdout.close()


def test_a_page_whose_script_failed_to_load_is_loaded_again(tmp_path: Path) -> None:
    """One dropped script request costs a reload, not the page."""
    with _served(dropped=1) as page:
        url = f"http://127.0.0.1:{page.server_address[1]}/"
        with _launched(url, tmp_path) as (process, answers, log):
            browser = Browser(process, answers)
            browser.wait_ready(log)

            drawn = browser.evaluate(_DRAWN)
            evidence = cast("dict[str, object]", browser.command("evidence"))
        requests = page.script_requests

    assert drawn is True, "the launcher reported a blank page ready"
    assert requests == 2, f"the script was asked for {requests} time(s)"
    # The load that was thrown away is not held against the page that
    # replaced it; it is written where a failure would be read.
    assert evidence["errors"] == []
    assert "page load 1 discarded" in log.read_text(encoding="utf-8")


def test_a_page_that_never_loads_is_a_startup_failure(tmp_path: Path) -> None:
    """A page that cannot load is not handed to a test as ready."""
    with _served(dropped=1_000) as page:
        url = f"http://127.0.0.1:{page.server_address[1]}/"
        with _launched(url, tmp_path) as (process, answers, log):
            exit_code = process.wait(timeout=180)
            reported = not answers.empty()
        requests = page.script_requests

    written = log.read_text(encoding="utf-8")
    assert not reported, "a page that never loaded was reported ready"
    assert exit_code != 0
    assert requests == 3, f"the load was tried {requests} time(s), not three"
    assert "page load 2 discarded" in written
    assert "The monitor page did not load" in written
