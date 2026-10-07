"""Run the canonical native smoke under scoped OS outbound-network denial."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from tools.binaries.bun_pins import BUN_EXECUTABLES
from tools.binaries.bun_toolchain import provision_bun
from tools.binaries.native import host_target_triple
from tools.monitor.smoke import probe
from vaultspec_rag._fd_lock import lock_fd_exclusive, unlock_fd
from vaultspec_rag.qdrant_runtime._provision import verify_native_binary

if TYPE_CHECKING:
    from collections.abc import Iterator

CONTROL_HOST = "1.1.1.1"
CONTROL_PORT = 443
MAC_PROFILE = """(version 1)
(allow default)
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*"))
"""
# Adding a firewall rule takes an Administrator, and a CI runner account is
# deliberately not one. So the rules are added once per host, for two fixed
# program paths in a directory the runner may write, and every proof after
# that only copies bytes into those paths and shows that they cannot connect.
DENIED_DIRECTORY = "MONITOR_OUTBOUND_DENIED_DIR"
DENIED_GROUP = "vaultspec-monitor-outbound-denied"
MONITOR_SLOT = "monitor.exe"
CONTROL_SLOT = "network-control.exe"
CLAIM = "claim.lock"
CLAIM_WAIT_SECONDS = 900.0
PROVISION = """
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$adminRole = [Security.Principal.WindowsBuiltInRole]::Administrator
if (-not $principal.IsInRole($adminRole)) {
    throw 'Provisioning outbound denial requires an elevated session'
}
if ((Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -ne 0) {
    throw 'Every firewall profile must be enabled for offline proof'
}
$spec = Get-Content -LiteralPath $env:MONITOR_FIREWALL_SPEC -Raw | ConvertFrom-Json
foreach ($program in $spec.programs) {
    Get-NetFirewallRule -Group $spec.group -ErrorAction SilentlyContinue |
        Where-Object { ($_ | Get-NetFirewallApplicationFilter).Program -eq $program } |
        Remove-NetFirewallRule
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
const [host, port] = process.argv.slice(1);
const socket = createConnection({ host, port: Number(port) });
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
        [
            *launch_prefix,
            str(binary),
            "--eval",
            BUN_CONTROL,
            CONTROL_HOST,
            str(CONTROL_PORT),
        ],
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


def denied_directory() -> Path:
    """Return the host's provisioned outbound-denied directory."""
    configured = os.environ.get(DENIED_DIRECTORY, "")
    directory = Path(configured)
    if not configured or not directory.is_absolute() or not directory.is_dir():
        raise RuntimeError(
            f"Windows OS-offline verification needs {DENIED_DIRECTORY} to name a "
            "directory provisioned from an elevated session with "
            "`python -m tools.monitor.offline --provision-denied-directory <dir>`"
        )
    return directory


@contextlib.contextmanager
def claimed(directory: Path) -> Iterator[None]:
    """Hold the denied directory's two program paths for one proof at a time."""
    descriptor = os.open(directory / CLAIM, os.O_RDWR | os.O_CREAT)
    try:
        deadline = time.monotonic() + CLAIM_WAIT_SECONDS
        while True:
            try:
                lock_fd_exclusive(descriptor)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Another offline proof still holds the denied directory"
                    ) from None
                time.sleep(1)
        try:
            yield
        finally:
            unlock_fd(descriptor)
    finally:
        os.close(descriptor)


def provision_denied_directory(directory: Path) -> None:
    """Deny outbound traffic to the two program paths a proof occupies."""
    if os.name != "nt":
        raise RuntimeError("Only Windows proves outbound denial by program path")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    powershell = str(
        Path(os.environ["SYSTEMROOT"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    with tempfile.TemporaryDirectory(prefix="monitor-os-offline-") as scratch:
        specification = Path(scratch) / "firewall.json"
        specification.write_text(
            json.dumps(
                {
                    "group": DENIED_GROUP,
                    "programs": [
                        str(directory / MONITOR_SLOT),
                        str(directory / CONTROL_SLOT),
                    ],
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", PROVISION],
            env={**os.environ, "MONITOR_FIREWALL_SPEC": str(specification)},
            check=True,
            timeout=120,
        )


def windows_probe(
    binary: Path,
    digest: str,
    identity: dict[str, object],
    browser: Path,
) -> dict[str, object]:
    directory = denied_directory()
    bun = provision_bun(
        Path(tempfile.gettempdir()) / "vaultspec-bun", host_target_triple()
    )
    if not bun_connection(bun):
        raise RuntimeError("The external TCP positive control did not connect")
    monitor = directory / MONITOR_SLOT
    control = directory / CONTROL_SLOT
    with claimed(directory):
        try:
            # The control occupies BOTH paths before the monitor takes its
            # own, so the denial the monitor runs under is one this proof
            # watched refuse a connection, not one it was told exists.
            for slot in (control, monitor):
                shutil.copy2(bun, slot)
                if bun_connection(slot):
                    raise RuntimeError(
                        "OS offline proof refused: blocked control still connects"
                    )
            shutil.copy2(binary, monitor)
            verify_native_binary(monitor, digest)
            return probe(monitor, digest, identity, browser)
        finally:
            for slot in (monitor, control):
                slot.unlink(missing_ok=True)


def probe_offline(
    binary: Path,
    expected_sha256: str,
    identity: dict[str, object],
    browser: Path,
) -> dict[str, object]:
    verify_native_binary(binary, expected_sha256)
    if os.name == "nt":
        result = windows_probe(binary.absolute(), expected_sha256, identity, browser)
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
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-outbound", action="store_true")
    action.add_argument("--provision-denied-directory", type=Path)
    args = parser.parse_args()
    if args.provision_denied_directory:
        provision_denied_directory(args.provision_denied_directory)
    else:
        require_denial()


if __name__ == "__main__":
    main()
