"""Shared CLI runtime state: console, logger, and dotenv bootstrap.

Split out of the original ``cli.py`` monolith. Every CLI submodule imports the
shared :data:`console` and :data:`logger` from here so the assembled
package exposes a single Rich console and a single
``vaultspec_rag.cli``-named logger (the latter matters because tests
filter ``caplog`` on that exact logger name).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from typing import IO

__all__ = [
    "_build_console",
    "_stdout_is_tty",
    "console",
    "logger",
]

# Force UTF-8 on Windows to handle Unicode progress spinners.
if sys.platform == "win32":
    from io import TextIOWrapper

    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportUnknownMemberType]  # TextIOWrapper stubs leave _BufferT_co unbound after isinstance
    if isinstance(sys.stderr, TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportUnknownMemberType]  # same

from dotenv import load_dotenv

load_dotenv()

# Logger name pinned to ``vaultspec_rag.cli`` (not ``__name__``) so the
# package and every submodule share one logger; tests filter caplog on
# this exact name.
logger = logging.getLogger("vaultspec_rag.cli")


def _stdout_is_tty() -> bool:
    """Report whether the real stdout is a terminal.

    Interactivity is decided here and nowhere else in the CLI, and it is
    decided from the stream itself rather than from Rich's own terminal
    detection. Rich believes ``FORCE_COLOR``, which CI sets, so it reports a
    terminal for output that is in fact captured or piped; ``isatty`` does not,
    and that difference is the whole reason this function exists.
    """
    isatty = getattr(sys.stdout, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError) as exc:  # stream closed or already replaced
        logger.debug("stdout interactivity check failed: %s", exc)
        return False


def _build_console(
    *,
    interactive: bool,
    file: IO[str] | None = None,
    stderr: bool = False,
) -> Console:
    """Build a CLI console with the project's fixed presentation settings.

    ``highlight=False`` disables Rich's automatic number/path styling (bold
    reprs), keeping operator text parseable.

    ``force_interactive`` gates every live region - spinners and progress bars
    alike. Rich renders a Live only while its console reports itself
    interactive, so a console built with it false animates nothing at all: not
    slowly, not once, but never, with a transient region emitting no content
    whatsoever and a non-transient one emitting a single frame after the work
    it was tracking has already finished. Driving the flag from the real
    terminal is what makes progress visible to an operator while keeping
    captured and piped output plain and deterministic for the scripted
    consumers and tests that parse it.

    ``force_terminal`` is asserted only alongside interactivity, where it is a
    no-op on a genuine terminal and simply makes the pairing explicit. It stays
    unset otherwise so non-interactive streams keep Rich's own detection.
    """
    return Console(
        file=file,
        stderr=stderr,
        legacy_windows=False,
        highlight=False,
        force_terminal=True if interactive else None,
        force_interactive=interactive,
    )


# One console for the whole CLI, and one only. Live regions and ordinary prints
# must share it: Rich positions a live region from what it alone has rendered,
# so a print issued through any second console on the same stream lands inside
# the spinner frame instead of scrolling above it. Sharing this console is what
# lets Rich's render hooks erase the frame, emit the line, and repaint.
#
# Interactivity comes from the real stdout terminal. Deriving it from Rich's
# own detection would be wrong, because that consults the environment: a
# non-empty FORCE_COLOR (even "0") forces the terminal on under the spec Rich
# implements, which would make captured and piped output animate. CI does not
# currently set it - only NO_COLOR="1", precisely so is_terminal falls through
# to isatty() - so nothing is defending against that today, but isatty() is
# what makes this correct regardless of who sets what.
console = _build_console(interactive=_stdout_is_tty())
