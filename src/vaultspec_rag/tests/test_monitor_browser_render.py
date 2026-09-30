"""Carbon rendering over production local routes, ledgers and managed files."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ..config._settings import get_config
from ..job_models import JobSource
from ..jobs import record_finish, record_start
from ..logging_config import QDRANT_LOG_NAME
from ..server._search_activity import SearchActivityCompletion, SearchActivityStart
from ..server._state import search_activity_ledger
from .test_monitor_logs import monitor_http as monitor_http

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


class Browser:
    def __init__(
        self, process: subprocess.Popen[str], answers: queue.Queue[str]
    ) -> None:
        self.process = process
        self.answers = answers

    def command(self, operation: str, **params: object) -> object:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"operation": operation, **params}) + "\n")
        self.process.stdin.flush()
        answer = json.loads(self.answers.get(timeout=60))
        assert answer["ok"], answer.get("message")
        return answer.get("value")

    def wait(self, expression: str) -> None:
        self.command(
            "wait", expression=f"document.body && ({expression})", timeout=45000
        )

    def evaluate(self, expression: str) -> object:
        return self.command("evaluate", expression=expression)


@pytest.fixture
def rendered_monitor(
    monitor_http: tuple[int, Path], tmp_path: Path
) -> Iterator[Browser]:
    root = Path(__file__).resolve().parents[3]
    node = shutil.which("node")
    assert node is not None, "the enrolled monitor Node runtime is required"
    executable = shutil.which("google-chrome") or shutil.which("chromium")
    if executable is None:
        for candidate in (
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        ):
            if candidate.is_file():
                executable = str(candidate)
                break
    if executable is None:
        pytest.skip(
            "rendered checks require installed Chrome/Chromium/Edge; "
            "no browser is downloaded"
        )
    if not (root / "node_modules/vite").is_dir():
        pytest.skip("run just init-monitor before installed-browser checks")
    environment = dict(os.environ)
    environment.pop("VAULTSPEC_RAG_PORT", None)
    environment["VAULTSPEC_RAG_STATUS_DIR"] = str(monitor_http[1])
    with (tmp_path / "browser-errors.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [
                node,
                str(root / "dev/monitor-browser.mjs"),
                executable,
                str(tmp_path / "profile"),
            ],
            cwd=root,
            env=environment,
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

        threading.Thread(target=read_answers, daemon=True).start()
        try:
            ready = json.loads(answers.get(timeout=20))
            assert ready["ready"] is True
            yield Browser(process, answers)
        finally:
            if process.poll() is None:
                try:
                    artifact = Browser(process, answers)
                    body = artifact.evaluate("document.body?.innerText")
                    (tmp_path / "rendered-body.txt").write_text(
                        str(body), encoding="utf-8"
                    )
                    (tmp_path / "rendered-evidence.json").write_text(
                        json.dumps(artifact.command("evidence")), encoding="utf-8"
                    )
                except (AssertionError, queue.Empty, BrokenPipeError):
                    pass
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
            process.stdout.close()


def _click(browser: Browser, label: str) -> None:
    browser.evaluate(
        "[...document.querySelectorAll('button')].find(button => "
        f"button.textContent.trim() === {json.dumps(label)}).click()"
    )


def _inspect(browser: Browser, kind: str, identity: str) -> None:
    selector = json.dumps(f'[aria-label="Inspect {kind} {identity}"]')
    browser.evaluate(f"document.querySelector({selector}).click()")


def _check_retention(
    browser: Browser, directory: Path, path: Path, request_id: str
) -> None:
    discovery = directory / "service.json"
    original = discovery.read_text(encoding="utf-8")
    discovery.write_text("{}", encoding="utf-8")
    browser.wait("document.body.innerText.includes('Showing retained evidence')")
    browser.wait(
        "document.querySelector('#work-inspector')?.innerText"
        ".includes('Observation unavailable') || "
        "document.body.innerText.includes('Work left the current page')"
    )
    # Dropping prior data on failure failed this assertion; restoring it passed.
    # Proof: .pytest-tmp/browser-render-retention-{broken,restored}.log.
    assert (
        browser.evaluate(
            "Boolean(document.querySelector('#work-inspector')?.innerText.includes('next-request'))"
        )
        is True
    )
    discovery.write_text(original, encoding="utf-8")
    browser.wait("!document.body.innerText.includes('Observation unavailable')")
    _click(browser, "Pause live updates")
    with path.open("a", encoding="utf-8") as log:
        log.write(f"request_id={request_id} resumed-request\n")
    time.sleep(1.3)
    # Polling Logs while paused failed here; restored cancellation passed.
    # Proof: .pytest-tmp/browser-render-poll-pause-{broken,restored}.log.
    assert (
        browser.evaluate(
            "document.querySelector('#work-inspector').innerText.includes('resumed-request')"
        )
        is False
    )
    _click(browser, "Resume live updates")
    browser.wait(
        "document.querySelector('#work-inspector')?.innerText.includes('resumed-request')"
    )


@pytest.mark.parametrize("size", [(1440, 1000), (800, 900), (390, 844)])
def test_carbon_monitor_live_scopes_and_retained_evidence(
    rendered_monitor: Browser,
    monitor_http: tuple[int, Path],
    size: tuple[int, int],
    tmp_path: Path,
) -> None:
    browser = rendered_monitor
    _, directory = monitor_http
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    ledger = search_activity_ledger()
    request_id = uuid.uuid4().hex
    ticket = ledger.start(
        SearchActivityStart(
            request_id, "carbon inspection query", "code", str(directory), 3
        )
    )
    path = directory / get_config().log_file
    path.write_text(
        f"job_id={job_id} first-job\nrequest_id={request_id} first-request\n",
        encoding="utf-8",
    )
    (directory / QDRANT_LOG_NAME).write_text("qdrant-own-record\n", encoding="utf-8")
    try:
        browser.command("resize", width=size[0], height=size[1])
        browser.wait(
            f"document.body.innerText.includes({json.dumps(job_id)}) && "
            "document.body.innerText.includes('qdrant-own-record')"
        )
        browser.command("screenshot", path=str(tmp_path / f"monitor-{size[0]}.png"))
        artifact = Path(__file__).resolve().parents[3] / ".pytest-tmp"
        artifact.mkdir(exist_ok=True)
        browser.command(
            "screenshot", path=str(artifact / f"carbon-monitor-{size[0]}.png")
        )
        assert (
            browser.evaluate(
                "(async () => { const payload = await "
                "(await fetch('/api/monitor/health')).json(); "
                "const tile = document.querySelector('#typesafe-heading')"
                ".closest('.monitor-health-tile'); "
                "return tile.innerText.includes(payload.features.typesafe.state) && "
                "tile.innerText.includes(payload.features.typesafe.model); })()"
            )
            is True
        )
        assert (
            browser.evaluate("document.documentElement.scrollWidth <= innerWidth")
            is True
        )
        assert (
            browser.evaluate(
                "document.querySelector('h1').getBoundingClientRect().top >= 48"
            )
            is True
        )
        _inspect(browser, "job", job_id)
        browser.wait(
            "document.querySelector('#work-inspector')?.innerText.includes('first-job')"
        )
        # Removing the work scope mixed request logs into this pane: failed/pass.
        # Proof: .pytest-tmp/browser-render-work-scope-{broken,restored}.log.
        assert (
            browser.evaluate(
                "document.querySelector('#work-inspector').innerText.includes('first-request')"
            )
            is False
        )
        # Enabling all controls failed this capability assertion; restore passed.
        # Proof: .pytest-tmp/browser-render-capabilities-{broken,restored}.log.
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('#work-inspector button')]"
                ".find(button => button.textContent === 'Pause').disabled"
            )
            is True
        )
        with path.open("a", encoding="utf-8") as log:
            log.write(f"job_id={job_id} next-job\n")
        browser.wait(
            "document.querySelector('#work-inspector')?.innerText.includes('next-job')"
        )
        browser.evaluate(
            "[...document.querySelectorAll('[role=tab]')]"
            ".find(tab => tab.textContent === 'Serving requests').click()"
        )
        browser.wait(
            f"!!document.querySelector('[aria-label=\"Inspect request {request_id}\"]')"
        )
        _inspect(browser, "request", request_id)
        browser.wait(
            "document.querySelector('#work-inspector')?.innerText.includes('first-request')"
        )
        # Removing scope/filter validation failed the separate model guard.
        # Rendered ownership independently requires the old job log to leave.
        assert (
            browser.evaluate(
                "document.querySelector('#work-inspector').innerText.includes('next-job')"
            )
            is False
        )
        # Treating requests as jobs failed this assertion; restoring passed.
        # Proof: .pytest-tmp/browser-render-request-controls-{broken,restored}.log.
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('#work-inspector button')]"
                ".some(button => button.textContent === 'Stop')"
            )
            is False
        )
        with path.open("a", encoding="utf-8") as log:
            log.write(
                f"request_id={request_id} next-request <script>inert()</script>\n"
            )
        browser.wait(
            "document.querySelector('#work-inspector')?.innerText.includes('next-request')"
        )
        # Rendering log HTML produced a script node: failed, then restored pass.
        # Proof: .pytest-tmp/browser-render-html-escaping-{broken,restored}.log.
        assert (
            browser.evaluate(
                "document.querySelector('#work-inspector pre script') !== null"
            )
            is False
        )
        _check_retention(browser, directory, path, request_id)
        ledger.finish(
            ticket,
            completion=SearchActivityCompletion(
                "succeeded",
                200,
                result_count=3,
                timings={
                    "typesafe_latency_ms": 125,
                    "typesafe_confidence": 0.9,
                    "rerank_seconds": 0.05,
                },
            ),
        )
        browser.wait(
            "document.querySelector('#work-inspector')?.innerText.includes('125 ms')"
        )
        assert (
            browser.evaluate(
                "document.querySelector('#work-inspector').innerText.includes('0.9 s')"
            )
            is False
        )
        assert (
            browser.evaluate("document.documentElement.scrollWidth <= innerWidth")
            is True
        )
        evidence = cast("dict[str, object]", browser.command("evidence"))
        assert evidence["errors"] == []
        assert any(
            "contains=" + request_id in str(url)
            for url in cast("list[str]", evidence["network"])
        )
    finally:
        record_finish(job_id, result="completed")
        ledger.finish(ticket, completion=SearchActivityCompletion("succeeded", 200))


def test_carbon_delete_targets_the_selected_terminal_job(
    rendered_monitor: Browser, monitor_http: tuple[int, Path]
) -> None:
    browser = rendered_monitor
    _, directory = monitor_http
    first = record_start(JobSource.CODE, "tool", project_root=directory)
    second = record_start(JobSource.VAULT, "tool", project_root=directory)
    record_finish(first, result="first completed")
    record_finish(second, result="second completed")
    browser.wait(f"document.body.innerText.includes({json.dumps(second)})")
    _inspect(browser, "job", first)
    browser.wait(
        "document.querySelector('#work-inspector')?.innerText"
        ".includes('first completed')"
    )
    _click(browser, "Delete record")
    browser.wait("document.body.innerText.includes('Delete this job record?')")
    _click(browser, "Cancel")
    _inspect(browser, "job", second)
    browser.wait(
        "document.querySelector('#work-inspector')?.innerText"
        ".includes('second completed')"
    )
    _click(browser, "Delete record")
    browser.wait("document.body.innerText.includes('Delete this job record?')")
    browser.evaluate(
        "[...document.querySelectorAll('[role=dialog] button')]"
        ".find(button => button.textContent.endsWith('Delete record')).click()"
    )
    browser.wait(
        "document.body.innerText.includes('Work left the current page') || "
        "!document.querySelector('h1')"
    )
    # Removing the obsolete Carbon-row guard blanked the page: failed/pass.
    # Proof: .pytest-tmp/browser-render-removed-row-{broken,restored}.log.
    assert (
        browser.evaluate(
            "document.body.innerText.includes('Work left the current page')"
        )
        is True
    )
    result = browser.evaluate(
        "(async () => { const payload = await "
        "(await fetch('/api/monitor/jobs?limit=100')).json(); "
        "return payload.jobs.map(job => job.id); })()"
    )
    assert first in cast("list[str]", result)
    assert second not in cast("list[str]", result)
