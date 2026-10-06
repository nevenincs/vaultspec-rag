"""The committed Qdrant pin tables, read from their source file on their own.

One declared test seam writes a stand-in's digests into the live pin tables
for the length of a block. A seam like that is only safe if a leak is loud:
a table left holding a stand-in digest would make every later test in the
run trust the wrong bytes, and pass.

So the committed values are read here a second time, by executing the
constants module's source under another name. The copy shares nothing with
the live tables, which makes it a reference no write to them can move. The
check below compares the two and is run after every test.

Kept free of every other test helper, so the suite's root fixtures can import
it without importing what those helpers import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from ..qdrant_runtime import _constants as live

__all__ = ["COMMITTED_PINS", "pin_table_drift"]

_PRISTINE_NAME = f"{__name__}._pristine_constants"


def _read_committed() -> dict[str, dict[str, str]]:
    """Execute the constants source as a module of its own and copy its tables."""
    source = Path(live.__file__)
    spec = importlib.util.spec_from_file_location(_PRISTINE_NAME, source)
    assert spec is not None, source
    assert spec.loader is not None, source
    module = importlib.util.module_from_spec(spec)
    # Registered while it executes: a class defined in a module that cannot
    # be found by name is not something every decorator copes with.
    sys.modules[_PRISTINE_NAME] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[_PRISTINE_NAME]
    return {
        "QDRANT_ASSET_SHA256": dict(module.QDRANT_ASSET_SHA256),
        "QDRANT_EXECUTABLE_SHA256": dict(module.QDRANT_EXECUTABLE_SHA256),
    }


#: Each pin table by name, as the source file commits it.
COMMITTED_PINS = _read_committed()


def pin_table_drift() -> list[str]:
    """Say how the live pin tables differ from the committed ones, if they do.

    Returns:
        One line per entry that differs, is missing, or was added, naming
        the table and the asset. Empty when both tables are exactly the
        committed ones.
    """
    drift: list[str] = []
    for table, committed in COMMITTED_PINS.items():
        current: dict[str, str] = getattr(live, table)
        for asset in sorted(committed.keys() | current.keys()):
            was, now = committed.get(asset), current.get(asset)
            if was != now:
                drift.append(f"{table}[{asset!r}] is {now!r}, committed {was!r}")
    return drift
