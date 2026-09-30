"""Local browser adapter checks over actual service routes and real files."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ..config._settings import get_config
from ..job_models import JobSource
from ..jobs import record_finish, record_start
from ..server._search_activity import SearchActivityCompletion, SearchActivityStart
from ..server._state import search_activity_ledger
from .test_monitor_logs import monitor_http as monitor_http

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture
def browser_bridge(monitor_http: tuple[int, Path]) -> Iterator[tuple[int, Path]]:
    _, directory = monitor_http
    node = shutil.which("node")
    assert node is not None, "the enrolled monitor Node runtime is required"
    source = Path(__file__).resolve().parents[2] / "monitor/server/local-service.ts"
    script = (
        "import { createServer } from 'node:http'; "
        f"import {{ monitorMiddleware }} from {json.dumps(source.as_uri())}; "
        "const server = createServer((req,res) => monitorMiddleware(req,res,() => {"
        "res.writeHead(404); res.end();})); "
        "server.listen(0,'127.0.0.1',() => console.log(server.address().port));"
    )
    environment = dict(os.environ)
    environment.pop("VAULTSPEC_RAG_PORT", None)
    process = subprocess.Popen(
        [node, "--input-type=module", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        answer: queue.Queue[str] = queue.Queue()
        assert process.stdout is not None
        output = process.stdout
        reader = threading.Thread(
            target=lambda: answer.put(output.readline()), daemon=True
        )
        reader.start()
        port = int(answer.get(timeout=10).strip())
        yield port, directory
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _read(
    port: int, path: str, *, origin: str | None = None, prefix: str = "/api/monitor"
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{prefix}{path}")
    if origin:
        request.add_header("Origin", origin)
    try:
        response = urllib.request.urlopen(request, timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.status
        assert isinstance(status, int)
        return status, cast("dict[str, object]", json.load(response))


def test_local_bridge_connects_without_browser_credentials(
    browser_bridge: tuple[int, Path],
    monitor_http: tuple[int, Path],
) -> None:
    port, directory = browser_bridge
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    path = directory / get_config().log_file
    path.write_text(f"job_id={job_id} browser-correlated-record\n", encoding="utf-8")
    try:
        status, jobs = _read(port, f"/jobs?limit=100&job_id={job_id}")
        assert status == 200
        assert any(
            job["id"] == job_id for job in cast("list[dict[str, object]]", jobs["jobs"])
        )
        status, logs = _read(
            port, f"/logs/json?source=service&lines=200&job_id={job_id}"
        )
        assert status == 200
        assert logs["filters"] == {"job_id": job_id}
        assert "browser-correlated-record" in json.dumps(logs)
        _, upstream = _read(monitor_http[0], "/health", prefix="")
        assert upstream["service_token"] == "monitor-test-token"
        _, health = _read(port, "/health")
        # Removing token deletion failed this assertion; restored it passes.
        assert "service_token" not in health
        assert "token" not in health
        discovery = directory / "service.json"
        metadata = json.loads(discovery.read_text(encoding="utf-8"))
        metadata["service_token"] = "obsolete-test-token"
        discovery.write_text(json.dumps(metadata), encoding="utf-8")
        status, refreshed = _read(port, f"/jobs?limit=100&job_id={job_id}")
        assert status == 200
        refreshed_jobs = cast("list[dict[str, object]]", refreshed["jobs"])
        assert len(refreshed_jobs) == 1 and refreshed_jobs[0]["id"] == job_id
        status, activity = _read(port, "/search-activity?limit=100")
        assert status == 200 and "queued" in activity and "recent" in activity
    finally:
        record_finish(job_id, result="completed")


def test_local_bridge_refuses_foreign_origins_and_unrelated_routes(
    browser_bridge: tuple[int, Path],
) -> None:
    port, _ = browser_bridge
    # Bypassing localRequest failed the foreign-origin assertion, then passed
    # after restoration. Bypassing allowedRoute similarly exposed /projects.
    status, answer = _read(port, "/health", origin="http://example.invalid")
    assert status == 403
    assert answer["message"] == "The monitor connects on this machine only."
    status, answer = _read(port, "/projects")
    assert status == 404
    assert answer["message"] == "Unknown monitor operation."


def test_local_bridge_reports_missing_discovery(
    browser_bridge: tuple[int, Path],
) -> None:
    port, directory = browser_bridge
    (directory / "service.json").write_text("{}", encoding="utf-8")
    status, answer = _read(port, "/jobs?limit=100")
    assert status == 503
    assert "No local service is recorded" in str(answer["message"])


def test_browser_projection_rejects_misattributed_production_observations(
    browser_bridge: tuple[int, Path],
) -> None:
    port, directory = browser_bridge
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    ledger = search_activity_ledger()
    ticket = ledger.start(
        SearchActivityStart(
            "projection-request", "real query", "code", str(directory), 3
        )
    )
    path = directory / get_config().log_file
    path.write_text(f"job_id={job_id} projection-record\n", encoding="utf-8")
    try:
        _, log_payload = _read(
            port, f"/logs/json?source=service&lines=200&job_id={job_id}"
        )
        _, activity_payload = _read(port, "/search-activity?limit=100")
        source = Path(__file__).resolve().parents[2] / "monitor/model.ts"
        node = shutil.which("node")
        assert node is not None
        script = (
            "import assert from 'node:assert/strict';"
            "import { logs, activity, diagnostic, safeLog } from "
            f"{json.dumps(source.as_uri())};"
            "const [payload, serving, id] = JSON.parse(process.argv[1]);"
            "const work = {kind:'job',id};"
            "assert.equal(logs(payload,work)[0].lines.length,1);"
            "assert.equal(activity(serving).records[0].request_id,'projection-request');"
            # Verified: bypassing filter validation failed this refusal assertion;
            # restoring validation passed.
            "assert.throws(() => logs({...payload,"
            "filters:{job_id:'different-job'}},work), /different scope/);"
            # Verified: bypassing duplicate identity validation failed this
            # assertion; restoring validation passed.
            "assert.throws(() => activity({...serving,recent:["
            "{...serving.active[0],state:'terminal'}],returned:2}), /identities/);"
            "assert.equal(diagnostic('typesafe_latency_ms',125),'125 ms');"
            "assert.equal(diagnostic('typesafe_confidence',0.9),Number(0.9).toLocaleString());"
            "assert.equal(diagnostic('rerank_seconds',0.05),"
            "Number(0.05).toLocaleString()+' s');"
            "assert.equal(safeLog(String.fromCharCode(27)+'[31mrecord'+String.fromCharCode(0)),'record�');"
        )
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                script,
                json.dumps([log_payload, activity_payload, job_id]),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert result.returncode == 0, result.stderr
    finally:
        record_finish(job_id, result="completed")
        ledger.finish(ticket, completion=SearchActivityCompletion("succeeded", 200))
