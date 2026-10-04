"""Local browser adapter checks over actual service routes and real files."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPConnection
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ..config._settings import get_config
from ..job_models import JobSource
from ..jobs import record_finish, record_start
from ..server._search_activity import SearchActivityCompletion, SearchActivityStart
from ..server._state import search_activity_ledger
from ..service_quiesce import QuiesceTransitionCode
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
        "server.listen(0,'0.0.0.0',() => console.log(server.address().port));"
    )
    environment = dict(os.environ)
    environment.pop("VAULTSPEC_RAG_PORT", None)
    environment["VAULTSPEC_RAG_MONITOR_PYTHON"] = sys.executable
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
    port: int,
    path: str,
    *,
    origin: str | None = None,
    host: str | None = None,
    prefix: str = "/api/monitor",
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{prefix}{path}")
    if origin:
        request.add_header("Origin", origin)
    if host:
        request.add_header("Host", host)
    return _response(request)


def _post(
    port: int, path: str, body: dict[str, object]
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/monitor{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return _response(request)


def _response(request: urllib.request.Request) -> tuple[int, dict[str, object]]:
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
    # after restoration. Bypassing allowedRoute exposes /readiness.
    status, answer = _read(port, "/health", origin="http://example.invalid")
    assert status == 403
    assert answer["message"] == (
        "The monitor accepts only loopback clients at a local host."
    )
    status, answer = _read(port, "/readiness")
    assert status == 404
    assert answer["message"] == "Unknown monitor operation."


@pytest.mark.parametrize("installed", [True, False])
def test_local_bridge_lifecycle_uses_fixed_canonical_commands(
    tmp_path: Path, installed: bool
) -> None:
    """Exercise the adapter's command boundary without operating a daemon."""
    node = shutil.which("node")
    assert node is not None
    source = Path(__file__).resolve().parents[2] / "monitor/server/local-service.ts"
    tools_directory = tmp_path / "tools"
    if installed:
        interpreter = (
            tools_directory
            / "vaultspec-rag"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()
    script = (
        "import assert from 'node:assert/strict';"
        "import child from 'node:child_process';"
        "import { syncBuiltinESMExports } from 'node:module';"
        "import { createServer } from 'node:http';"
        "import { join } from 'node:path';"
        "const config=JSON.parse(process.argv[1]);"
        "const calls=[],probes=[]; let failure=false,observedState='stopped';"
        "child.execFile=(file,args,options,callback)=>{"
        "if(file==='uv'){probes.push({args,options});"
        "callback(null,config.toolsDirectory,'');return;}"
        "calls.push({file,args,options}); const verb=args[4];"
        "const code=verb==='status'?observedState==='stopped'?3:"
        "observedState==='warming'?5:4:failure?1:0;"
        "const error=code?Object.assign(new Error('owner failed'),{code}):null;"
        "callback(error,JSON.stringify({ok:code===0,command:'service.'+verb,"
        "data:verb==='status'?{state:observedState}:{status:failure?'still_running':"
        "verb==='start'?'already_running':'already_stopped',"
        "health:{service_token:'never-browser',nested:[{token:'private'}]}}}),'');"
        "}; syncBuiltinESMExports();"
        f"const {{ monitorMiddleware }}=await import({json.dumps(source.as_uri())});"
        "const server=createServer((req,res)=>monitorMiddleware(req,res,()=>{"
        "res.writeHead(404);res.end();}));"
        "await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));"
        "const base='http://127.0.0.1:'+server.address().port+'/api/monitor';"
        "async function action(path,body,expected){"
        "const response=await fetch(base+path,{method:body===undefined?'GET':'POST',"
        "body:body===undefined?undefined:JSON.stringify(body)});"
        "assert.equal(response.status,expected);return response.json();}"
        "try {"
        "for(observedState of ['stopped','warming','crashed-pid-dead']){"
        "const state=await action('/lifecycle',undefined,200);"
        "assert.equal(state.state,observedState);assert.equal(state.ok,false);"
        "assert.equal(state.data.state,observedState); }"
        "for(const verb of ['start','stop']){"
        "const result=await action('/lifecycle/'+verb,{},200);"
        "assert.equal(result.data.status,'already_'+(verb==='start'?'running':'stopped'));"
        # Returning nested credentials fails this assertion; restoration passes.
        "assert.equal(JSON.stringify(result).includes('never-browser'),false);"
        "assert.equal(JSON.stringify(result).includes('private'),false);"
        "}"
        "failure=true;const refused=await action('/lifecycle/stop',{},503);"
        "assert.equal(refused.data.status,'still_running');assert.equal(refused.ok,false);"
        "assert.equal(calls.length,6);assert.equal(probes.length,1);"
        "assert.deepEqual(probes[0].args,['tool','dir']);"
        "assert.equal(probes[0].options.shell,false);"
        "assert.equal(probes[0].options.windowsHide,true);"
        "assert.equal(probes[0].options.timeout,5000);"
        "assert.equal(probes[0].options.maxBuffer,8192);"
        "for(const call of calls){const verb=call.args[4];"
        "assert.deepEqual(call.args,['-P','-m','vaultspec_rag','server',verb,'--json']);"
        # Preferring checkout Python failed the installed-runtime assertion;
        # restoring installed-tool preference passed.
        "assert.equal(call.file,join(config.installed?"
        "join(config.toolsDirectory,'vaultspec-rag'):join(call.options.cwd,'.venv'),"
        "process.platform==='win32'?'Scripts/python.exe':'bin/python'));"
        "assert.equal(call.options.env.PYTHONPATH,join(call.options.cwd,'src'));"
        # Enabling shell execution fails this assertion; restoration passes.
        "assert.equal(call.options.shell,false);assert.equal(call.options.windowsHide,true);"
        "assert.equal(call.options.maxBuffer,1024*1024);"
        "assert.equal(call.options.timeout,verb==='status'?30000:verb==='start'?900000:120000);"
        "}"
        "failure=false;"
        # Accepting browser arguments fails this assertion; restoration passes.
        "await action('/lifecycle/start',{root:'arbitrary',command:'anything'},400);"
        "await action('/lifecycle/stop?port=1',{},400);"
        "await action('/lifecycle/start',[],400);"
        "await action('/lifecycle/start',null,400);"
        "await action('/lifecycle/restart',{},404);"
        "await action('/lifecycle/start',undefined,404);"
        "assert.equal(calls.length,6);"
        "} finally {await new Promise(resolve=>server.close(resolve));}"
    )
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            json.dumps(
                {"toolsDirectory": str(tools_directory), "installed": installed}
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr


def test_local_bridge_status_reads_stopped_owner_without_starting(
    browser_bridge: tuple[int, Path],
) -> None:
    port, directory = browser_bridge
    (directory / "service.json").unlink()
    status, answer = _read(port, "/lifecycle")
    assert status == 200
    assert answer["command"] == "service.status"
    assert answer["state"] == "stopped"
    assert answer["data"] == {"service_json_present": False, "state": "stopped"}
    assert not (directory / "service.json").exists()


def test_local_bridge_forwards_operator_inventory_and_controls(
    browser_bridge: tuple[int, Path], tmp_path: Path
) -> None:
    port, _ = browser_bridge
    root = tmp_path / "enrolled-root"
    root.mkdir()
    (root / ".vault").mkdir()
    status, enrollment = _post(
        port, "/repositories/enroll", {"root": str(root), "watch": False}
    )
    assert status == 200 and enrollment["status"] == "enrolled"
    assert enrollment["watcher_status"] == "disabled"
    status, inventory = _read(port, "/repositories?limit=100")
    assert status == 200
    rows = cast("list[dict[str, object]]", inventory["repositories"])
    assert any(row["root"] == str(root.resolve()) and row["enrolled"] for row in rows)
    assert "seats" in inventory
    status, projects = _read(port, "/projects")
    assert status == 200 and projects["projects"] == []
    status, eviction = _post(port, "/projects/evict", {"root": str(root)})
    assert status == 200 and eviction["reason"] == "not_found"
    status, state = _read(
        port, "/service-state?" + urllib.parse.urlencode({"project_root": str(root)})
    )
    assert status == 200 and "quiesce" in state and "root_features" in state
    status, resources = _read(port, "/runtime-observations")
    assert status == 200 and "cpu" in resources and "clients" in resources
    status, survey = _read(port, "/storage/survey?status=unsupported")
    assert status in (400, 409)
    assert survey["error"] in ("bad_request", "server_mode_required")
    status, paused = _post(port, "/pause", {})
    assert status == 200 and paused["ok"] is True
    assert paused["status"] == QuiesceTransitionCode.QUIESCED
    status, resumed = _post(port, "/resume", {})
    assert status == 200 and resumed["ok"] is True
    assert resumed["status"] == QuiesceTransitionCode.RUNNING


@pytest.mark.parametrize(
    "host",
    [
        "gw-workstation.taild36992.ts.net:15420",
        "100.84.254.21:5420",
        "[fd7a:115c:a1e0::2c01:feb6]:5420",
    ],
)
@pytest.mark.parametrize("send_origin", [True, False])
def test_bridge_refuses_tailnet_proxy_authorities(
    browser_bridge: tuple[int, Path], host: str, send_origin: bool
) -> None:
    port, _ = browser_bridge
    # Restoring Tailnet Host admission fails this assertion; loopback-only passes.
    status, answer = _read(
        port, "/health", host=host, origin=f"https://{host}" if send_origin else None
    )
    assert status == 403
    assert answer["message"] == (
        "The monitor accepts only loopback clients at a local host."
    )


@pytest.mark.parametrize(
    "host", ["localhost:5420", "vaultspec-rag-monitor.localhost", "[::1]:5420"]
)
def test_bridge_accepts_local_proxy_authorities(
    browser_bridge: tuple[int, Path], host: str
) -> None:
    port, _ = browser_bridge
    status, health = _read(port, "/health", host=host, origin=f"https://{host}")
    assert status == 200
    assert "service_token" not in health
    assert "token" not in health


@pytest.mark.parametrize("host", ["other.taild36992.ts.net", "100.128.0.1"])
def test_bridge_refuses_undeclared_proxy_authorities(
    browser_bridge: tuple[int, Path], host: str
) -> None:
    port, _ = browser_bridge
    # Bypassing host validation failed here; restoring the check passed.
    status, _ = _read(port, "/health", host=host, origin=f"https://{host}")
    assert status == 403


def test_bridge_refuses_a_client_outside_admitted_loopback_addresses(
    browser_bridge: tuple[int, Path],
) -> None:
    port, _ = browser_bridge
    # Removing client-address validation failed this real-source assertion;
    # restoring it passed. Proof: .pytest-tmp/tailnet-client-{broken,restored}.log.
    connection = HTTPConnection(
        "127.0.0.1", port, timeout=8, source_address=("127.0.0.2", 0)
    )
    try:
        connection.request("GET", "/api/monitor/health")
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()


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
    tmp_path: Path,
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
        payload_path = tmp_path / "projection-observations.json"
        payload_path.write_text(
            json.dumps([log_payload, activity_payload, job_id]), encoding="utf-8"
        )
        script = (
            "import assert from 'node:assert/strict';"
            "import { readFileSync } from 'node:fs';"
            "import { logs, activity, compareValues, safeLog } from "
            f"{json.dumps(source.as_uri())};"
            "const [payload, serving, id] = "
            "JSON.parse(readFileSync(process.argv[1],'utf8'));"
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
            "assert(compareValues(145000,150)>0);"
            "assert(compareValues('145000','150')>0);"
            "assert(compareValues(0.95,0.1)>0);"
            "assert.equal(safeLog(String.fromCharCode(27)+'[31mrecord'+String.fromCharCode(0)),'record�');"
        )
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                script,
                str(payload_path),
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
