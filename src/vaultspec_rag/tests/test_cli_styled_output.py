"""The styled print primitive: colour on a terminal, the same text everywhere.

Operator lines carry paths, commands and service messages, so a bracketed
substring must print as written rather than be read as Rich markup, and the
characters a pipe receives must be exactly the plain line.
"""

from __future__ import annotations

import io
import re

import pytest

import vaultspec_rag.cli as _cli

from ..cli._core import _build_console
from ..cli._render import (
    COMMAND,
    HEADING,
    _display_search_results,
    _print_next_action,
    _styled,
)

pytestmark = pytest.mark.unit

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_CYAN = "\x1b[36m"
_BOLD = "\x1b[1m"


def _capture(monkeypatch: pytest.MonkeyPatch, *, terminal: bool) -> io.StringIO:
    """Hand the production renderers a real console that records to a buffer.

    Styling reaches only a colour terminal, and the CLI builds its one console
    at import from the real stdout, so swapping the output sink is the only way
    to read the styled bytes. Every renderer under test runs unchanged.
    """
    buffer = io.StringIO()
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        _cli, "console", _build_console(interactive=terminal, file=buffer)
    )
    return buffer


def test_bracketed_data_prints_literally_on_a_colour_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutation proof: appending segments through ``Text.from_markup`` made the
    # ``[red]`` tag vanish from the output and this assertion fail.
    buffer = _capture(monkeypatch, terminal=True)
    _styled("path: ", ("tests/[red]/case.py", COMMAND))
    written = _ANSI_RE.sub("", buffer.getvalue())
    assert written == "path: tests/[red]/case.py\n"


def test_a_pipe_receives_the_plain_line(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = _capture(monkeypatch, terminal=False)
    _styled(("Readiness:", HEADING), " ", ("ready for requests", "green"))
    assert buffer.getvalue() == "Readiness: ready for requests\n"


def test_the_next_action_command_is_coloured(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = _capture(monkeypatch, terminal=True)
    _print_next_action("vaultspec-rag server jobs")
    written = buffer.getvalue()
    assert f"{_CYAN}vaultspec-rag server jobs" in written
    assert _ANSI_RE.sub("", written) == "Next action:\n  vaultspec-rag server jobs\n"


def test_a_search_hit_heads_its_passage_in_bold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = _capture(monkeypatch, terminal=True)
    _display_search_results(
        [{"path": "src/app.py", "line_start": 3, "line_end": 4, "snippet": "x = 1"}],
        "code",
    )
    written = buffer.getvalue()
    assert f"{_BOLD}1. src/app.py:3-4" in written
    assert _ANSI_RE.sub("", written).splitlines()[1] == "   x = 1"
