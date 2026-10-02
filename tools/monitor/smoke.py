"""Probe finalized or acquired monitor bytes with an isolated home and cwd."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlsplit

from tools.binaries.build_pyapp import glibc_version, required_symbol_versions
from tools.binaries.native import host_target_triple
from vaultspec_rag._loopback_http import LOOPBACK_OPENER
from vaultspec_rag.qdrant_runtime._provision import verify_native_binary


def isolated_environment(directory: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}
    }
    environment.update(
        {
            "HOME": str(directory),
            "USERPROFILE": str(directory),
            "XDG_CONFIG_HOME": str(directory / "config"),
            "XDG_DATA_HOME": str(directory / "data"),
            "APPDATA": str(directory / "appdata"),
            "LOCALAPPDATA": str(directory / "localappdata"),
            "PATH": str(directory / "empty-path"),
            "VAULTSPEC_RAG_STATUS_DIR": str(directory / "status"),
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(directory / "storage"),
        }
    )
    (directory / "empty-path").mkdir()
    (directory / ".env").write_text("VAULTSPEC_RAG_PORT=1\n", encoding="utf-8")
    (directory / "bunfig.toml").write_text(
        'preload = ["./ambient.js"]\n', encoding="utf-8"
    )
    (directory / "ambient.js").write_text(
        'import {writeFileSync} from "node:fs"; writeFileSync("autoloaded", "bad");',
        encoding="utf-8",
    )
    return environment


def installed_browser() -> Path:
    """Use enrolled Chromium-family browsers; release checks never download one."""
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        if executable := shutil.which(name):
            return Path(executable)
    for candidate in (
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ):
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "Native monitor verification requires installed Chrome/Chromium/Edge"
    )


def output_line(process: subprocess.Popen[str]) -> str:
    answer: queue.Queue[str] = queue.Queue()
    if process.stdout is None:
        raise RuntimeError("The probe child has no stdout pipe")
    output = process.stdout
    threading.Thread(target=lambda: answer.put(output.readline()), daemon=True).start()
    try:
        return answer.get(timeout=30)
    except queue.Empty as exc:
        raise RuntimeError(
            "The monitor did not report readiness within 30 seconds"
        ) from exc


def get(url: str) -> tuple[int, str, bytes]:
    try:
        response = LOOPBACK_OPENER.open(url, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        status = response.status
        if not isinstance(status, int):
            raise RuntimeError("The monitor did not return an HTTP status")
        return (
            status,
            response.headers.get("Content-Type", ""),
            response.read(32 << 20),
        )


def browser_probe(url: str, executable: Path, directory: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError(
            "The browser probe needs Node; the delivered monitor does not"
        )
    script = Path(__file__).resolve().parents[2] / "dev/monitor-browser.mjs"
    process = subprocess.Popen(
        [node, str(script), str(executable), str(directory / "browser"), url],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        ready = json.loads(output_line(process))
        if not ready.get("ready") or process.stdin is None:
            raise RuntimeError("The browser probe did not become ready")
        for command in (
            {
                "operation": "wait",
                "expression": "document.readyState === 'complete' && "
                "document.querySelector('#root')?.textContent.includes('Dashboard')",
            },
            {
                "operation": "wait",
                "expression": "document.fonts.ready.then(() => "
                "getComputedStyle(document.querySelector('header'))"
                ".position === 'fixed')",
            },
            {"operation": "evidence"},
            {"operation": "close"},
        ):
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            if command["operation"] != "close":
                result = json.loads(output_line(process))
                if not result.get("ok") or (
                    command["operation"] == "evidence" and result["value"]["errors"]
                ):
                    raise RuntimeError(f"Delivered-page browser check failed: {result}")
        process.wait(timeout=15)
        if process.returncode:
            detail = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"The delivered-page browser probe failed: {detail}")
    finally:
        if process.poll() is None:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()


def probe_assets(url: str, expected: dict[str, object]) -> int:
    status, content_type, content = get(url + "/monitor.json")
    if status != 200 or not content_type.startswith("application/json"):
        raise RuntimeError("The monitor returned no build/asset identity")
    metadata = json.loads(content)
    if any(
        metadata.get(key) != value
        for key, value in expected.items()
        if key != "command"
    ):
        raise RuntimeError("The served monitor identity differs from --version")
    assets = metadata["assets"]
    for route, entry in assets.items():
        status, content_type, body = get(url + route)
        if (
            status != 200
            or content_type != entry["content_type"]
            or len(body) != entry["size"]
            or hashlib.sha256(body).hexdigest() != entry["sha256"]
        ):
            raise RuntimeError(f"Embedded asset bytes or MIME mismatch: {route}")
    status, _, html = get(url + "/")
    if status != 200 or html != get(url + "/index.html")[2]:
        raise RuntimeError("The delivered root is not the embedded index.html")
    status, _, unavailable = get(url + "/api/monitor/health")
    payload = json.loads(unavailable)
    if (
        status != 503
        or payload.get("ok") is not False
        or not payload["message"].startswith("No local service")
    ):
        raise RuntimeError(
            "Offline startup did not preserve backend-unavailable semantics"
        )
    # A foreign Origin must not reach any local service capability.
    from urllib.request import Request

    request = Request(
        url + "/api/monitor/health", headers={"Origin": "http://foreign.invalid"}
    )
    try:
        with LOOPBACK_OPENER.open(request, timeout=10) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
        error.close()
    if status != 403:
        raise RuntimeError("The delivered bridge admitted a foreign origin")
    return len(assets)


def probe_request_bounds(url: str) -> None:
    """Exercise the shared operation allowlist and request limit in native bytes."""
    target = urlsplit(url)
    if target.hostname is None:
        raise ValueError("The native probe requires a monitor URL with a host")
    for route, body, expected in (
        ("/api/monitor/not-an-operation", b"{}", {404}),
        ("/api/monitor/lifecycle/start", b"broken json", {400}),
        ("/api/monitor/lifecycle/start", b'{"unexpected":true}', {400}),
        ("/index.html", b"{}", {405}),
        (
            "/api/monitor/lifecycle/start",
            b'{"padding":"' + b"x" * 9000 + b'"}',
            {503, None},
        ),
    ):
        connection = http.client.HTTPConnection(
            target.hostname, target.port, timeout=10
        )
        try:
            connection.request(
                "POST", route, body, {"Content-Type": "application/json"}
            )
            try:
                response = connection.getresponse()
                status = response.status
                response.read()
            except (http.client.RemoteDisconnected, ConnectionResetError):
                status = None
            if status not in expected:
                raise RuntimeError(f"Native request boundary failed: {route}: {status}")
        finally:
            connection.close()


def partial_request(port: int) -> socket.socket:
    connection = socket.create_connection(("127.0.0.1", port), timeout=5)
    connection.sendall(
        b"POST /api/monitor/lifecycle/start HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\nContent-Type: application/json\r\n"
        b"Content-Length: 12\r\n\r\n{"
    )
    return connection


def platform_evidence(binary: Path, target: str) -> dict[str, str | None]:
    """Measure the monitor independently of the enclosing PyApp bundle floor."""
    versions = (
        [
            version
            for requirement in required_symbol_versions(binary)
            if (version := glibc_version(requirement)) is not None
        ]
        if target.endswith("linux-gnu")
        else []
    )
    if target.endswith("linux-gnu") and not versions:
        raise RuntimeError("The monitor has no measurable glibc requirements")
    return {
        "glibc_required": (
            ".".join(str(part) for part in max(versions)) if versions else None
        ),
    }


def exercise_monitor(
    process: subprocess.Popen[str],
    starting_port: int,
    metadata: dict[str, object],
    browser: Path | None,
    directory: Path,
) -> int:
    ready = output_line(process).strip()
    prefix = "vaultspec.monitor.ready "
    if not ready.startswith(prefix):
        raise RuntimeError(f"The monitor readiness protocol failed: {ready}")
    port = int(ready.removeprefix(prefix))
    if port <= starting_port:
        raise RuntimeError("Managed monitor did not allocate upward")
    url = f"http://127.0.0.1:{port}"
    count = probe_assets(url, metadata)
    probe_request_bounds(url)
    partial_request(port).close()
    if get(url + "/monitor.json")[0] != 200:
        raise RuntimeError("The monitor did not recover from client cancellation")
    if browser:
        browser_probe(url, browser, directory)
    if (directory / "autoloaded").exists() or (directory / "status").exists():
        raise RuntimeError(
            "Shell startup loaded ambient config or created service state"
        )
    if process.stdin is None:
        raise RuntimeError("The managed monitor has no parent pipe")
    with partial_request(port):
        process.stdin.close()
        process.wait(timeout=5)
    if process.returncode:
        raise RuntimeError("Managed monitor did not stop cleanly on parent EOF")
    return count


def probe(
    binary: Path,
    expected_sha256: str,
    identity: dict[str, object],
    browser: Path | None,
    launch_prefix: tuple[str, ...] = (),
) -> dict[str, object]:
    binary = binary.absolute()
    target = host_target_triple()
    platform = platform_evidence(binary, target)
    with tempfile.TemporaryDirectory(prefix="monitor-delivered-") as scratch:
        directory = Path(scratch)
        environment = isolated_environment(directory)
        verify_native_binary(binary, expected_sha256)
        version = subprocess.run(
            [*launch_prefix, str(binary), "--version", "--json"],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        metadata = cast("dict[str, object]", json.loads(version.stdout))
        if any(metadata.get(key) != value for key, value in identity.items()):
            raise RuntimeError(
                "The monitor does not report the requested release identity"
            )
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            starting_port = int(occupied.getsockname()[1])
            verify_native_binary(binary, expected_sha256)
            refused = subprocess.run(
                [*launch_prefix, str(binary), "--port", str(starting_port)],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if refused.returncode == 0 or "EADDRINUSE" not in refused.stderr:
                raise RuntimeError("A strict occupied monitor port was not refused")
            verify_native_binary(binary, expected_sha256)
            process = subprocess.Popen(
                [
                    *launch_prefix,
                    str(binary),
                    "--managed",
                    "--port",
                    str(starting_port),
                ],
                cwd=directory,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                count = exercise_monitor(
                    process, starting_port, metadata, browser, directory
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
    return {
        "schema": "vaultspec.monitor.smoke.v1",
        **metadata,
        "sha256": expected_sha256,
        "target": target,
        "platform": platform,
        "assets_verified": count,
        "browser_verified": browser is not None,
        "isolated_shell": True,
        "occupied_port_refused": True,
        "parent_eof_shutdown": True,
        "request_bounds_verified": True,
        "cancelled_request_recovered": True,
        "partial_request_shutdown": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = probe(
        args.binary,
        args.expected_sha256,
        {
            "command": "vaultspec-rag-monitor",
            "version": args.version,
            "source_revision": args.source_revision,
        },
        args.browser,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
