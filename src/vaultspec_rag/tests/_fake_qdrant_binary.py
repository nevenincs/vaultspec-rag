"""Stand a script in for the qdrant binary the supervisor executes.

The supervisor runs its binary with no arguments, so a test that needs the
child to behave a particular way - abort on a named collection, serve without
asking for a key - cannot hand it a script directly. This writes the script
beside a launcher the supervisor can execute as-is.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def fake_qdrant_binary(tmp_path: Path, source: str, name: str = "fake_qdrant") -> Path:
    """Write a fake qdrant 'binary' the supervisor can exec as ``[binary]``."""
    script = tmp_path / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / f"{name}.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}"\r\n', encoding="utf-8")
        return launcher
    launcher = tmp_path / f"{name}.sh"
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher
