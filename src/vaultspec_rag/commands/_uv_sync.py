"""``uv sync`` subprocess invocation and result classification."""

from __future__ import annotations

import logging
import re
import subprocess
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ._models import InstallReport

logger = logging.getLogger(__name__)

#: Matches a PEP 503-normalized requirement string whose distribution name
#: is exactly ``vaultspec-rag`` (any extras/specifier/marker suffix, but not
#: a longer name such as ``vaultspec-rag-extras``).
_RAG_REQUIREMENT = re.compile(r"^vaultspec-rag(?:$|[\[><=~!;@ ])")


def _normalized_requirement(entry: str) -> str:
    """Lowercase and collapse ``-``/``_``/``.`` runs (PEP 503 name rules)."""
    return re.sub(r"[-_.]+", "-", entry.strip().lower())


__all__ = [
    "_classify_uv_add_result",
    "_classify_uv_sync_result",
    "_run_uv_add_mcp_extra",
    "_run_uv_sync_torch",
]

# The package spelling that carries the MCP server's dependency; ``uv add`` of
# this updates the consumer's existing ``vaultspec-rag`` requirement to include
# the optional extra (and resolves it), so a later ``uv run vaultspec-search-mcp``
# has ``mcp`` available.
_MCP_EXTRA_SPEC = "vaultspec-rag[mcp]"


def _detect_rag_placement(target: Path) -> str | None:
    """Where the host pyproject already declares ``vaultspec-rag``.

    Returns ``"runtime"`` for ``[project.dependencies]``, the group name for
    a PEP 735 ``[dependency-groups]`` entry (first match wins, runtime
    checked first), or ``None`` when the host does not declare rag (or has
    no readable pyproject). The existing declaration outranks the declared
    mode when placing the ``[mcp]`` extra: operators move packages between
    groups, and ``uv add`` must update that entry in place rather than
    duplicate rag into runtime dependencies.
    """
    pyproject = target / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        doc: dict[str, object] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError:
        return None
    except tomllib.TOMLDecodeError:  # a host-file problem, not ours
        logger.warning("could not parse %s for mcp-extra placement", pyproject)
        return None

    def _declares_rag(entries: object) -> bool:
        if not isinstance(entries, list):
            return False
        return any(
            isinstance(entry, str)
            and _RAG_REQUIREMENT.match(_normalized_requirement(entry))
            for entry in entries  # pyright: ignore[reportUnknownVariableType]  # tomllib payload
        )

    project = doc.get("project")
    if isinstance(project, dict) and _declares_rag(
        project.get("dependencies")  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]  # tomllib payload
    ):
        return "runtime"
    groups = doc.get("dependency-groups")
    if isinstance(groups, dict):
        for name, entries in groups.items():  # pyright: ignore[reportUnknownVariableType]  # tomllib payload
            if _declares_rag(entries):  # pyright: ignore[reportUnknownArgumentType]  # tomllib payload
                return str(name)  # pyright: ignore[reportUnknownArgumentType]  # tomllib payload
    return None


def _mcp_extra_add_command(placement: str | None, mode: str) -> list[str] | None:
    """The ``uv add`` argv for the extra, or ``None`` when the step must skip.

    Pure so tests can pin the full placement matrix. The host's existing
    declaration wins; the declared mode is the fallback for a host that does
    not declare rag yet. Tool mode never runs ``uv add`` - the tool-mode
    launch carries the extra through ``_vaultspec_mode_tool_spec`` instead.
    """
    if mode == "tool":
        return None
    if placement == "runtime":
        return ["uv", "add", _MCP_EXTRA_SPEC]
    if placement is not None:
        return ["uv", "add", "--group", placement, _MCP_EXTRA_SPEC]
    if mode == "dev":
        return ["uv", "add", "--group", "dev", _MCP_EXTRA_SPEC]
    return ["uv", "add", _MCP_EXTRA_SPEC]


def _run_uv_add_mcp_extra(
    *, target: Path, report: InstallReport, mode: str = "dependency"
) -> None:
    """Ensure the MCP extra with a placement-aware ``uv add``.

    Non-fatal: a missing ``uv`` or a non-zero exit is recorded as a warning, not
    raised, so wiring up the MCP surface never aborts the rest of the install.
    A bare ``uv add`` always targets runtime ``[project.dependencies]``, which
    leaked the extra into published dependency lists on dev-mode hosts; the
    command now follows the host's existing rag declaration (or the declared
    mode when rag is not declared yet). Classification lives in
    :func:`_classify_uv_add_result` so tests can pin every branch without
    forging subprocesses (the same reason the torch-sync helper splits its
    classifier out).
    """
    command = _mcp_extra_add_command(_detect_rag_placement(target), mode)
    if command is None:
        report.mcp_extra_action = "skipped-tool-mode"
        return
    # Remediation strings must name the SAME placement-aware command that
    # ran: telling a dev-mode operator to re-run the bare form would leak
    # the extra into runtime dependencies - the defect this step fixes.
    command_display = subprocess.list2cmdline(command)
    try:
        proc = subprocess.run(
            command,
            cwd=str(target),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        report.mcp_extra_action = "uv-not-found"
        report.warnings.append(
            "MCP extra requested but `uv` is not on PATH; run "
            f"`{command_display}` manually to enable the MCP server "
            "(or re-run install with --no-mcp)."
        )
        return
    except OSError as exc:
        report.mcp_extra_action = "error"
        report.warnings.append(f"{command_display} failed to launch: {exc}")
        return

    action, warning = _classify_uv_add_result(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        command_display=command_display,
    )
    report.mcp_extra_action = action
    if warning is not None:
        report.warnings.append(warning)


def _classify_uv_add_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    command_display: str = f"uv add {_MCP_EXTRA_SPEC}",
) -> tuple[str, str | None]:
    """Classify the placement-aware ``uv add`` by exit code and streams.

    Pure function returning ``(action, warning_or_none)`` for the install
    report; centralising it lets tests pin every branch without a subprocess.
    ``command_display`` is the exact command that ran, so remediation text
    never steers the operator back to the bare (runtime-leaking) form.
    """
    if returncode == 0:
        return "succeeded", None
    stream = stderr.strip() or stdout.strip()
    if stream:
        tail = "\n".join(stream.splitlines()[-5:])
        return (
            "failed",
            f"{command_display} exited with code {returncode}; "
            f"last output:\n{tail}. The MCP server will not start until the "
            f"`mcp` extra is installed; run `{command_display}` manually "
            "or re-run install with --no-mcp.",
        )
    return (
        "failed",
        f"{command_display} exited with code {returncode}.",
    )


def _run_uv_sync_torch(*, target: Path, report: InstallReport) -> None:
    """Shell out to ``uv sync --reinstall-package torch``.

    Non-fatal: failures are recorded as warnings, never raised. Runs
    with ``check=False`` so we can surface uv's own stderr in the
    report without a Python traceback. Result-classification logic
    lives in :func:`_classify_uv_sync_result` so it can be exercised
    by tests without going through ``subprocess`` PATH resolution
    (Windows ``CreateProcess`` only auto-tries ``.exe``, which makes
    ``.cmd`` / ``.bat`` stubs unreliable cross-platform).
    """
    try:
        proc = subprocess.run(
            ["uv", "sync", "--reinstall-package", "torch"],
            cwd=str(target),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        report.torch_sync_action = "uv-not-found"
        report.warnings.append(
            "--sync requested but `uv` is not on PATH; "
            "run `uv sync --reinstall-package torch` manually"
        )
        return
    except OSError as exc:
        report.torch_sync_action = "error"
        report.warnings.append(f"uv sync failed to launch: {exc}")
        return

    action, warning = _classify_uv_sync_result(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    report.torch_sync_action = action
    if warning is not None:
        report.warnings.append(warning)


def _classify_uv_sync_result(
    *, returncode: int, stdout: str, stderr: str
) -> tuple[str, str | None]:
    """Classify the outcome of ``uv sync`` by exit code and streams.

    Pure function: takes the captured streams from ``subprocess.run``
    and returns ``(action, warning_or_none)`` for the install report.
    Centralising the stream-priority logic here lets tests pin every
    branch (success, stderr-failed, stdout-only-failed, both-empty
    failed) without forging subprocesses.

    uv writes resolution failures to stderr most of the time, but
    certain ``--locked`` mismatches and lockfile-conflict renderings
    land on stdout - surface whichever stream carries a payload so
    the user has something actionable to read.
    """
    if returncode == 0:
        return "succeeded", None
    stderr_s = stderr.strip()
    stdout_s = stdout.strip()
    if stderr_s:
        tail = "\n".join(stderr_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stderr lines:\n{tail}",
        )
    if stdout_s:
        tail = "\n".join(stdout_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stdout lines:\n{tail}",
        )
    return (
        "failed",
        f"uv sync --reinstall-package torch exited with code {returncode}",
    )
