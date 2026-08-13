"""Guard: torch loads only through the centralized ``_gpu.load_torch`` gate.

vaultspec-rag is GPU-only. Every local-mode compute path that needs torch must
obtain it through ``vaultspec_rag._gpu.load_torch`` - never a naked
module-scope ``import torch`` - so the import is controlled in one place and a
CPU-only build fails hard rather than degrading to CPU compute. These guards
lock that invariant:

* importing the local-mode modules must not pull torch into ``sys.modules``
  (the import is function-local, deferred to ``load_torch``);
* no compute module declares a module-scope ``import torch``;
* the entry points that resolve index policy without a model must not load
  torch when they run, not merely when they are imported; and
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

# Tiers are declared per test rather than for the module: the allocator-fraction
# test needs a real device, and a module-level default would be ADDED to its
# `cuda` mark rather than overridden by it, leaving it selected by the fast lane.

# Local-mode modules that legitimately use torch - all must keep the import
# function-local so importing the module loads no torch.
_LOCAL_MODE_MODULES = (
    "vaultspec_rag.embeddings",
    "vaultspec_rag.service",
    "vaultspec_rag.search._searcher",
    "vaultspec_rag.api",
    "vaultspec_rag.store_runtime",
    "vaultspec_rag._gpu",
    "vaultspec_rag._gpu_admission",
)

# Compute modules whose torch import must never sit at module scope.
_COMPUTE_MODULE_FILES = (
    _PKG_ROOT / "embeddings.py",
    _PKG_ROOT / "service.py",
    _PKG_ROOT / "search" / "_searcher.py",
    _PKG_ROOT / "_gpu.py",
    _PKG_ROOT / "_gpu_admission.py",
)

_HEAVY_LIBS = ("torch", "sentence_transformers")


@pytest.mark.unit
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


@pytest.mark.unit
def test_compute_modules_have_no_module_scope_torch_import() -> None:
    """No compute module may declare ``import torch`` at module scope."""
    for path in _COMPUTE_MODULE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # module-scope statements only, not nested
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                assert "torch" not in names, f"{path.name}: module-scope import torch"
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] == "torch"
            ):
                msg = f"{path.name}: module-scope from torch import"
                raise AssertionError(msg)


#: Source built inside a fresh interpreter by the preflight guard below. Every
#: production entry point that resolves index policy without a model appears
#: here; a new one must be added or it goes unguarded.
_PREFLIGHT_DRIVER = """
import pathlib, sys, tempfile

from vaultspec_rag import _job_admission, api
from vaultspec_rag._public_index import scan_documents
from vaultspec_rag.indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp).resolve()
    # The document domain admits only explicitly routed content, so without a
    # routing rule the document preflights below would walk nothing and the
    # guard would pass without having exercised them.
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        '\\nversion = 2\\n\\n[[rule]]\\npattern = "*.bin"\\n'
        'command = "extract {path}"\\ntarget = "document"\\n'
        'extractor_version = "1"\\n',
        encoding="utf-8",
    )
    (root / "routed.bin").write_bytes(b"routed")
    (root / "mod.py").write_text("def alpha():\\n    return 1\\n", encoding="utf-8")
    changed = [root / "routed.bin"]

    code = _job_admission.validate_code_index_policy(root)
    _job_admission.validate_scoped_code_index_policy(root, (root / "mod.py",))
    docs = _job_admission.validate_document_index_policy(root)
    _job_admission.validate_scoped_document_index_policy(root, tuple(changed))
    api._preflight_code_index(root)
    api._preflight_document_index(root)
    api._preflight_document_scope(root, changed)
    scanned = scan_documents(root)

    # A preflight that discovered nothing would prove nothing about the paths
    # a real model would have been loaded on.
    assert code.scan.files, "code preflight discovered no files"
    assert docs.files, "document preflight discovered no files"
    assert scanned.total_files, "document scan discovered no files"

heavy = [m for m in __HEAVY_LIBS__ if m in sys.modules]
assert not heavy, "preflight loaded " + repr(heavy)
"""


@pytest.mark.unit
def test_preflight_paths_load_no_model() -> None:
    """Resolving index policy must never load torch or a sentence transformer.

    Every one of these entry points builds its discovery without a model and
    without a store. That is the whole reason they are safe to call before a
    job takes the GPU or the writer lock, and it is invisible to a type
    checker: a site that started constructing a real model here would still
    type-check, still pass its own tests, and only show up as a job that now
    pays for a model load to answer a dry run.

    Run in a fresh interpreter so a model another test already loaded into
    this session's ``sys.modules`` cannot mask the regression.

    Shown to fail by adding a function-local ``import torch`` to the model-free
    construction path these entry points share: the driver then exits non-zero
    on its ``preflight loaded ['torch']`` assertion. The three emptiness
    assertions inside the driver are what stop a tree that discovered nothing
    from passing this guard without having exercised a single preflight.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _PREFLIGHT_DRIVER.replace("__HEAVY_LIBS__", repr(_HEAVY_LIBS)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.unit
def test_load_torch_contract_holds_for_the_real_interpreter() -> None:
    """``load_torch`` returns torch under CUDA, else fails hard - no mocks.

    Exercises whichever real state the host has: GPU torch returns the module;
    a CPU-only torch build raises ``RuntimeError``; absent torch raises
    ``ImportError``. Together across environments this covers both the success
    and the fail-hard branches of the single centralized gate.

    A CUDA device present but too contended to hold a model stack is the fourth
    real state, and the gate refuses it. Which of the two CUDA states this host
    is in cannot be decided before the call - a sibling consumer can fill the
    card in the interval, and refusing then is the gate working - so both are
    accepted here while everything else stays a failure: another exception type,
    a refusal that is not the contention one, or anything returned that is not
    the torch module.
    """
    from .._gpu import load_torch

    if importlib.util.find_spec("torch") is None:
        with pytest.raises(ImportError):
            load_torch()
        return

    import torch

    if not torch.cuda.is_available():
        with pytest.raises(RuntimeError):
            load_torch()
        return

    try:
        loaded = load_torch()
    except RuntimeError as exc:
        assert "too contended" in str(exc), exc
        return
    assert loaded is torch


@pytest.mark.cuda
def test_load_torch_applies_configured_process_allocator_fraction(
    clean_config: None,
) -> None:
    """The real centralized gate applies headroom before callers load models."""
    del clean_config
    from .._gpu import load_torch
    from ..config._settings import get_config

    configured = 0.73
    get_config({"index_cuda_allocator_fraction": configured})
    torch = load_torch()
    assert torch.cuda.get_per_process_memory_fraction() == pytest.approx(configured)
