"""Run the canonical native smoke under scoped OS outbound-network denial."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from tools.binaries.bun_pins import BUN_EXECUTABLES
from tools.binaries.bun_toolchain import provision_bun
from tools.binaries.native import host_target_triple
from tools.monitor.smoke import probe
from vaultspec_rag.qdrant_runtime._provision import verify_native_binary

CONTROL_HOST = "1.1.1.1"
CONTROL_PORT = 443
MAC_PROFILE = """(version 1)
(allow default)
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*"))
"""
FIREWALL = """
$ErrorActionPreference = 'Stop'
if ($env:MONITOR_FIREWALL_ACTION -eq 'check') {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $adminRole = [Security.Principal.WindowsBuiltInRole]::Administrator
    if (-not $principal.IsInRole($adminRole)) {
        throw 'Windows OS-offline verification requires an elevated test account'
    }
    if ((Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -ne 0) {
        throw 'Every firewall profile must be enabled for offline proof'
    }
    exit 0
}
$spec = Get-Content -LiteralPath $env:MONITOR_FIREWALL_SPEC -Raw | ConvertFrom-Json
if ($env:MONITOR_FIREWALL_ACTION -eq 'remove') {
    Get-NetFirewallRule -Group $spec.group -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    exit 0
}
foreach ($program in $spec.programs) {
    $rule = New-NetFirewallRule -DisplayName $spec.group -Group $spec.group `
        -Direction Outbound -Action Block -Profile Any -Program $program -Enabled True
    $active = Get-NetFirewallRule -PolicyStore ActiveStore -Name $rule.Name
    $filter = $active | Get-NetFirewallApplicationFilter
    if ($active.Enabled -ne 'True' -or $active.Action -ne 'Block' -or
        $active.Direction -ne 'Outbound' -or $filter.Program -ne $program) {
        throw 'The executable outbound rule is not active'
    }
}
"""
BUN_CONTROL = """
import { createConnection } from 'node:net';
const socket = createConnection({ host: '1.1.1.1', port: 443 });
socket.setTimeout(5000);
socket.on('connect', () => { socket.destroy(); console.log('connected'); });
socket.on('error', error => { console.error(error.code); process.exit(1); });
socket.on('timeout', () => { console.error('timeout'); process.exit(1); });
"""


def external_connection() -> bool:
    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=5):
            return True
    except OSError:
        return False


def require_denial() -> None:
    if external_connection():
        raise RuntimeError("OS offline proof refused: external TCP still connects")


def macos_launcher() -> tuple[str, ...]:
    launcher = ("/usr/bin/sandbox-exec", "-p", MAC_PROFILE)
    subprocess.run(
        [*launcher, sys.executable, "-m", "tools.monitor.offline", "--check-outbound"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        timeout=15,
    )
    return launcher


def bun_connection(binary: Path, launch_prefix: tuple[str, ...] = ()) -> bool:
    verify_native_binary(binary, BUN_EXECUTABLES[host_target_triple()])
    result = subprocess.run(
        [*launch_prefix, str(binary), "--eval", BUN_CONTROL],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode == 0:
        if result.stdout.strip() != "connected":
            raise RuntimeError("The network control produced no connection evidence")
        return True
    if result.returncode != 1 or result.stderr.strip() not in {
        "EACCES",
        "EPERM",
        "ETIMEDOUT",
        "ECONNREFUSED",
        "ENETUNREACH",
        "EHOSTUNREACH",
        "timeout",
    }:
        raise RuntimeError(f"Unexpected network control failure: {result.stderr}")
    return False


def windows_probe(
    directory: Path,
    binary: Path,
    digest: str,
    identity: dict[str, object],
    browser: Path,
) -> dict[str, object]:
    powershell = str(
        Path(os.environ["SYSTEMROOT"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", FIREWALL],
        env={**os.environ, "MONITOR_FIREWALL_ACTION": "check"},
        check=True,
        timeout=15,
    )
    bun = provision_bun(
        Path(tempfile.gettempdir()) / "vaultspec-bun", host_target_triple()
    )
    control = directory / "network-control.exe"
    shutil.copy2(bun, control)
    if not bun_connection(control):
        raise RuntimeError("The external TCP positive control did not connect")
    group = "vaultspec-monitor-" + uuid.uuid4().hex
    specification = directory / "firewall.json"
    specification.write_text(
        json.dumps(
            {
                "group": group,
                "programs": [str(binary), str(control)],
            }
        ),
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "MONITOR_FIREWALL_SPEC": str(specification),
        "MONITOR_FIREWALL_ACTION": "add",
    }
    try:
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", FIREWALL],
            env=environment,
            check=True,
            timeout=60,
        )
        if bun_connection(control):
            raise RuntimeError(
                "OS offline proof refused: blocked control still connects"
            )
        return probe(binary, digest, identity, browser)
    finally:
        environment["MONITOR_FIREWALL_ACTION"] = "remove"
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", FIREWALL],
            env=environment,
            check=True,
            timeout=60,
        )


def probe_offline(
    binary: Path,
    expected_sha256: str,
    identity: dict[str, object],
    browser: Path,
) -> dict[str, object]:
    verify_native_binary(binary, expected_sha256)
    with tempfile.TemporaryDirectory(prefix="monitor-os-offline-") as scratch:
        directory = Path(scratch)
        if os.name == "nt":
            result = windows_probe(
                directory, binary.absolute(), expected_sha256, identity, browser
            )
            mechanism = "Windows Firewall executable rules"
            scope = "monitor and pinned Bun control; browser harness outside policy"
        elif sys.platform == "linux":
            bun = provision_bun(
                Path(tempfile.gettempdir()) / "vaultspec-bun", host_target_triple()
            )
            if not bun_connection(bun):
                raise RuntimeError("The external TCP positive control did not connect")
            launcher = (sys.executable, str(Path(__file__).with_name("linux_exec.py")))
            control_prefix = (*launcher, BUN_EXECUTABLES[host_target_triple()])
            if bun_connection(bun, control_prefix):
                raise RuntimeError("OS offline proof refused: blocked control connects")
            result = probe(
                binary,
                expected_sha256,
                identity,
                browser,
                (*launcher, expected_sha256),
            )
            mechanism = "Linux seccomp outbound connect/datagram denial"
            scope = "monitor and pinned Bun control; accepted loopback HTTP preserved"
        elif sys.platform == "darwin":
            if not external_connection():
                raise RuntimeError("The external TCP positive control did not connect")
            result = probe(binary, expected_sha256, identity, browser, macos_launcher())
            mechanism = "macOS Seatbelt"
            scope = "monitor and Python network control; loopback HTTP preserved"
        else:
            raise RuntimeError("No native OS isolation method for this platform")
    return {
        **result,
        "os_offline_verified": True,
        "os_offline": {
            "mechanism": mechanism,
            "scope": scope,
            "external_tcp_positive_control": True,
            "external_tcp_denied": True,
            "loopback_http_verified": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-outbound", action="store_true", required=True)
    parser.parse_args()
    require_denial()


if __name__ == "__main__":
    main()
