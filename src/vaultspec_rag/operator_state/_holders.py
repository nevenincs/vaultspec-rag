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

from .._operator_commands import server_start_command, server_stop_command
from .._process_probe import HolderRelation, is_server_launch, server_launch_port

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .._process_probe import EnvironmentHolder

__all__ = [
    "HolderRole",
    "holder_line",
    "holder_role",
    "holder_summary",
    "holder_wire",
]

#: How much of a command line is shown. Long enough to recognise a process by,
#: short enough that ten holders stay readable.
_CMDLINE_LIMIT = 160

#: How much of the head survives the elision. The head carries the
#: interpreter, which is the same for every holder in one environment; the
#: arguments are what tell them apart, so a line too long to show keeps its
#: tail and loses the middle of the path. A cut from the end instead reads as
#: a list of identical interpreters, and did: an environment under a long
#: directory pushed every argument past the limit.
_CMDLINE_HEAD = 40
_ELISION = "..."


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
        """What this holder needs once the repair has been applied.

        The repair changes the environment in place and nothing has to stop
        for it, so a process running out of that environment is not an
        obstacle to clear: it is a process still running the build it
        imported at startup, and a restart is what moves it onto the new one.
        Only a process holding the tree by working directory is asked to
        move, because its own binary has nothing to do with the environment.
        """
        return {
            HolderRole.SERVICE: (
                f"restart it with `{server_stop_command(port)}` then "
                f"`{server_start_command(port)}` to pick up the new build"
            ),
            HolderRole.MCP_ADAPTER: (
                "restart the editor or agent session that started it"
            ),
            HolderRole.DIRECTORY_VISITOR: "move this process out of the directory",
            HolderRole.UNRECOGNISED: "restart it once the repair is done",
        }[self]


def holder_wire(
    holders: Sequence[EnvironmentHolder], *, limit: int
) -> dict[str, object]:
    """Serialise a holder list for a report, bounded and counted.

    One serialisation for every surface that publishes holders. Two of them
    existed, with different keys and different bounds, so the same machine
    described itself two ways depending on which command was asked.

    Command lines are left out of THIS shape, which travels over HTTP from
    the readiness route: an argument vector can carry material an operator
    never chose to publish, and the role and the port say what the process
    is without it. The lines an operator reads locally, built by
    :func:`holder_summary`, do show the command line, because that is what
    tells two processes of the same image apart in front of them. The total
    is carried because a capped list with no count reads as the whole story.
    """
    return {
        "total": len(holders),
        "holders": [
            {
                "pid": holder.pid,
                "launcher_pid": holder.launcher_pid,
                "relation": str(holder.relation),
                "role": str(holder_role(holder)),
                "port": server_launch_port(holder.argv),
                "image": holder.image,
            }
            for holder in holders[:limit]
        ],
    }


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
    """Trim a command line to something an operator can read in a list.

    The middle goes, not the end: what identifies a process to an operator is
    what it was asked to do, and that is at the end of the line.
    """
    if len(cmdline) <= _CMDLINE_LIMIT:
        return cmdline
    tail = _CMDLINE_LIMIT - _CMDLINE_HEAD - len(_ELISION)
    return f"{cmdline[:_CMDLINE_HEAD].rstrip()}{_ELISION}{cmdline[-tail:].lstrip()}"


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
