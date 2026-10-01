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


def _page(browser: Browser, page: str) -> None:
    browser.evaluate(f"location.hash = '/{page}'")
    browser.wait(f"location.hash === '#/{page}'")


def _expand(browser: Browser, kind: str, identity: str) -> None:
    label = f"Expand {kind} {identity}"
    selector = json.dumps(
        f'button[aria-label="{label}"], [data-work-id="{identity}"] button'
    )
    browser.wait(f"!!document.querySelector({selector})")
    browser.evaluate(f"document.querySelector({selector}).click()")


def _check_retention(
    browser: Browser, directory: Path, path: Path, request_id: str
) -> None:
    discovery = directory / "service.json"
    original = discovery.read_text(encoding="utf-8")
    _select_theme(browser, "dark")
    try:
        discovery.write_text("{}", encoding="utf-8")
        browser.wait(
            "document.body.innerText.includes("
            "'Showing data from the last successful update')"
        )
        assert browser.evaluate(
            "getComputedStyle(document.querySelector('.cds--inline-notification'))"
            ".backgroundColor.match(/\\d+/g).slice(0, 3)"
            ".every(value => Number(value) < 128)"
        ), "Dark-theme warnings must use Carbon's low-contrast background"
        assert (
            browser.evaluate("document.body.innerText.includes('next-request')") is True
        )
    finally:
        discovery.write_text(original, encoding="utf-8")
    browser.wait(
        "!document.querySelector('main').innerText.includes('Unable to update data')"
    )
    browser.evaluate("document.querySelector('#live-updates').click()")
    with path.open("a", encoding="utf-8") as log:
        log.write(f"request_id={request_id} resumed-request\n")
    time.sleep(1.3)
    assert (
        browser.evaluate("document.body.innerText.includes('resumed-request')") is False
    )
    browser.evaluate("document.querySelector('#live-updates').click()")
    browser.wait("document.body.innerText.includes('resumed-request')")


def _select_theme(browser: Browser, theme: str) -> None:
    browser.wait("!!document.querySelector('.monitor-theme')")
    for _ in range(3):
        if browser.evaluate("localStorage.getItem('monitor-theme')") == theme:
            break
        browser.evaluate("document.querySelector('.monitor-theme').click()")
    browser.wait(f"localStorage.getItem('monitor-theme') === '{theme}'")


def _check_shell(browser: Browser, desktop: bool) -> None:
    assert browser.evaluate(
        "(() => { const refresh = document.querySelector('.monitor-refresh')"
        ".getBoundingClientRect(); const theme = "
        "document.querySelector('.monitor-theme')"
        ".getBoundingClientRect(); return refresh.right === theme.left "
        "&& refresh.top === theme.top && theme.width === 48; })()"
    ), "Refresh must immediately precede the standard theme header action"

    def toggle(label: str) -> None:
        browser.evaluate(
            f"document.querySelector('button[aria-label=\"{label} navigation\"]')"
            ".click()"
        )

    if desktop:
        assert browser.evaluate(
            "document.querySelector('button[aria-label=\"Close navigation\"]')"
            ".getBoundingClientRect().width >= 40"
        ), "Desktop sidebar control must be visible"
        toggle("Close")
    else:
        toggle("Open")
        browser.wait(
            "document.querySelector('#monitor-navigation')"
            ".getBoundingClientRect().width > 200"
        )
        toggle("Close")
    browser.wait(
        "document.querySelector('#monitor-navigation')"
        ".getBoundingClientRect().right <= 0"
    )
    if desktop:
        toggle("Open")
        browser.wait(
            "document.querySelector('#monitor-navigation')"
            ".getBoundingClientRect().right > 200"
        )
    _select_theme(browser, "light")
    browser.wait("localStorage.getItem('monitor-theme') === 'light'")
    browser.wait(
        "getComputedStyle(document.querySelector('.monitor-root')).backgroundColor "
        "=== 'rgb(244, 244, 244)'"
    )
    _select_theme(browser, "dark")
    browser.wait(
        "getComputedStyle(document.querySelector('.monitor-root')).backgroundColor "
        "=== 'rgb(22, 22, 22)'"
    )


def _dashboard_artifact(browser: Browser, size: tuple[int, int]) -> Path:
    _check_shell(browser, size[0] >= 1056)
    assert browser.evaluate(
        "document.querySelector('.monitor-header-details').getBoundingClientRect()"
        ".bottom <= document.querySelector('header').getBoundingClientRect().bottom"
    ), "Header controls must stay inside the header"
    artifact = Path(__file__).resolve().parents[3] / ".pytest-tmp"
    artifact.mkdir(exist_ok=True)
    browser.command(
        "screenshot", path=str(artifact / f"carbon-dashboard-{size[0]}.png")
    )
    return artifact


@pytest.mark.parametrize("size", [(1440, 1000), (800, 900), (390, 844), (320, 740)])
def test_carbon_monitor_live_scopes_and_retained_evidence(
    rendered_monitor: Browser,
    monitor_http: tuple[int, Path],
    size: tuple[int, int],
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
        browser.wait("document.body.innerText.includes('Models and integrations')")
        browser.wait("document.body.innerText.includes('System CPU')")
        assert (
            browser.evaluate("document.querySelector('h1').textContent") == "Dashboard"
        )
        assert (
            browser.evaluate(
                "!!document.querySelector('[aria-label=\"Monitor navigation\"]')"
            )
            is True
        )
        assert (
            browser.evaluate("document.body.innerText.includes('TypeSafe API')") is True
        )
        assert (
            browser.evaluate("document.querySelector('#typesafe-heading') === null")
            is True
        )
        assert (
            browser.evaluate(
                "document.querySelector('table[aria-label=\"Queries\"]') === null"
            )
            is True
        )
        assert (
            browser.evaluate("document.documentElement.scrollWidth <= innerWidth")
            is True
        )
        assert (
            browser.evaluate(
                "document.querySelector('h1').getBoundingClientRect().top "
                ">= document.querySelector('header').getBoundingClientRect().bottom"
            )
            is True
        )
        artifact = _dashboard_artifact(browser, size)
        _page(browser, "indexing")
        _expand(browser, "index request", job_id)
        browser.wait("document.body.innerText.includes('first-job')")
        assert (
            browser.evaluate("document.body.innerText.includes('first-request')")
            is False
        )
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('button')].find(button => "
                "button.textContent === 'Pause').disabled"
            )
            is True
        )
        with path.open("a", encoding="utf-8") as log:
            log.write(f"job_id={job_id} next-job\n")
        browser.wait("document.body.innerText.includes('next-job')")
        _page(browser, "queries")
        _expand(browser, "query", request_id)
        browser.wait("document.body.innerText.includes('first-request')")
        assert browser.evaluate("document.body.innerText.includes('next-job')") is False
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('button')].some(button => "
                "button.textContent === 'Delete record')"
            )
            is False
        )
        with path.open("a", encoding="utf-8") as log:
            log.write(
                f"request_id={request_id} next-request <script>inert()</script>\n"
            )
        browser.wait("document.body.innerText.includes('next-request')")
        assert (
            browser.evaluate("document.querySelector('main script') === null") is True
        )
        _check_retention(browser, directory, path, request_id)
        browser.command(
            "screenshot", path=str(artifact / f"carbon-queries-{size[0]}.png")
        )
        _page(browser, "logs")
        browser.wait("document.body.innerText.includes('qdrant-own-record')")
        browser.wait("document.body.innerText.includes('next-job')")
        assert (
            browser.evaluate("document.documentElement.scrollWidth <= innerWidth")
            is True
        )
        evidence = cast("dict[str, object]", browser.command("evidence"))
        assert evidence["errors"] == []
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
    _page(browser, "indexing")
    _expand(browser, "index request", second)
    _click(browser, "Delete record")
    browser.wait("document.body.innerText.includes('Delete this job record?')")
    browser.evaluate(
        "[...document.querySelectorAll('[role=dialog] button')].find(button "
        "=> button.textContent.endsWith('Delete record')).click()"
    )
    browser.wait(
        f"!document.querySelector('[aria-label=\"Expand index request {second}\"]')"
    )
    assert (
        browser.evaluate("document.querySelector('h1').textContent") == "Index Requests"
    )
    result = browser.evaluate(
        "(async () => { const payload = await (await "
        "fetch('/api/monitor/jobs?limit=100')).json(); return "
        "payload.jobs.map(job => job.id); })()"
    )
    assert first in cast("list[str]", result)
    assert second not in cast("list[str]", result)


def test_carbon_relational_query_results_and_enrollment_validation(
    rendered_monitor: Browser, monitor_http: tuple[int, Path]
) -> None:
    browser = rendered_monitor
    _, directory = monitor_http
    request_id = uuid.uuid4().hex
    ledger = search_activity_ledger()
    ticket = ledger.start(
        SearchActivityStart(request_id, "nested evidence", "code", str(directory), 1)
    )
    ledger.finish(
        ticket,
        completion=SearchActivityCompletion(
            "succeeded",
            200,
            result_count=1,
            response={"results": [{"path": "src/example.py", "score": 0.95}]},
        ),
    )
    _page(browser, "queries")
    _expand(browser, "query", request_id)
    browser.wait("document.body.innerText.includes('response')")
    browser.evaluate(
        "[...document.querySelectorAll('[role=treeitem]')].find(item => "
        "item.textContent.trim().startsWith('response')).click()"
    )
    browser.wait("!!document.querySelector('button[aria-label=\"Expand results\"]')")
    browser.evaluate(
        "document.querySelector('button[aria-label=\"Expand results\"]').click()"
    )
    browser.wait("document.body.innerText.includes('src/example.py')")
    assert browser.evaluate("document.body.innerText.includes('0.95')") is True
    _page(browser, "repositories")
    browser.wait("document.body.innerText.includes('Enroll repository')")
    _click(browser, "Enroll repository")
    browser.evaluate(
        "(() => { const input = document.querySelector('#repository-root'); "
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
        ".set.call(input, 'relative/path'); "
        "input.dispatchEvent(new Event('input', { bubbles: true })); })()"
    )
    browser.wait(
        "[...document.querySelectorAll('[role=dialog] button')].some(button => "
        "button.textContent === 'Enroll' && !button.disabled)"
    )
    _click(browser, "Enroll")
    browser.wait(
        "[...document.querySelectorAll('[role=dialog]')].some(dialog => "
        "dialog.innerText.includes('Enrollment failed'))"
    )
    assert cast("dict[str, object]", browser.command("evidence"))["errors"] == []


def test_carbon_stopped_service_and_theme_notifications(
    rendered_monitor: Browser, monitor_http: tuple[int, Path]
) -> None:
    browser = rendered_monitor
    discovery = monitor_http[1] / "service.json"
    original = discovery.read_text(encoding="utf-8")
    _select_theme(browser, "dark")
    try:
        discovery.write_text("{}", encoding="utf-8")
        browser.wait("document.body.innerText.includes('Service not running')")
        assert (
            browser.evaluate(
                "!document.querySelector('main').innerText.includes('System CPU')"
            )
            is True
        )
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('button')].find(button => "
                "button.textContent === 'Start service').disabled"
            )
            is False
        )
        assert (
            browser.evaluate(
                "[...document.querySelectorAll('button')].find(button => "
                "button.textContent === 'Pause service').disabled"
            )
            is True
        )
        dark = browser.evaluate(
            "getComputedStyle(document.querySelector('#service-state-notice')).backgroundColor"
        )
        _select_theme(browser, "light")
        browser.wait("localStorage.getItem('monitor-theme') === 'light'")
        browser.wait(
            "getComputedStyle(document.querySelector('#service-state-notice'))"
            ".backgroundColor "
            f"!== {json.dumps(dark)}"
        )
    finally:
        discovery.write_text(original, encoding="utf-8")
    browser.wait("document.body.innerText.includes('Models and integrations')")
