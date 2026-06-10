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

console = Console(legacy_windows=False)
