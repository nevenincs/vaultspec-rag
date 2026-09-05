"""The accelerated index this project pins torch against.

Deliberately dependency-free, and that is the whole reason it is its own
module. The lockfile derivation beside it is imported by the binary build,
which runs inside a manylinux container holding nothing but the standard
library - so anything it reaches must import nothing a wheel would install.
Keeping these two names here lets that hold without a second copy of the URL
appearing in the build tooling.
"""

from __future__ import annotations

from typing import Final

__all__ = ["CU130_INDEX_NAME", "CU130_INDEX_URL"]

CU130_INDEX_NAME: Final[str] = "pytorch-cu130"
CU130_INDEX_URL: Final[str] = "https://download.pytorch.org/whl/cu130"
