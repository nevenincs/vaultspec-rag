"""Shared Rich console capability predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

__all__ = ["supports_live"]


def supports_live(console: Console) -> bool:
    """Return whether *console* can render a Rich live region."""
    return console.is_interactive and not console.is_dumb_terminal
