"""Shared CLI runtime state: console, logger, and dotenv bootstrap.

Split out of the original ``cli.py`` monolith per the
``2026-06-01-module-split-adr``. Every CLI submodule imports the
shared :data:`console` and :data:`logger` from here so the assembled
package exposes a single Rich console and a single
``vaultspec_rag.cli``-named logger (the latter matters because tests
filter ``caplog`` on that exact logger name).
"""

from __future__ import annotations

import logging
import sys

from rich.console import Console

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

# highlight=False disables Rich's automatic number/path styling (bold reprs).
# force_interactive=False disables Live/status spinner animation. Together they
# keep the CLI's output plain and deterministic: the operator text is parseable
# and nothing leaks ANSI styling or animated spinner frames into captured/piped
# output. This matters because CI sets FORCE_COLOR, which otherwise makes Rich
# treat captured output as an interactive terminal and emit styling/animation a
# scripted or test consumer cannot parse. Status messages still print once.
console = Console(legacy_windows=False, highlight=False, force_interactive=False)
