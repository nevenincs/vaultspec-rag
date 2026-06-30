"""Guard: torch loads only through the centralized ``_gpu.load_torch`` gate.

vaultspec-rag is GPU-only. Every local-mode compute path that needs torch must
obtain it through ``vaultspec_rag._gpu.load_torch`` - never a naked
module-scope ``import torch`` - so the import is controlled in one place and a
CPU-only build fails hard rather than degrading to CPU compute. These guards
lock that invariant:

* importing the local-mode modules must not pull torch into ``sys.modules``
  (the import is function-local, deferred to ``load_torch``);
* no compute module declares a module-scope ``import torch``; and
* ``load_torch`` honours its contract on the real interpreter (returns torch
  when a CUDA device is present, raises hard otherwise) - asserted without
  mocks against whatever torch state the host actually has.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[1]

pytestmark = [pytest.mark.unit]

# Local-mode modules that legitimately use torch - all must keep the import
# function-local so importing the module loads no torch.
_LOCAL_MODE_MODULES = (
    "vaultspec_rag.embeddings",
    "vaultspec_rag.service",
    "vaultspec_rag.search._searcher",
    "vaultspec_rag.api",
    "vaultspec_rag.store",
    "vaultspec_rag._gpu",
)

# Compute modules whose torch import must never sit at module scope.
_COMPUTE_MODULE_FILES = (
    _PKG_ROOT / "embeddings.py",
    _PKG_ROOT / "service.py",
    _PKG_ROOT / "search" / "_searcher.py",
    _PKG_ROOT / "_gpu.py",
)

_HEAVY_LIBS = ("torch", "sentence_transformers")


def test_importing_local_mode_modules_loads_no_torch() -> None:
    """A fresh interpreter importing the local-mode modules must not load torch.

    Run in a subprocess so session-wide ``sys.modules`` pollution from other
    tests cannot mask a naked import.
    """
    imports = "; ".join(f"import {m}" for m in _LOCAL_MODE_MODULES)
    code = (
        "import sys\n"
        f"{imports}\n"
        f"heavy = [m for m in {_HEAVY_LIBS!r} if m in sys.modules]\n"
        "assert not heavy, heavy\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_compute_modules_have_no_module_scope_torch_import() -> None:
    """No compute module may declare ``import torch`` at module scope."""
    for path in _COMPUTE_MODULE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # module-scope statements only, not nested
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                assert "torch" not in names, f"{path.name}: module-scope import torch"
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[
                0
            ] == "torch":
                msg = f"{path.name}: module-scope from torch import"
                raise AssertionError(msg)


def test_load_torch_contract_holds_for_the_real_interpreter() -> None:
    """``load_torch`` returns torch under CUDA, else fails hard - no mocks.

    Exercises whichever real state the host has: GPU torch returns the module;
    a CPU-only torch build raises ``RuntimeError``; absent torch raises
    ``ImportError``. Together across environments this covers both the success
    and the fail-hard branches of the single centralized gate.
    """
    from vaultspec_rag._gpu import load_torch

    if importlib.util.find_spec("torch") is None:
        with pytest.raises(ImportError):
            load_torch()
        return

    import torch

    if torch.cuda.is_available():
        assert load_torch() is torch
    else:
        with pytest.raises(RuntimeError):
            load_torch()
