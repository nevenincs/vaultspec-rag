"""Actionable GPU / torch remediation messages and the error handler."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import typer

from ..commands._tool_torch import tool_cuda_install_spec
from ._core import logger
from ._render import _plain

if TYPE_CHECKING:
    from pathlib import Path
    from typing import NoReturn

    from ..torch_config._constants import TorchDiagnosis

__all__ = [
    "RuntimeEnvKind",
    "_cpu_only_message",
    "_handle_gpu_error",
    "_no_gpu_message",
    "_no_torch_message",
    "classify_interpreter_env",
    "classify_runtime_env",
    "durable_tool_install_command",
    "gpu_escape_hatch_command",
    "warn_if_active_torch_not_accelerator",
]


class RuntimeEnvKind(StrEnum):
    """Classification of the environment a python prefix belongs to.

    Drives which torch remediation is offered: a ``uv tool`` env can only be
    repaired in place (the project-scoped cu130 pin never reaches it), a uvx
    ephemeral cache env is almost never the environment the operator thinks
    they are running, and a project venv is served by ``vaultspec-rag install``.
    """

    UV_TOOL = "uv-tool"
    UVX_EPHEMERAL = "uvx-ephemeral"
    PROJECT_VENV = "project-venv"
    OTHER = "other"

    @property
    def label(self) -> str:
        """Human-readable form used beside interpreter paths in messages."""
        return {
            RuntimeEnvKind.UV_TOOL: "uv tool install",
            RuntimeEnvKind.UVX_EPHEMERAL: (
                "uvx ephemeral cache env - NOT the installed tool"
            ),
            RuntimeEnvKind.PROJECT_VENV: "project venv",
            RuntimeEnvKind.OTHER: "unrecognized env",
        }[self]


def classify_runtime_env(prefix: str | Path | None = None) -> RuntimeEnvKind:
    """Classify the environment rooted at ``prefix`` (default: the running one).

    Pure path logic - never shells out to ``uv`` (this runs on the ``server
    start`` path). The uvx ephemeral cache is positively identified by the
    ``archive-v0`` component of the uv cache layout (or a ``UV_CACHE_DIR``
    ancestor); the installed-tool shape is the prefix sitting directly inside a
    ``tools`` directory (or a ``UV_TOOL_DIR`` ancestor); a ``.venv``/``venv``
    prefix is a project venv. Misclassification degrades only which remediation
    hint is printed, never correctness.
    """
    import os
    import sys
    from pathlib import Path

    resolved = Path(prefix if prefix is not None else sys.prefix).resolve()
    parts = {part.lower() for part in resolved.parts}
    cache_dir = os.environ.get("UV_CACHE_DIR", "")
    if "archive-v0" in parts or (
        cache_dir and resolved.is_relative_to(Path(cache_dir).resolve())
    ):
        return RuntimeEnvKind.UVX_EPHEMERAL
    tool_dir = os.environ.get("UV_TOOL_DIR", "")
    if tool_dir and resolved.is_relative_to(Path(tool_dir).resolve()):
        return RuntimeEnvKind.UV_TOOL
    if resolved.parent.name.lower() == "tools":
        return RuntimeEnvKind.UV_TOOL
    if resolved.name.lower() in {".venv", "venv"}:
        return RuntimeEnvKind.PROJECT_VENV
    return RuntimeEnvKind.OTHER


def classify_interpreter_env(interpreter: str | Path) -> RuntimeEnvKind:
    """Classify the environment that owns ``interpreter`` (a python binary).

    Walks up from the binary to its env root (the parent of ``Scripts``/
    ``bin``) and classifies that root, so the daemon interpreter resolved by
    the start pre-flight gets the same classification as a running prefix.
    """
    from pathlib import Path

    binary = Path(interpreter).resolve()
    if binary.parent.name.lower() in {"scripts", "bin"}:
        return classify_runtime_env(binary.parent.parent)
    return classify_runtime_env(binary.parent)


def gpu_escape_hatch_command(interpreter: str) -> str:
    """The in-place GPU-wheel repair for ``interpreter``.

    Works on any env kind but is undone by the next tool-env re-resolution
    (``--torch-backend`` is ``uv pip``-only); pair it with
    :func:`durable_tool_install_command` on tool envs.
    """
    from ..torch_config._index import CU130_INDEX_URL

    backend = CU130_INDEX_URL.rsplit("/", 1)[-1]
    return (
        f'uv pip install --python "{interpreter}" '
        f"--reinstall --torch-backend={backend} torch"
    )


def durable_tool_install_command() -> str:
    """The receipt-carrying tool reinstall that keeps CUDA across upgrades.

    uv records ``--with`` requirements (including a PEP 508 direct wheel URL)
    in the tool receipt and re-applies them on every ``uv tool upgrade``, so
    torch keeps resolving to the cu130 wheel. ``--index`` is NOT recorded by
    current uv (verified on 0.11.x: the receipt carried no index options and
    an upgrade re-resolved torch to the CPU wheel), so the direct URL is the
    only re-resolution-proof pin. Nothing may be running out of the target
    environment first: a forced reinstall fails mid-removal on the locked
    Scripts dir, and the holder is as often an MCP client session's server
    process as the service itself.

    A direct wheel URL has to name one interpreter and one ABI, so both tags
    are read off the running interpreter rather than written down. Hardcoding
    them hands a 3.13 wheel to whoever is running 3.14, and uv rejects the
    mismatch with a tag error that says nothing about why the command was wrong.

    The two tags are NOT interchangeable: a free-threaded build is
    ``cp314-cp314t``, and ``sys.version_info`` is ``(3, 14)`` for both the
    free-threaded and the GIL build, so deriving one tag and using it twice
    silently names the GIL wheel on a free-threaded host. ``packaging`` already
    resolves this from ``Py_GIL_DISABLED`` and is a direct dependency, so ask it
    instead of re-deriving the rule here. Its first tag is the most specific one
    for this interpreter.

    The manylinux level stays hand-picked - it must match what PyTorch
    actually publishes (``manylinux_2_28``), which is not necessarily the
    first platform tag ``packaging`` yields for the host - but the machine
    architecture is read from the host, since PyTorch publishes that level
    per architecture (``x86_64`` and ``aarch64``).

    The torch version tracks the distribution already installed in this env
    (the CPU wheel being replaced), with the local ``+cpu`` suffix stripped:
    the same release is guaranteed to exist in the cu130 flavour for an
    interpreter that resolved it, where a baked constant goes stale against
    an env that has not caught up with the workspace pin. The constant
    remains only as the fallback when no torch is present at all.

    The command must also carry ``--python``: ``uv tool install --force``
    rebuilds the tool env with uv's *default* python request, not the
    interpreter that printed this command, so on a host whose default is a
    different version (or a free-threaded build) the pinned wheel fails the
    resolve on a tag mismatch that never names the real cause. The request is
    parsed out of the same tag as the wheel filename so the two cannot
    diverge, and uv records ``python`` in the tool receipt, so upgrades keep
    resolving on the matching interpreter.
    """
    return tool_cuda_install_spec().command


def _cpu_only_message() -> str:
    """Return the CPU_ONLY remediation copy as plain text."""
    return (
        "Error: PyTorch was installed without CUDA support "
        "(CPU-only wheel). Your GPU is fine.\n\n"
        "  Install vaultspec-rag with its [gpu] extra, then run "
        "uv run vaultspec-rag install; it patches your pyproject.toml "
        "with the cu130 torch index and adds torch>=2.4 as a direct "
        "dependency when needed. After patching, rerun "
        "uv sync --reinstall-package torch.\n\n"
        "  If install has already run and you are still here, verify:\n"
        "    1. pyproject.toml has [[tool.uv.index]] "
        'name = "pytorch-cu130" and [tool.uv.sources] torch = ...\n'
        "    2. pyproject.toml requests vaultspec-rag[gpu] and has "
        "torch>=2.4 as a direct dependency in [project].dependencies "
        "or [dependency-groups].dev\n"
        "    3. uv.lock has a torch entry with source = "
        '{ registry = "https://download.pytorch.org/whl/cu130" } '
        "(not pypi.org/simple)\n"
        "    4. If the lockfile still points at PyPI, rerun "
        "uv lock --refresh-package torch && uv sync.\n\n"
        "  Or configure manually by adding this to your pyproject.toml:"
    )


def _no_torch_message() -> str:
    """Return the NO_TORCH remediation copy as plain text."""
    import sys

    if sys.platform == "darwin":
        return (
            "Error: PyTorch is not installed.\n\n"
            "  Install vaultspec-rag in this interpreter to provision the "
            "macOS torch build with Apple MPS support."
        )
    return (
        "Error: PyTorch is not installed.\n\n"
        '  uv add "vaultspec-rag[gpu]" && uv run vaultspec-rag install '
        "configures the cu130 torch index and installs the GPU build."
    )


def _no_gpu_message() -> str:
    """Return the NO_GPU remediation copy as plain text."""
    return (
        "Error: No CUDA GPU detected.\n"
        "  PyTorch is built with CUDA support, but no CUDA device "
        "is available.\n\n"
        "  Quick checks:\n"
        "    1. nvidia-smi - confirms the driver sees the GPU. "
        "If this fails, install/repair the NVIDIA driver.\n"
        '    2. python -c "import torch; print(torch.version.cuda)" '
        "- prints the CUDA version torch was built against. Your "
        "driver must support at least this CUDA major.\n"
        "    3. WSL/Docker users: confirm GPU passthrough is enabled "
        "(--gpus all for docker, GPU support enabled in WSL2). "
        "A GPU visible to the host is not automatically visible inside "
        "the container/VM."
    )


def _no_mps_message() -> str:
    """Return MPS remediation copy for a macOS host."""
    return (
        "Error: No Apple Metal accelerator detected.\n"
        "  PyTorch is installed, but MPS is unavailable. vaultspec-rag never "
        "runs inference on CPU.\n\n"
        "  Quick checks:\n"
        "    1. Confirm this is an Apple silicon Mac running macOS 12.3 or later.\n"
        '    2. python -c "import torch; print(torch.backends.mps.is_built(), '
        'torch.backends.mps.is_available())"\n'
        "    3. Reinstall the supported macOS torch wheel if MPS is not built in."
    )


def _active_torch_diagnosis() -> TorchDiagnosis:
    """Diagnose torch in the *running* interpreter - the installed wheel.

    Distinct from the install report's ``PyTorch configuration`` line, which
    reflects ``pyproject.toml`` text and says nothing about the wheel actually
    present in the interpreter that will run the service.
    """
    from ..torch_config._constants import TorchDiagnosis
    from ..torch_config._diagnose import diagnose_torch

    try:
        import torch
    except ImportError:
        return TorchDiagnosis.NO_TORCH
    try:
        return diagnose_torch(
            torch.version.cuda,
            torch.cuda.is_available(),
            torch.backends.mps.is_available(),
        )
    except Exception as exc:
        logger.debug("active torch diagnosis failed: %s", exc, exc_info=True)
        return TorchDiagnosis.NO_TORCH


def warn_if_active_torch_not_accelerator() -> None:
    """Warn when the running interpreter cannot use a supported accelerator.

    vaultspec-rag is GPU-only. A configured ``pyproject.toml`` does not
    guarantee a usable accelerator in the active interpreter - a ``uv tool`` / ``pip``
    install resolves torch from PyPI (CPU), since the cu130 source pin is
    project-scoped and is not part of the published wheel metadata. This probes
    the actual wheel and, when it is CPU-only, absent, or GPU-less, prints a
    prominent topology-aware warning so a configured-but-CPU install never
    passes silently.
    """
    import sys

    from ..torch_config._constants import TorchDiagnosis

    diag = _active_torch_diagnosis()
    if diag == TorchDiagnosis.WORKING:
        try:
            import torch

            from .._gpu import resolve_accelerator

            resolve_accelerator(torch)
        except RuntimeError as exc:
            _plain(f"\nWARNING: {exc}")
        return

    lines = [
        "",
        "WARNING: the active interpreter's torch has no supported accelerator.",
    ]
    if sys.platform == "darwin":
        lines += [
            "  MPS is unavailable. vaultspec-rag requires Apple silicon with a "
            "PyTorch build that supports Metal; CPU fallback is not accepted.",
            "  Check the active interpreter:",
            '    python -c "import torch; print(torch.backends.mps.is_built(), '
            'torch.backends.mps.is_available())"',
        ]
        _plain("\n".join(lines))
        return
    if diag == TorchDiagnosis.NO_TORCH:
        lines.append("  No torch is installed in the active interpreter.")
    elif diag == TorchDiagnosis.CPU_ONLY:
        lines.append(
            "  The installed torch is a CPU-only wheel. pyproject.toml may be "
            "configured for cu130, but the wheel actually present is CPU - "
            "vaultspec-rag is GPU-only and the service will not start."
        )
    else:  # NO_GPU
        lines.append(
            "  torch is a CUDA build but no supported accelerator is visible "
            "(driver or hardware). Run nvidia-smi to check CUDA visibility."
        )
        _plain("\n".join(lines))
        return

    kind = classify_runtime_env()
    if kind is RuntimeEnvKind.UV_TOOL:
        lines += [
            "",
            "  This vaultspec-rag is a `uv tool` install. The cu130 GPU pin is "
            "project-scoped and does not reach `uv tool` / `pip` installs "
            "(`--torch-backend` is `uv pip`-only), so every `uv tool upgrade` "
            "re-resolves torch to the CPU wheel.",
            "  Repair this environment now (undone by the next upgrade):",
            f"    {gpu_escape_hatch_command(sys.executable)}",
            "  Make upgrades keep the GPU wheel. Stop the service and close "
            "every editor or agent session running an MCP stdio transport "
            "first: a "
            "held file stops the forced reinstall after it has removed the "
            "old packages, leaving the environment unrunnable.",
            f"    {durable_tool_install_command()}",
        ]
    elif kind is RuntimeEnvKind.UVX_EPHEMERAL:
        lines += [
            "",
            "  This interpreter is a uvx EPHEMERAL cache environment "
            f"({sys.prefix}) - not the installed tool. uvx silently falls "
            "back to it when the installed tool env is broken or the request "
            "does not match it.",
            "  Reinstall the tool with nothing running out of its "
            "environment - the service, and every editor or agent session "
            "running an MCP stdio transport, both take the Scripts lock that "
            "stops a forced reinstall half-way:",
            f"    {durable_tool_install_command()}",
        ]
    else:
        lines += [
            "",
            "  Provision the cu130 GPU wheel in this environment:",
            "    vaultspec-rag install   (patches pyproject.toml with the cu130 index)",
            "    uv sync --reinstall-package torch",
        ]
    _plain("\n".join(lines))


def _handle_gpu_error(exc: Exception) -> NoReturn:
    """Print an actionable message for torch / CUDA failures and exit.

    Distinguishes three failure states so the remediation hint matches
    the actual problem:

    - torch not installed at all (``ImportError``)
    - torch installed without CUDA support - the CPU-only PyPI wheel
      (``torch.version.cuda is None``)
    - torch built with CUDA but no GPU visible - driver or hardware
      issue (``torch.version.cuda`` set, ``is_available()`` False)

    Args:
        exc: The caught exception (``ImportError`` or ``RuntimeError``).

    Raises:
        typer.Exit: Always exits with code 1.
    """
    from .._gpu import MPS_FALLBACK_MESSAGE
    from ..torch_config._constants import TorchDiagnosis
    from ..torch_config._diagnose import diagnose_torch
    from ..torch_config._mutate import manual_snippet

    diagnosis: TorchDiagnosis
    if isinstance(exc, ImportError):
        diagnosis = TorchDiagnosis.NO_TORCH
    else:
        try:
            import torch

            diagnosis = diagnose_torch(
                torch.version.cuda,
                torch.cuda.is_available(),
                torch.backends.mps.is_available(),
            )
        except Exception as _diag_exc:
            # Broad except: torch import succeeded but probing the
            # CUDA state failed in an unexpected way (driver
            # mismatch, opaque ABI error). Treat as "no torch" for
            # diagnosis purposes; debug-log so the swallow stays
            # observable.
            logger.debug(
                "torch accelerator diagnosis failed: %s",
                _diag_exc,
                exc_info=True,
            )
            diagnosis = TorchDiagnosis.NO_TORCH

    import sys

    if MPS_FALLBACK_MESSAGE in str(exc):
        _plain(f"Error: {MPS_FALLBACK_MESSAGE}")
    elif diagnosis == TorchDiagnosis.NO_TORCH:
        _plain(_no_torch_message())
    elif sys.platform == "darwin":
        _plain(_no_mps_message())
    elif diagnosis == TorchDiagnosis.CPU_ONLY:
        _plain(_cpu_only_message())
        _plain(manual_snippet())
    elif diagnosis == TorchDiagnosis.NO_GPU:
        _plain(_no_gpu_message())
    else:
        _plain(f"Error: {exc}")
    raise typer.Exit(code=1)
