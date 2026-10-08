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

from tools.monitor.smoke import installed_browser

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

    def wait_ready(self, diagnostic_path: Path) -> None:
        try:
            ready = json.loads(self.answers.get(timeout=60))
        except queue.Empty:
            diagnostic = diagnostic_path.read_text(encoding="utf-8", errors="replace")
            pytest.fail(f"Browser startup did not complete: {diagnostic}")
        assert ready["ready"] is True
        # innerText forces layout, which can block while Vite compiles Carbon's
        # stylesheet on a cold CI worker. Wait without requesting layout first.
        self.wait("document.readyState === 'complete'")


@pytest.fixture
def rendered_monitor(
    monitor_http: tuple[int, Path], tmp_path: Path
) -> Iterator[Browser]:
    root = Path(__file__).resolve().parents[3]
    node = shutil.which("node")
    assert node is not None, "the enrolled monitor Node runtime is required"
    try:
        executable = str(installed_browser())
    except RuntimeError as error:
        pytest.skip(str(error))
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
            browser = Browser(process, answers)
            browser.wait_ready(tmp_path / "browser-errors.log")
            yield browser
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
    _expand_button(browser, selector)


def _expand_button(browser: Browser, selector: str) -> None:
    browser.wait(f"!!document.querySelector({selector})")
    direction = (
        "(() => { const button = document.querySelector("
        + selector
        + "); const matrix = new DOMMatrix(getComputedStyle("
        "button.querySelector('svg')).transform); "
        "return button.getAttribute('aria-expanded') === 'true' "
        "? Math.abs(matrix.a) < 0.01 && Math.abs(matrix.b - 1) < 0.01 "
        ": Math.abs(matrix.a - 1) < 0.01 && Math.abs(matrix.b) < 0.01; })()"
    )
    assert browser.evaluate(direction), "Collapsed chevrons must point right"
    browser.evaluate(f"document.querySelector({selector}).click()")
    browser.wait(direction)
    browser.evaluate(f"document.querySelector({selector}).click()")
    browser.wait(direction)
    browser.evaluate(f"document.querySelector({selector}).click()")
    browser.wait(direction)


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


def test_chart_updates_and_navigation_release_browser_resources(
    rendered_monitor: Browser,
) -> None:
    browser = rendered_monitor
    browser.wait("document.querySelectorAll('.chart-holder svg').length >= 2")
    browser.evaluate("document.querySelector('#live-updates').click()")
    browser.wait(
        "document.querySelector('#live-updates')"
        ".getAttribute('aria-checked') === 'false'"
    )
    browser.evaluate("new Promise(resolve => setTimeout(resolve, 500))")
    original = int(
        cast("int", browser.evaluate("document.querySelectorAll('*').length"))
    )
    # Repeated theme changes force the production chart's option-update path.
    # Removing the status-indicator class repair makes the node bound fail.
    for _ in range(12):
        browser.evaluate("document.querySelector('[aria-label^=\"Theme:\"]').click()")
        browser.evaluate("new Promise(resolve => setTimeout(resolve, 50))")
    current = int(
        cast("int", browser.evaluate("document.querySelectorAll('*').length"))
    )
    assert current <= original + 8, (original, current)
    _page(browser, "queries")
    browser.wait("!document.querySelector('.chart-holder')")
    baseline = cast("dict[str, int]", browser.command("memory"))
    for _ in range(6):
        _page(browser, "dashboard")
        browser.wait("document.querySelectorAll('.chart-holder svg').length >= 2")
        _page(browser, "queries")
        browser.wait("!document.querySelector('.chart-holder')")
    retained = cast("dict[str, int]", browser.command("memory"))
    # Removing componentWillUnmount or the document listener cleanup makes
    # repeated visits retain complete detached chart trees after collection.
    assert retained["nodes"] <= baseline["nodes"] + 40, (baseline, retained)
    assert retained["jsEventListeners"] <= baseline["jsEventListeners"] + 4


def test_background_monitor_stops_polling_and_resumes(
    rendered_monitor: Browser,
) -> None:
    browser = rendered_monitor
    browser.wait("document.querySelectorAll('.chart-holder svg').length >= 2")
    browser.command("background", hidden=True)
    browser.wait("document.hidden")
    before = cast("dict[str, list[object]]", browser.command("evidence"))
    browser.evaluate("new Promise(resolve => setTimeout(resolve, 3500))")
    after = cast("dict[str, list[object]]", browser.command("evidence"))
    # Removing the visibility gate permits health/runtime requests while hidden.
    assert len(after["network"]) == len(before["network"])
    browser.command("background", hidden=False)
    browser.wait("!document.hidden")
    browser.evaluate("new Promise(resolve => setTimeout(resolve, 500))")
    resumed = cast("dict[str, list[object]]", browser.command("evidence"))
    assert len(resumed["network"]) > len(after["network"])


def test_browser_wait_uses_its_deadline_for_renderer_commands(
    rendered_monitor: Browser,
) -> None:
    """A renderer response may exceed the ordinary command's ten-second limit."""
    rendered_monitor.wait(
        "new Promise(resolve => setTimeout(() => { "
        "window.monitorWaitFinished = true; resolve(true); }, 11000))"
    )
    assert rendered_monitor.evaluate("window.monitorWaitFinished") is True


#: The elements whose right edge lies past the viewport, widest first, each
#: with its tag, class and the start of its text.
_STICKING_OUT = (
    "[...document.querySelectorAll('body *')]"
    ".map(node => [node, node.getBoundingClientRect()])"
    ".filter(([, box]) => box.width > 0 && box.right > innerWidth + 0.5)"
    ".sort(([, a], [, b]) => b.right - a.right)"
    ".slice(0, 8)"
    ".map(([node, box]) => `${node.tagName.toLowerCase()}"
    ".${node.getAttribute('class') ?? ''} right=${Math.round(box.right)} "
    "width=${Math.round(box.width)} "
    "${(node.textContent ?? '').trim().slice(0, 40)}`)"
)


def _fits_viewport(browser: Browser) -> None:
    """Wait for the page to settle with nothing wider than its viewport.

    Waited for, not sampled once: the page was drawn at the browser's own
    size and the charts take a new width a frame or more after a resize, so
    the first frame at a narrower size is still as wide as the last one. A
    page that keeps overflowing never settles, and the failure then names
    what sticks out.

    Mutation proof: a ``min-width: 2000px`` on the body failed this on the
    overflow condition at 320 pixels; removing it passed.
    """
    try:
        browser.wait("document.documentElement.scrollWidth <= innerWidth")
    except AssertionError:
        widths = browser.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        sticking_out = browser.evaluate(_STICKING_OUT)
        raise AssertionError(
            f"the page stays wider than its viewport {widths}: {sticking_out}"
        ) from None


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
        _fits_viewport(browser)
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
        _fits_viewport(browser)
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
        "fetch('/api/monitor/jobs?limit=100',{headers:{Authorization:'Bearer '+"
        "sessionStorage.getItem('monitor-capability')}})).json(); return "
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
            result_count=2,
            response={
                "results": [
                    {
                        "path": "src/example.py",
                        "score": 0.95,
                        "size": 145000,
                        "metadata": {"language": "python"},
                    },
                    {"path": "src/small.py", "score": 0.1, "size": 150},
                ]
            },
        ),
    )
    _page(browser, "queries")
    _expand(browser, "query", request_id)
    browser.wait("document.body.innerText.includes('src/example.py')")
    assert browser.evaluate("document.body.innerText.includes('0.95')") is True
    browser.evaluate(
        '[...document.querySelectorAll(\'table[aria-label="Query results"] '
        "th button')]"
        ".find(button => button.textContent.trim() === 'size').click()"
    )
    browser.wait(
        "document.querySelector('table[aria-label=\"Query results\"] > tbody > tr')"
        ".innerText.includes('src/small.py')"
    )
    browser.evaluate(
        '[...document.querySelectorAll(\'table[aria-label="Query results"] '
        "th button')]"
        ".find(button => button.textContent.trim() === 'size').click()"
    )
    browser.wait(
        "document.querySelector('table[aria-label=\"Query results\"] > tbody > tr')"
        ".innerText.includes('src/example.py')"
    )
    _expand_button(browser, json.dumps('button[aria-label="Expand 1"]'))
    _expand_button(browser, json.dumps('button[aria-label="Expand metadata"]'))
    browser.wait("document.body.innerText.includes('python')")
    assert browser.evaluate("document.querySelector('[role=tree]') === null")
    assert browser.evaluate(
        "[...document.querySelectorAll('tr[data-child-row] > td, "
        "tr[data-child-row] > td > .cds--child-row-inner-container')].every(node => "
        "getComputedStyle(node).padding === '0px' && "
        "getComputedStyle(node).margin === '0px')"
    ), "Every nested expansion container must have zero padding and margin"
    _page(browser, "repositories")
    browser.wait("document.body.innerText.includes('Add repository')")
    _click(browser, "Add repository")
    browser.evaluate(
        "(() => { const input = document.querySelector('#repository-root'); "
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
        ".set.call(input, 'relative/path'); "
        "input.dispatchEvent(new Event('input', { bubbles: true })); })()"
    )
    browser.wait(
        "[...document.querySelectorAll('[role=dialog] button')].some(button => "
        "button.textContent === 'Add repository' && !button.disabled)"
    )
    browser.evaluate(
        "[...document.querySelectorAll('[role=dialog] button')].find(button => "
        "button.textContent === 'Add repository').click()"
    )
    browser.wait(
        "[...document.querySelectorAll('[role=dialog]')].some(dialog => "
        "dialog.innerText.includes('Could not add repository'))"
    )
    assert cast("dict[str, object]", browser.command("evidence"))["errors"] == []


def test_request_details_stay_open_and_lists_are_pageable(
    rendered_monitor: Browser, monitor_http: tuple[int, Path]
) -> None:
    browser = rendered_monitor
    _, directory = monitor_http
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    _page(browser, "indexing")
    _expand(browser, "index request", job_id)
    browser.evaluate(
        "window.openDetails = document.querySelector('.monitor-request-details'); true"
    )
    browser.evaluate(
        "[...document.querySelectorAll('.monitor-request-details button')].find(button "
        "=> button.textContent.includes('Timing and diagnostics')).click()"
    )
    _expand_button(browser, json.dumps('button[aria-label="Expand runtime"]'))
    record_finish(job_id, result="Indexing finished while open")
    browser.wait("document.body.innerText.includes('Indexing finished while open')")
    assert browser.evaluate(
        "window.openDetails === document.querySelector('.monitor-request-details')"
    ), "Polling must not replace an open request detail view"
    assert browser.evaluate(
        "document.querySelector('button[aria-label=\"Expand runtime\"]')"
        ".getAttribute('aria-expanded') === 'true'"
    ), "Polling must preserve nested expansion state"
    for index in range(27):
        other = record_start(
            JobSource.CODE, "tool", project_root=directory / f"project-{index:02}"
        )
        record_finish(other, result=f"Finished {index:02}")
    browser.evaluate(
        "(() => { const input = document.querySelector('#index-requests-search'); "
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
        f".set.call(input, {json.dumps(str(directory))}); "
        "input.dispatchEvent(new Event('input', {bubbles:true})); })()"
    )
    browser.wait(
        "document.querySelector('.monitor-work-pagination')"
        ".innerText.includes('28 items')"
    )
    browser.wait(
        "!document.querySelector('.monitor-work-pagination "
        ".cds--pagination__button--forward').disabled"
    )
    browser.evaluate(
        "document.querySelector('.monitor-work-pagination "
        ".cds--pagination__button--forward').click()"
    )
    browser.wait(
        "document.querySelectorAll('.monitor-work-table > tbody > "
        "tr[data-parent-row]').length === 3"
    )
    browser.evaluate(
        "(() => { const input = document.querySelector('#index-requests-search'); "
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')"
        ".set.call(input, 'project-19'); "
        "input.dispatchEvent(new Event('input', {bubbles:true})); })()"
    )
    browser.wait(
        "document.querySelectorAll('.monitor-work-table > tbody > "
        "tr[data-parent-row]').length === 1"
    )
    assert browser.evaluate(
        "document.querySelector('.monitor-work-table').innerText.includes('project-19')"
    )
    path = directory / get_config().log_file
    path.write_text(
        "".join(f"pageable-log-{index:03}\n" for index in range(60)), encoding="utf-8"
    )
    _page(browser, "logs")
    browser.wait("document.body.innerText.includes('pageable-log-059')")
    browser.evaluate(
        "document.querySelector('button[aria-label=\"Older log records\"]').click()"
    )
    browser.wait("document.body.innerText.includes('pageable-log-010')")
    assert not browser.evaluate("document.body.innerText.includes('pageable-log-059')")


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
