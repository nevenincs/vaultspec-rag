"""Local browser adapter checks over actual service routes and real files."""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
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
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from .test_monitor_logs import monitor_http as monitor_http

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture
def browser_bridge(monitor_http: tuple[int, Path]) -> Iterator[tuple[str, Path]]:
    _, directory = monitor_http
    node = shutil.which("node")
    assert node is not None, "the enrolled monitor Node runtime is required"
    source = Path(__file__).resolve().parents[2] / "monitor/server/local-service.ts"
    script = (
        "import { createServer } from 'node:http'; "
        "import { monitorAccess, monitorMiddleware } from "
        f"{json.dumps(source.as_uri())}; "
        "const server = createServer((req,res) => monitorMiddleware(req,res,() => {"
        "res.writeHead(404); res.end();})); "
        "server.listen(0,'0.0.0.0',() => "
        "console.log(monitorAccess(server.address().port)));"
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
        yield answer.get(timeout=CHILD_PROCESS_TIMEOUT_SECONDS).strip(), directory
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


def _request(
    access: str, path: str, *, bearer: str | None = None
) -> urllib.request.Request:
    """Address the bridge behind an access link, presenting its capability.

    ``bearer`` replaces the credential; an empty string sends none.
    """
    link = urllib.parse.urlsplit(access)
    request = urllib.request.Request(f"http://{link.netloc}/api/monitor{path}")
    credential = link.fragment.removeprefix("capability=") if bearer is None else bearer
    if credential:
        request.add_header("Authorization", f"Bearer {credential}")
    return request


def _read(
    access: str,
    path: str,
    *,
    origin: str | None = None,
    host: str | None = None,
    bearer: str | None = None,
) -> tuple[int, dict[str, object]]:
    request = _request(access, path, bearer=bearer)
    if origin:
        request.add_header("Origin", origin)
    if host:
        request.add_header("Host", host)
    return _response(request)


def _post(
    access: str, path: str, body: dict[str, object], *, bearer: str | None = None
) -> tuple[int, dict[str, object]]:
    request = _request(access, path, bearer=bearer)
    request.data = json.dumps(body).encode()
    request.add_header("Content-Type", "application/json")
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


def test_local_bridge_keeps_the_backend_credential_from_the_browser(
    browser_bridge: tuple[str, Path],
    monitor_http: tuple[int, Path],
) -> None:
    access, directory = browser_bridge
    job_id = record_start(JobSource.CODE, "tool", project_root=directory)
    path = directory / get_config().log_file
    path.write_text(f"job_id={job_id} browser-correlated-record\n", encoding="utf-8")
    try:
        status, jobs = _read(access, f"/jobs?limit=100&job_id={job_id}")
        assert status == 200
        assert any(
            job["id"] == job_id for job in cast("list[dict[str, object]]", jobs["jobs"])
        )
        status, logs = _read(
            access, f"/logs/json?source=service&lines=200&job_id={job_id}"
        )
        assert status == 200
        assert logs["filters"] == {"job_id": job_id}
        assert "browser-correlated-record" in json.dumps(logs)
        _, upstream = _response(
            urllib.request.Request(f"http://127.0.0.1:{monitor_http[0]}/health")
        )
        assert "service_token" not in upstream
        _, health = _read(access, "/health")
        # Removing token deletion failed this assertion; restored it passes.
        assert "service_token" not in health
        assert "token" not in health
        discovery = directory / "service.json"
        metadata = json.loads(discovery.read_text(encoding="utf-8"))
        metadata["service_token"] = "obsolete-test-token"
        discovery.write_text(json.dumps(metadata), encoding="utf-8")
        status, refreshed = _read(access, f"/jobs?limit=100&job_id={job_id}")
        assert status == 401
        assert refreshed["error"] == "unauthorized"
        metadata["service_token"] = "monitor-test-token"
        discovery.write_text(json.dumps(metadata), encoding="utf-8")
        status, refreshed = _read(access, f"/jobs?limit=100&job_id={job_id}")
        assert status == 200
        refreshed_jobs = cast("list[dict[str, object]]", refreshed["jobs"])
        assert len(refreshed_jobs) == 1 and refreshed_jobs[0]["id"] == job_id
        status, activity = _read(access, "/search-activity?limit=100")
        assert status == 200 and "queued" in activity and "recent" in activity
    finally:
        record_finish(job_id, result="completed")


def test_local_bridge_refuses_foreign_origins_and_unrelated_routes(
    browser_bridge: tuple[str, Path],
) -> None:
    access, _ = browser_bridge
    # Bypassing localRequest failed the foreign-origin assertion, then passed
    # after restoration. Bypassing allowedRoute exposes /readiness.
    status, answer = _read(access, "/health", origin="http://example.invalid")
    assert status == 403
    assert answer["message"] == (
        "The monitor accepts only loopback clients at a local host."
    )
    status, answer = _read(access, "/readiness")
    assert status == 404
    assert answer["message"] == "Unknown monitor operation."


@pytest.mark.parametrize("bearer", ["", "not-the-capability", "monitor-test-token"])
def test_bridge_refuses_loopback_callers_without_its_capability(
    browser_bridge: tuple[str, Path], tmp_path: Path, bearer: str
) -> None:
    """Admitting every loopback caller fails the first 401 assertion; restoring
    the capability check passes.

    ``monitor-test-token`` is the backend credential recorded in discovery. It
    authenticates the bridge upstream and must not authenticate a caller here;
    a backend refusal would answer ``error: unauthorized`` instead.
    """
    access, directory = browser_bridge
    discovery = json.loads((directory / "service.json").read_text(encoding="utf-8"))
    assert discovery["service_token"] == "monitor-test-token"
    refusal = {
        "ok": False,
        "message": (
            "The monitor requires its access link. Open the address reported by "
            "`vaultspec-rag server start`, or printed by a monitor you launched "
            "directly."
        ),
    }
    root = tmp_path / "unconfirmed-root"
    root.mkdir()
    for path in (
        "/health",
        "/jobs?limit=100",
        "/search-activity?limit=100",
        "/logs/json?source=service&lines=10",
        "/service-state",
        "/runtime-observations",
        "/repositories?limit=100",
        "/storage/survey",
        "/projects",
        "/lifecycle",
        "/not-an-operation",
    ):
        assert _read(access, path, bearer=bearer) == (401, refusal), path
    mutations: tuple[tuple[str, dict[str, object]], ...] = (
        ("/repositories/enroll", {"root": str(root), "watch": False}),
        ("/projects/evict", {"root": str(root)}),
        ("/pause", {}),
        ("/resume", {}),
        ("/lifecycle/start", {}),
        ("/lifecycle/stop", {}),
        ("/jobs/job/retry", {}),
    )
    for path, body in mutations:
        assert _post(access, path, body, bearer=bearer) == (401, refusal), path
    for method, path in (("PUT", "/jobs/job/desired-state"), ("DELETE", "/jobs/job")):
        request = _request(access, path, bearer=bearer)
        request.method = method
        assert _response(request) == (401, refusal), path
    # The refused mutations left the owner's service as it was.
    status, inventory = _read(access, "/repositories?limit=100")
    assert status == 200
    rows = cast("list[dict[str, object]]", inventory["repositories"])
    assert all(row["root"] != str(root.resolve()) for row in rows)
    status, health = _read(access, "/health")
    assert status == 200
    assert cast("dict[str, object]", health["quiesce"])["state"] == "running"


def test_a_refusal_waits_for_the_request_it_refuses(
    browser_bridge: tuple[str, Path],
) -> None:
    """A refused request is answered only once its body is off the wire.

    A server that answers and closes while the caller is still sending
    resets the connection, and on Windows a reset discards the answer the
    caller has not read yet: the caller sees an aborted connection where
    the refusal should be. A standard client writes its headers and its body
    separately, so every refused mutation is open to it.

    Mutation proof: answering the refusal at once made this fail on the
    timeout expectation, with the refusal on the wire before any body was
    sent; draining the request first made it pass.
    """
    access, _ = browser_bridge
    link = urllib.parse.urlsplit(access)
    assert link.hostname is not None
    assert link.port is not None
    body = b'{"root": "unconfirmed", "watch": false}'
    head = "\r\n".join(
        (
            "POST /api/monitor/repositories/enroll HTTP/1.1",
            f"Host: {link.netloc}",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        )
    )
    with socket.create_connection((link.hostname, link.port), timeout=8) as caller:
        caller.sendall(head.encode())
        caller.settimeout(0.5)
        with pytest.raises(TimeoutError):
            caller.recv(1)
        caller.settimeout(8)
        caller.sendall(body)
        answer = b""
        while chunk := caller.recv(4096):
            answer += chunk
    assert answer.startswith(b"HTTP/1.1 401 ")
    assert b"The monitor requires its access link." in answer


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
        "const { monitorAccess, monitorMiddleware }="
        f"await import({json.dumps(source.as_uri())});"
        "const server=createServer((req,res)=>monitorMiddleware(req,res,()=>{"
        "res.writeHead(404);res.end();}));"
        "await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));"
        "const access=new URL(monitorAccess(server.address().port));"
        "const base=access.origin+'/api/monitor';"
        "const owner='Bearer '+access.hash.slice('#capability='.length);"
        "let bearer=owner;"
        "async function action(path,body,expected){"
        "const response=await fetch(base+path,{method:body===undefined?'GET':'POST',"
        "headers:bearer?{authorization:bearer}:{},"
        "body:body===undefined?undefined:JSON.stringify(body)});"
        "assert.equal(response.status,expected);return response.json();}"
        "try {"
        # Admitting every loopback caller fails these assertions; restoring
        # the capability check passes. No owner command may have been spawned.
        "for(bearer of ['','Bearer never-browser']){"
        "await action('/lifecycle',undefined,401);"
        "await action('/lifecycle/start',{},401);"
        "await action('/lifecycle/stop',{},401);}"
        "assert.equal(calls.length,0);assert.equal(probes.length,0);"
        "bearer=owner;"
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
    browser_bridge: tuple[str, Path],
) -> None:
    access, directory = browser_bridge
    (directory / "service.json").unlink()
    status, answer = _read(access, "/lifecycle")
    assert status == 200
    assert answer["command"] == "service.status"
    assert answer["state"] == "stopped"
    assert answer["data"] == {"service_json_present": False, "state": "stopped"}
    assert not (directory / "service.json").exists()


def test_local_bridge_forwards_operator_inventory_and_controls(
    browser_bridge: tuple[str, Path], tmp_path: Path
) -> None:
    access, _ = browser_bridge
    root = tmp_path / "enrolled-root"
    root.mkdir()
    (root / ".vault").mkdir()
    status, enrollment = _post(
        access, "/repositories/enroll", {"root": str(root), "watch": False}
    )
    assert status == 200 and enrollment["status"] == "enrolled"
    assert enrollment["watcher_status"] == "disabled"
    status, inventory = _read(access, "/repositories?limit=100")
    assert status == 200
    rows = cast("list[dict[str, object]]", inventory["repositories"])
    assert any(row["root"] == str(root.resolve()) and row["enrolled"] for row in rows)
    assert "seats" in inventory
    status, projects = _read(access, "/projects")
    assert status == 200 and projects["projects"] == []
    status, eviction = _post(access, "/projects/evict", {"root": str(root)})
    assert status == 200 and eviction["reason"] == "not_found"
    status, state = _read(
        access, "/service-state?" + urllib.parse.urlencode({"project_root": str(root)})
    )
    assert status == 200 and "quiesce" in state and "root_features" in state
    status, resources = _read(access, "/runtime-observations")
    assert status == 200 and "cpu" in resources and "clients" in resources
    status, survey = _read(access, "/storage/survey?status=unsupported")
    assert status in (400, 409)
    assert survey["error"] in ("bad_request", "server_mode_required")
    status, paused = _post(access, "/pause", {})
    assert status == 200 and paused["ok"] is True
    assert paused["status"] == QuiesceTransitionCode.QUIESCED
    status, resumed = _post(access, "/resume", {})
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
    browser_bridge: tuple[str, Path], host: str, send_origin: bool
) -> None:
    access, _ = browser_bridge
    # Restoring Tailnet Host admission fails this assertion; loopback-only passes.
    status, answer = _read(
        access, "/health", host=host, origin=f"https://{host}" if send_origin else None
    )
    assert status == 403
    assert answer["message"] == (
        "The monitor accepts only loopback clients at a local host."
    )


@pytest.mark.parametrize(
    "host", ["localhost:5420", "vaultspec-rag-monitor.localhost", "[::1]:5420"]
)
def test_bridge_accepts_local_proxy_authorities(
    browser_bridge: tuple[str, Path], host: str
) -> None:
    access, _ = browser_bridge
    status, health = _read(access, "/health", host=host, origin=f"https://{host}")
    assert status == 200
    assert "service_token" not in health
    assert "token" not in health


@pytest.mark.parametrize("host", ["other.taild36992.ts.net", "100.128.0.1"])
def test_bridge_refuses_undeclared_proxy_authorities(
    browser_bridge: tuple[str, Path], host: str
) -> None:
    access, _ = browser_bridge
    # Bypassing host validation failed here; restoring the check passed.
    status, _ = _read(access, "/health", host=host, origin=f"https://{host}")
    assert status == 403


def test_bridge_refuses_a_client_outside_admitted_loopback_addresses(
    browser_bridge: tuple[str, Path], second_loopback_address: str
) -> None:
    access, _ = browser_bridge
    # Removing client-address validation failed this real-source assertion;
    # restoring it passed. Proof: .pytest-tmp/tailnet-client-{broken,restored}.log.
    connection = HTTPConnection(
        "127.0.0.1",
        urllib.parse.urlsplit(access).port,
        timeout=8,
        source_address=(second_loopback_address, 0),
    )
    try:
        connection.request("GET", "/api/monitor/health")
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()


def test_local_bridge_reports_missing_discovery(
    browser_bridge: tuple[str, Path],
) -> None:
    access, directory = browser_bridge
    (directory / "service.json").write_text("{}", encoding="utf-8")
    status, answer = _read(access, "/jobs?limit=100")
    assert status == 503
    assert "No local service is recorded" in str(answer["message"])


def test_browser_projection_rejects_misattributed_production_observations(
    browser_bridge: tuple[str, Path],
    tmp_path: Path,
) -> None:
    access, directory = browser_bridge
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
            access, f"/logs/json?source=service&lines=200&job_id={job_id}"
        )
        _, activity_payload = _read(access, "/search-activity?limit=100")
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
