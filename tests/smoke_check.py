"""Smoke checks for built distribution artifacts.

Run against an installed wheel or sdist to verify that the package is
importable, exposes expected metadata, and that both console-script entry
points (``vaultspec-rag`` and ``vaultspec-search-mcp``) are functional.

Usage from CI::

    uv run --isolated --no-project --with dist/*.whl tests/smoke_check.py

This script is NOT a pytest test suite.  Functions are named ``check_*``
(not ``test_*``) and the file is named ``smoke_check.py`` (not
``*_test.py``) to prevent pytest from collecting it.  Failures call
``sys.exit(1)`` which would kill the pytest runner.
"""

from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _run_script(name: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a console script, falling back to ``python -m`` if not on PATH."""
    script = shutil.which(name)
    if script:
        cmd = [script, *args]
    else:
        module = name.replace("-", "_")
        if name == "vaultspec-search-mcp":
            module = "vaultspec_rag.mcp_server"
        elif name == "vaultspec-rag":
            module = "vaultspec_rag.cli"
        cmd = [sys.executable, "-m", module, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def check_import() -> None:
    try:
        import vaultspec_rag  # noqa: F401
    except ImportError as exc:
        _fail(f"import vaultspec_rag raised {exc}")
    print("PASS: import vaultspec_rag")


def check_version_metadata() -> None:
    version = importlib.metadata.version("vaultspec-rag")
    if not version:
        _fail("importlib.metadata.version returned empty string")
    print(f"PASS: version = {version}")


def check_entry_points_registered() -> None:
    """Verify that [project.scripts] entry points are in wheel metadata."""
    eps = importlib.metadata.entry_points()
    console_scripts = {ep.name for ep in eps if ep.group == "console_scripts"}
    for name in ("vaultspec-rag", "vaultspec-search-mcp"):
        if name not in console_scripts:
            _fail(
                f"console_scripts entry point '{name}' not found in metadata.\n"
                f"  Available: {sorted(console_scripts)}"
            )
    print("PASS: both console_scripts entry points registered")


def check_cli_help() -> None:
    result = _run_script("vaultspec-rag", ["--help"])
    if result.returncode != 0:
        _fail(
            f"vaultspec-rag --help exited {result.returncode}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    print("PASS: vaultspec-rag --help -> exit 0")


def check_mcp_help() -> None:
    """Verify vaultspec-search-mcp starts and exits cleanly with --help."""
    result = _run_script("vaultspec-search-mcp", ["--help"])
    if result.returncode != 0:
        _fail(
            f"vaultspec-search-mcp --help exited {result.returncode}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    print("PASS: vaultspec-search-mcp --help exits 0")


if __name__ == "__main__":
    check_import()
    check_version_metadata()
    check_entry_points_registered()
    check_cli_help()
    check_mcp_help()
    print("\nAll smoke checks passed.")
