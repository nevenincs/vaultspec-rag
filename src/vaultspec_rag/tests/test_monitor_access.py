"""Admission and listener coverage for the credential-free local monitor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_monitor_rejects_remote_peers_before_dispatch() -> None:
    """Restoring Tailnet peer admission fails the 403 assertion; restoration passes.

    Moving admission back inside API forwarding fails the asset assertion;
    restoring the shared entry guard passes.
    """
    node = shutil.which("node")
    assert node is not None
    source = Path(__file__).resolve().parents[2] / "monitor/server/local-service.ts"
    script = (
        "import assert from 'node:assert/strict';"
        "import { IncomingMessage, ServerResponse } from 'node:http';"
        "import { Socket } from 'node:net';"
        f"import {{ monitorMiddleware }} from {json.dumps(source.as_uri())};"
        "const routes=[['GET','/'],['GET','/index.html'],['GET','/monitor.json'],"
        "['GET','/api/monitor/not-an-operation'],['GET','/api/monitor/jobs'],"
        "['GET','/api/monitor/logs/json'],['GET','/api/monitor/repositories'],"
        "['GET','/api/monitor/storage/survey'],['GET','/api/monitor/lifecycle'],"
        "['POST','/api/monitor/lifecycle/start'],['POST','/api/monitor/lifecycle/stop'],"
        "['POST','/api/monitor/pause'],['POST','/api/monitor/resume'],"
        "['POST','/api/monitor/repositories/enroll'],"
        "['POST','/api/monitor/projects/evict'],['POST','/api/monitor/jobs/job/retry'],"
        "['PUT','/api/monitor/jobs/job/desired-state'],"
        "['DELETE','/api/monitor/jobs/job']];"
        "for(const address of ['100.84.254.21','::ffff:100.84.254.21',"
        "'fd7a:115c:a1e0::2c01:feb6','192.168.1.9','127.0.0.2',undefined]){"
        "for(const [method,url] of routes){for(const origin of [undefined,"
        "'http://127.0.0.1']){"
        "const socket=new Socket();"
        "Object.defineProperty(socket,'remoteAddress',{value:address});"
        "const request=new IncomingMessage(socket);request.method=method;"
        "request.url=url;request.headers={host:'127.0.0.1',"
        "'x-forwarded-for':'127.0.0.1','x-real-ip':'127.0.0.1',"
        "'tailscale-user-login':'operator@example.invalid',"
        "authorization:'Bearer untrusted-client-claim',"
        "...(origin?{origin}:{})};"
        "const response=new ServerResponse(request);let body='',dispatched=false;"
        "response.end=value=>{body=String(value);return response;};"
        "monitorMiddleware(request,response,()=>{dispatched=true;});"
        "assert.equal(response.statusCode,403,`${address} ${method} ${url}`);"
        "assert.equal(dispatched,false);"
        "assert.deepEqual(JSON.parse(body),{ok:false,"
        "message:'The monitor accepts only loopback clients at a local host.'});"
        "socket.destroy();}}}"
        "for(const address of ['127.0.0.1','::1','::ffff:127.0.0.1']){"
        "const socket=new Socket();"
        "Object.defineProperty(socket,'remoteAddress',{value:address});"
        "const request=new IncomingMessage(socket);request.url='/';"
        "request.headers={host:'localhost'};const response=new ServerResponse(request);"
        "let dispatched=false;"
        "monitorMiddleware(request,response,()=>{dispatched=true;});"
        "assert.equal(dispatched,true,address);socket.destroy();}"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["dev", "preview"])
@pytest.mark.parametrize("wildcard", [False, True])
def test_vite_monitor_listener_and_admission(
    tmp_path: Path, mode: str, wildcard: bool
) -> None:
    """Restoring the manifest wildcard bind fails the listener assertion;
    restoring loopback passes. Bypassing admission fails the peer assertion.
    Removing upgrade admission fails the remote WebSocket assertion;
    restoring admission passes while local HMR still upgrades.
    """
    node = shutil.which("node")
    assert node is not None
    root = Path(__file__).resolve().parents[3]
    script = (
        "import assert from 'node:assert/strict';"
        "import { request } from 'node:http';"
        "import { createConnection } from 'node:net';"
        "import { createServer, preview } from 'vite';"
        "const {mode,wildcard}=JSON.parse(process.argv[1]);"
        "const settings={port:0,strictPort:true,...(wildcard?{host:'0.0.0.0'}:{})};"
        "const runtime=mode==='dev'?await createServer({server:settings}):"
        "await preview({preview:settings});"
        "try {if(mode==='dev')await runtime.listen();"
        "const {address,port}=runtime.httpServer.address();"
        "assert.equal(address,wildcard?'0.0.0.0':'127.0.0.1','listener address');"
        "if(!wildcard){await new Promise((resolve,reject)=>{"
        "const socket=createConnection({host:'127.0.0.2',port});"
        "socket.setTimeout(3000,()=>{socket.destroy();reject(new Error('timeout'));});"
        "socket.once('connect',()=>{socket.destroy();"
        "reject(new Error('monitor accepted a nonlocal destination'));});"
        "socket.once('error',error=>{assert.equal(error.code,'ECONNREFUSED');"
        "resolve();});});}"
        "const base='http://127.0.0.1:'+port;"
        "assert.equal((await fetch(base+'/')).status,200);"
        "assert.equal((await fetch(base+'/api/monitor/health')).status,503);"
        "for(const path of ['/','/index.html','/api/monitor/health']){"
        "const status=await new Promise((resolve,reject)=>{"
        "const call=request(base+path,{localAddress:'127.0.0.2',"
        "headers:{host:'127.0.0.1','x-forwarded-for':'127.0.0.1'}},response=>{"
        "response.resume();resolve(response.statusCode);});"
        "call.once('error',reject);call.end();});"
        "assert.equal(status,403,'remote peer '+path);}"
        "if(mode==='dev'){"
        "const upgrade=(source,host,protocol,origin)=>new Promise((resolve,reject)=>{"
        "const call=request(base+'/?token='+runtime.config.webSocketToken,"
        "{localAddress:source,headers:{host,connection:'Upgrade',upgrade:'websocket',"
        "'sec-websocket-version':'13','sec-websocket-key':'dGhlIHNhbXBsZSBub25jZQ==',"
        "'sec-websocket-protocol':protocol,...(origin?{origin}:{})}});"
        "call.once('upgrade',(response,socket)=>{socket.destroy();"
        "resolve(response.statusCode);});"
        "call.once('response',response=>{response.resume();"
        "resolve(response.statusCode);});"
        "call.once('error',error=>resolve(error.code));"
        "call.setTimeout(3000,()=>{call.destroy();"
        "reject(new Error('upgrade timeout'));});"
        "call.end();});"
        "for(const protocol of ['vite-hmr','vite-ping']){"
        "assert.equal(await upgrade('127.0.0.1','127.0.0.1:'+port,protocol,base),101);"
        "for(const [source,host] of [['127.0.0.2','127.0.0.1'],"
        "['127.0.0.1','100.84.254.21']]){"
        "assert.equal(await upgrade(source,host,protocol),"
        "'ECONNRESET','remote WebSocket '+protocol);}}}"
        "} finally {if(mode==='dev')await runtime.close();"
        "else {runtime.httpServer.closeAllConnections();"
        "await new Promise(resolve=>runtime.httpServer.close(resolve));}}"
    )
    environment = dict(os.environ)
    environment.pop("VAULTSPEC_RAG_PORT", None)
    environment["VAULTSPEC_RAG_STATUS_DIR"] = str(tmp_path)
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            script,
            json.dumps({"mode": mode, "wildcard": wildcard}),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr
