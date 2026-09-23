"""Ask the interpreter that would run the service what it can do.

The service runs in whichever environment launches it, and the CLI must never
import torch itself, so the question is put to that interpreter in a child
process, which answers with :func:`environment_report`. Two depths:

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
from typing import cast

from ._compute import ProbeDepth
from ._installation import ComputeCapability, InstallRole
from ._models import ComputeReport

__all__ = ["InterpreterFacts", "probe_interpreter"]

#: Seconds allowed for each depth. A metadata read is an interpreter start and
#: a few file reads; a verify pays for importing torch and waking the driver.
METADATA_TIMEOUT_SECONDS = 15.0
VERIFY_TIMEOUT_SECONDS = 60.0

_PROBE_SCRIPT = """
import json, sys
from vaultspec_rag.operator_state._compute import ProbeDepth, environment_report
print(json.dumps(environment_report(ProbeDepth(sys.argv[1]))))
"""


@dataclass(frozen=True, slots=True)
class InterpreterFacts:
    """What one interpreter is and whether it can run inference."""

    interpreter: str
    role: InstallRole
    mcp_adapter: bool
    executable: str
    prefix: str
    compute: ComputeReport


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
            encoding="utf-8",
            errors="replace",
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
        decoded: object = json.loads(lines[-1]) if lines else None
        if not isinstance(decoded, dict):
            raise TypeError(type(decoded).__name__)
        report = cast("dict[str, object]", decoded)
        return InterpreterFacts(
            interpreter=interpreter,
            role=InstallRole(report["role"]),
            mcp_adapter=bool(report["mcp_adapter"]),
            executable=str(report["executable"]),
            prefix=str(report["prefix"]),
            compute=ComputeReport.model_validate(report["compute"]),
        )
    except (TypeError, KeyError, ValueError):
        stderr = proc.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else f"exit code {proc.returncode}"
        return _unanswered(interpreter, ComputeCapability.UNKNOWN, detail)


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
