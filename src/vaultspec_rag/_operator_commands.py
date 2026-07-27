"""The commands we tell an operator to run, spelled once.

A remediation line is not prose. It is an instruction a person pastes into a
shell, so every flag in it is a promise that the flag exists. Those promises
were spread across ten modules as bare strings, and the project already has
evidence they drift: ``server jobs`` once took ``--running``, the option was
replaced by ``--state active``, and two tests now exist for no reason other
than asserting the old spelling does not come back. A guard against a renamed
flag reappearing is a guard against the copies that were missed.

What lives here is only what an operator is told to type. Help text, log lines
and prose that happen to mention the tool are not commands and are not this
module's business.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ._source_types import PublicSourceType

__all__ = [
    "SERVICE_NOT_RUNNING_MESSAGE",
    "IndexCommandOptions",
    "index_command",
    "index_source_option",
    "port_option",
    "server_jobs_command",
    "server_start_command",
    "server_status_command",
]


@dataclass(frozen=True)
class IndexCommandOptions:
    """Optional flags for one operator-facing index command."""

    rebuild: bool = False
    dry_run: bool = False
    dry_run_limit: object | None = None
    full: bool = False
    port: object | None = None


_DEFAULT_INDEX_COMMAND_OPTIONS = IndexCommandOptions()


def port_option(port: object | None) -> str:
    """Return ``" --port N"`` when a port is known, else the empty string.

    Four modules computed this, three of them byte-identical. It is a single
    conditional, which is exactly why it was rewritten rather than shared -
    and why the fourth could quietly key on a different emptiness rule without
    anyone noticing the operator was handed a portless command.

    A port of ``None`` means "not known", and the option is omitted so the
    command falls back to discovery rather than naming a port nobody
    established.
    """
    return "" if port is None else f" --port {port}"


def server_jobs_command(
    port: object | None = None,
    *,
    state: str | None = "active",
    failed: bool = False,
    index: str | None = None,
) -> str:
    """Return the ``server jobs`` invocation that shows the work in question.

    Defaults to the active view, because an operator sent here is asking what
    is running now; a full history buries that behind finished work.

    Args:
        port: Included as ``--port`` when known.
        state: Job state filter, or ``None`` to omit the option entirely.
        failed: Ask for the failed view instead of a state filter.
        index: Restrict to one index source.

    """
    command = "vaultspec-rag server jobs"
    if failed:
        command += " --failed"
    elif state is not None:
        command += f" --state {state}"
    if index is not None:
        command += f" --index {index}"
    return command + port_option(port)


def server_status_command(
    port: object | None = None,
    *,
    verbose: bool = False,
) -> str:
    """Return the ``server status`` invocation an operator should run.

    Thirty-seven sites spelled this, and they had already reached two
    different flag orders for the same command - three sites emitting
    ``--port N --verbose`` and one ``--verbose --port N``. Neither is wrong to
    a shell, which is exactly why the divergence survived: nothing fails, the
    operator just sees the tool describe itself inconsistently. The majority
    order is kept.
    """
    return f"vaultspec-rag server status{port_option(port)}" + (
        " --verbose" if verbose else ""
    )


def server_start_command(
    port: object | None = None,
    *,
    local_only: bool = False,
    qdrant: bool = False,
    updates: bool = False,
) -> str:
    """Return the ``server start`` invocation an operator should run.

    ``local_only`` names the on-disk backend, which is the escape hatch every
    qdrant failure path offers. It was offered in five different sentences
    across the supervisor alone; the command inside them is one thing.

    ``port`` is rendered verbatim, so a caller with no concrete port to offer
    passes the placeholder it wants an operator to substitute.
    """
    command = "vaultspec-rag server start"
    if local_only:
        command += " --local-only"
    if qdrant:
        command += " --qdrant"
    if updates:
        command += " --updates"
    return command + port_option(port)


#: The message every verb prints when it finds no service to talk to. Ten
#: modules carried this sentence verbatim, which is one sentence too many to
#: reword safely: an operator meeting it from two different verbs should not
#: be told two different things, and the command inside it is built here so a
#: rename cannot leave nine copies pointing at a verb that no longer exists.
SERVICE_NOT_RUNNING_MESSAGE = (
    f"Service is not running. Start it with `{server_start_command()}`."
)


def index_source_option(
    source: PublicSourceType,
) -> Literal["vault", "code", "document", "all"]:
    """Return the ``--type`` value for *source*, in the CLI's own spelling.

    ``COMBINED`` is spelled ``all`` on the command line. The translation was
    written inline where the index verb reports what it ran, and the four
    source spellings were hand-enumerated where it offers a rebuild - so a new
    source type would have been missing from the remediation an operator is
    handed, while still being accepted by the flag.
    """
    from ._source_types import PublicSourceType as _Source

    if source is _Source.COMBINED:
        return "all"
    # The remaining members are exactly these three, which is what lets a
    # caller hand this to an API accepting only those spellings.
    return source.value


def index_command(
    source: object | None = None,
    options: IndexCommandOptions = _DEFAULT_INDEX_COMMAND_OPTIONS,
) -> str:
    """Return the ``index`` invocation an operator should run.

    Thirteen sites across six modules spelled a variant of this. Unlike the
    lifecycle verbs they are not one command repeated - each names a different
    combination - which is why counting repeats made this look like it was not
    duplication. The repeated thing is the VOCABULARY: the verb, its flag
    names, their order, and which source spellings exist.
    """
    command = "vaultspec-rag index"
    if options.rebuild:
        command += " --rebuild"
    if source is not None:
        from ._source_types import PublicSourceType as _Source

        resolved = (
            source
            if isinstance(source, _Source)
            else _Source(_Source.COMBINED if source == "all" else source)
        )
        command += f" --type {index_source_option(resolved)}"
    if options.dry_run:
        command += " --dry-run"
    if options.dry_run_limit is not None:
        command += f" --dry-run-limit {options.dry_run_limit}"
    if options.full:
        command += " --full"
    return command + port_option(options.port)
