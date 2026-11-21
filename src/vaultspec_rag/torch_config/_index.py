"""The accelerated index this project pins torch against.

Deliberately dependency-free, and that is the whole reason it is its own
module. The lockfile derivation beside it is imported by the binary build,
which runs inside a manylinux container holding nothing but the standard
library - so anything it reaches must import nothing a wheel would install.
Keeping these names here lets that hold without a second copy of the URL
appearing in the build tooling.

The URL is a constant and must stay one. It is not an operator setting, and
no environment variable may stand in for it, because three comparisons depend
on its being the same in every process:

- it is written into a consumer's ``pyproject.toml``, and an entry under this
  index name is canonical only when its URL equals this one. That file is
  committed and shared, so a per-process value would make one operator's
  written block read as hand-edited to everyone else, and widening the test
  to accept either value would make a hand-edited URL read as canonical;
- the accelerated torch version is derived by matching the lockfile's recorded
  registry against it, and the lockfile records this URL;
- an installed tool's receipt is judged to carry the accelerated index by
  comparing against it.

An operator who needs a wheel mirror edits the index URL in their own
``pyproject.toml``. That block is then classified as customised and is never
rewritten.
"""

from __future__ import annotations

from typing import Final

__all__ = ["CUDA_BACKEND", "CUDA_INDEX_NAME", "CUDA_INDEX_URL"]

#: The PyTorch wheel backend, and the only place its CUDA version is written.
#: The index name and URL are derived from it, so moving to a newer CUDA build
#: is a one-line change here plus the matching ``pyproject.toml`` entry.
CUDA_BACKEND: Final[str] = "cu134"
CUDA_INDEX_NAME: Final[str] = f"pytorch-{CUDA_BACKEND}"
CUDA_INDEX_URL: Final[str] = f"https://download.pytorch.org/whl/{CUDA_BACKEND}"
