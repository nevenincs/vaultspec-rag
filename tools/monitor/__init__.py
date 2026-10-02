"""Native frontend compilation and delivered-byte verification."""

import sys
from pathlib import Path

# Bare release interpreters still use the checked-out native artifact owner.
_SOURCE = str(Path(__file__).resolve().parents[2] / "src")
if _SOURCE not in sys.path:
    sys.path.insert(0, _SOURCE)
