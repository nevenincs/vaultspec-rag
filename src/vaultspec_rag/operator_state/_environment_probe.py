"""Ask the interpreter that would run the service what it can do.

The service runs in whichever environment launches it, and the CLI must never
import torch itself, so the question is put to that interpreter in a child
process. One script answers both depths:

- ``metadata`` reads installed distributions only. It is cheap enough for a
  default ``status`` and can tell a client, a missing torch and a CPU-only
  build apart, but never claims a device works.
- ``verify`` imports torch and resolves the accelerator. It is what a start
  preflight, ``--verbose`` and ``doctor`` need, and costs seconds.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

from ._installation import ComputeCapability, InstallRole
from ._models import ComputeReport

__all__ = ["InterpreterFacts", "ProbeDepth", "probe_interpreter"]

#: Seconds allowed for each depth. A metadata read is an interpreter start and
#: a few file reads; a verify pays for importing torch and waking the driver.
METADATA_TIMEOUT_SECONDS = 15.0
VERIFY_TIMEOUT_SECONDS = 60.0


class ProbeDepth(StrEnum):
    """How far the probe goes before it answers."""

    METADATA = "metadata"
    VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class InterpreterFacts:
    """What one interpreter is and whether it can run inference."""

    interpreter: str
    role: InstallRole
    mcp_adapter: bool
    executable: str
    prefix: str
    compute: ComputeReport


# The child reports through one JSON line so every outcome, including a torch
# that fails to import, is a named state rather than an exit code to decode.
# Without a local version tag, PyPI ships CPU-only torch for Windows and CUDA
# torch for Linux; macOS builds carry MPS.
_PROBE_SCRIPT = """
import json, sys
from importlib import metadata

def version(name):
    try:
        return metadata.version(name)
    except Exception:
        return None

report = {
    "executable": sys.executable,
    "prefix": sys.prefix,
    "inference_stack": version("sentence-transformers") is not None,
    "mcp_adapter": version("mcp") is not None,
    "torch_version": version("torch"),
}

def metadata_capability(torch_version):
    local = torch_version.partition("+")[2].lower()
    if local == "cpu":
        return "cpu_only_build"
    if local.startswith("cu"):
        return "build_present"
    if local:
        return "unknown"
    return "cpu_only_build" if sys.platform == "win32" else "build_present"

def verified_capability():
    try:
        import torch
    except Exception as exc:
        report["detail"] = f"{type(exc).__name__}: {exc}"
        return "torch_import_failed"
    cuda_build = torch.version.cuda
    mps = False
    try:
        mps = bool(torch.backends.mps.is_available())
        from vaultspec_rag._gpu import resolve_accelerator
        context = resolve_accelerator(torch)
    except Exception as exc:
        report["detail"] = str(exc)
        if mps:
            return "mps_policy_refused"
        return "no_device" if cuda_build else "cpu_only_build"
    report["backend"] = context.backend
    report["device_name"] = context.name
    if context.backend == "cuda":
        total = torch.cuda.get_device_properties(0).total_memory
        report["memory_mib"] = int(total // (1024 * 1024))
    return "ready"

if not report["inference_stack"]:
    capability = "not_applicable"
elif report["torch_version"] is None:
    capability = "torch_missing"
elif sys.argv[1] == "verify":
    capability = verified_capability()
else:
    capability = metadata_capability(report["torch_version"])
report["capability"] = capability
print(json.dumps(report))
"""


def probe_interpreter(
    interpreter: str,
    depth: ProbeDepth = ProbeDepth.METADATA,
    *,
    timeout: float | None = None,
) -> InterpreterFacts:
    """Return what *interpreter* is and whether it can run the service.

    Never raises for an environment problem: a missing interpreter, a probe
    that overruns its bound, or output that cannot be read each become a
    ``ComputeCapability`` member, so a caller always has a verdict to render.
    """
    bound = timeout or (
        VERIFY_TIMEOUT_SECONDS
        if depth is ProbeDepth.VERIFY
        else METADATA_TIMEOUT_SECONDS
    )
    try:
        proc = subprocess.run(
            [interpreter, "-c", _PROBE_SCRIPT, depth.value],
            capture_output=True,
            text=True,
            timeout=bound,
            check=False,
        )
    except FileNotFoundError:
        return _unanswered(interpreter, ComputeCapability.INTERPRETER_MISSING, "")
    except subprocess.TimeoutExpired:
        return _unanswered(
            interpreter,
            ComputeCapability.UNKNOWN,
            f"the check did not finish within {bound:.0f}s",
        )
    except OSError as exc:
        return _unanswered(interpreter, ComputeCapability.UNKNOWN, str(exc))
    return _parse(interpreter, proc)


def _parse(
    interpreter: str, proc: subprocess.CompletedProcess[str]
) -> InterpreterFacts:
    lines = proc.stdout.strip().splitlines()
    try:
        report = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, dict):
        stderr = proc.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else f"exit code {proc.returncode}"
        return _unanswered(interpreter, ComputeCapability.UNKNOWN, detail)
    fields = cast("dict[str, object]", report)
    capability = ComputeCapability(str(fields["capability"]))
    return InterpreterFacts(
        interpreter=interpreter,
        role=(
            InstallRole.HOST if fields.get("inference_stack") else InstallRole.CLIENT
        ),
        mcp_adapter=bool(fields.get("mcp_adapter")),
        executable=str(fields.get("executable") or interpreter),
        prefix=str(fields.get("prefix") or ""),
        compute=ComputeReport(
            capability=capability,
            torch_version=_text(fields.get("torch_version")),
            backend=cast("Literal['cuda', 'mps'] | None", fields.get("backend")),
            device_name=_text(fields.get("device_name")),
            memory_mib=_integer(fields.get("memory_mib")),
            detail=_text(fields.get("detail")),
        ),
    )


def _unanswered(
    interpreter: str, capability: ComputeCapability, detail: str
) -> InterpreterFacts:
    """Facts for an interpreter that could not describe itself.

    The role cannot be read either, so it is reported as a host: the caller
    asked because it meant to run the service there.
    """
    return InterpreterFacts(
        interpreter=interpreter,
        role=InstallRole.HOST,
        mcp_adapter=False,
        executable=interpreter,
        prefix="",
        compute=ComputeReport(capability=capability, detail=detail or None),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
