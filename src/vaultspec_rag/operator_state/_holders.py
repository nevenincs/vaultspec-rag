"""What a process holding an environment is, and what to do about it.

A pid and an image path do not tell an operator what they are looking at. The
processes that hold this product's own environment are nearly always its own:
the resident service, and the stdio adapter an assistant session starts. Each
is ended a different way, and neither is ended by the same instruction as a
stranger's process, so the role is read off the command line and carries its
own remediation.

Nothing here imports torch, and nothing here reads the process table: it
classifies facts the process probe already gathered.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from .._operator_commands import server_stop_command
from .._process_probe import HolderRelation, is_server_launch, server_launch_port

if TYPE_CHECKING:
    from .._process_probe import EnvironmentHolder

__all__ = ["HolderRole", "holder_line", "holder_role", "holder_summary"]

#: How much of a command line is shown. Long enough to recognise a process by,
#: short enough that ten holders stay readable.
_CMDLINE_LIMIT = 160


class HolderRole(StrEnum):
    """What a process holding this product's environment is."""

    SERVICE = "service"
    MCP_ADAPTER = "mcp_adapter"
    DIRECTORY_VISITOR = "directory_visitor"
    UNRECOGNISED = "unrecognised"

    @property
    def label(self) -> str:
        """Plain-language name for the process."""
        return {
            HolderRole.SERVICE: "vaultspec-rag service",
            HolderRole.MCP_ADAPTER: "vaultspec-rag MCP stdio adapter",
            HolderRole.DIRECTORY_VISITOR: "a process working inside this directory",
            HolderRole.UNRECOGNISED: "another process running out of this environment",
        }[self]

    def remediation(self, port: int | None = None) -> str:
        """What clears this holder, naming the command where one exists."""
        return {
            HolderRole.SERVICE: f"stop it with `{server_stop_command(port)}`",
            HolderRole.MCP_ADAPTER: (
                "close the editor or agent session that started it"
            ),
            HolderRole.DIRECTORY_VISITOR: "move this process out of the directory",
            HolderRole.UNRECOGNISED: "end this process",
        }[self]


def holder_role(holder: EnvironmentHolder) -> HolderRole:
    """Classify one holder from how it holds and what it is running.

    The working-directory relation is asked first: such a process is a shell
    or an editor whose own binary has nothing to do with this environment, and
    it is cleared by leaving the directory rather than by ending anything.
    """
    if holder.relation is HolderRelation.WORKING_DIRECTORY:
        return HolderRole.DIRECTORY_VISITOR
    if not is_server_launch(holder.argv):
        return HolderRole.UNRECOGNISED
    return (
        HolderRole.SERVICE
        if server_launch_port(holder.argv) is not None
        else HolderRole.MCP_ADAPTER
    )


def holder_line(
    pid: int,
    role: HolderRole,
    *,
    launcher_pid: int | None = None,
    port: int | None = None,
) -> str:
    """Name one holder, what it is, and what clears it, in one line.

    Two surfaces report holders and they may not show the same detail: the
    install refusal shows the command line, and the readiness snapshot must
    not, because it is also served over HTTP. What they do share is this
    line, so an operator reading either one is told the same thing about the
    same process.
    """
    pids = f"pid {pid}"
    if launcher_pid is not None:
        pids += f" (with its launcher, pid {launcher_pid})"
    named = role.label + (f" on port {port}" if port is not None else "")
    return f"{pids} - {named}: {role.remediation(port)}"


def _shortened(cmdline: str) -> str:
    """Trim a command line to something an operator can read in a list."""
    return (
        cmdline
        if len(cmdline) <= _CMDLINE_LIMIT
        else f"{cmdline[:_CMDLINE_LIMIT].rstrip()}..."
    )


def holder_summary(holder: EnvironmentHolder) -> str:
    """One operator-facing line naming a holder, its role and its remedy.

    The command line is shown rather than the image path alone: every python
    process in one environment has the same image, so the image answers "which
    of these is the service" for none of them.
    """
    line = holder_line(
        holder.pid,
        holder_role(holder),
        launcher_pid=holder.launcher_pid,
        port=server_launch_port(holder.argv),
    )
    what = holder.cmdline or holder.image or "unknown process"
    return f"{line}\n      {_shortened(what)}"
