"""Hardware and credential probes that decide whether a lane can run.

Most of this repository's test lanes need real hardware: a CUDA device, Apple
silicon, a Hugging Face token for the gated ``naver/splade-v3`` weights, and a
manifest-verified Qdrant binary in the host image. The root ``conftest.py``
does not SKIP when those are missing - it calls ``pytest.exit(..., returncode=1)``
and aborts the run. That is correct for a lane selected deliberately, and it is
exactly why an aggregate cannot simply invoke every lane and hope: on a
laptop, ``test gpu`` does not report "no GPU", it reports a red build.

So the aggregate asks first. A lane whose gate is closed is reported as
SKIPPED, by name and with the reason, and counted. It never silently vanishes,
which is the failure mode this module exists to prevent: ``test all`` used to
run one lane out of four and print nothing at all about the other three.

The probe runs once, in the project environment, in a single child process -
``torch`` and ``huggingface_hub`` are imported there rather than here, so the
harness itself stays standard-library-only and a broken project environment
degrades into "gate closed" rather than a traceback out of ``just``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass

#: Internal marker returned in place of an exit code when a lane did not run
#: because its gate was closed. Negative so it can never collide with a real
#: process exit status, and never returned from ``main``: the entry point maps
#: it onto :data:`~dev.exit_codes.NOTHING_SELECTED` before exiting.
SKIPPED = -1

_PROBE_SOURCE = textwrap.dedent(
    """
    import json, os
    facts = {"cuda": False, "mps": False, "hf_token": False, "qdrant": False}
    try:
        import torch
        facts["cuda"] = bool(torch.cuda.is_available())
        backend = getattr(torch.backends, "mps", None)
        facts["mps"] = bool(backend is not None and backend.is_available())
    except Exception:
        pass
    if os.environ.get("HF_TOKEN"):
        facts["hf_token"] = True
    else:
        try:
            from huggingface_hub import get_token
            facts["hf_token"] = bool(get_token())
        except Exception:
            pass
    try:
        from vaultspec_rag.qdrant_runtime._constants import QDRANT_SERVER_VERSION
        from vaultspec_rag.qdrant_runtime._resolve import resolve_binary
        resolved = resolve_binary(QDRANT_SERVER_VERSION)
        facts["qdrant"] = bool(
            resolved is not None and resolved.source == "provisioned"
        )
    except Exception:
        pass
    print(json.dumps(facts))
    """
)

#: Set this to any non-empty value to admit the ``perf`` lane into ``test all``.
#: The lane's wall-clock latency and footprint assertions ARE its system under
#: test, so a machine doing anything else fails them for reasons unrelated to a
#: regression. It is opt-in rather than probed because "is this machine quiet"
#: is a claim only the operator can make.
PERF_ENV = "VAULTSPEC_RAG_PERF_LANE"

_FACTS: dict[str, bool] | None = None


def facts() -> dict[str, bool]:
    """Return the probed host capabilities, running the probe at most once.

    Returns:
        A mapping of capability name to availability. Every key is present and
        false when the probe cannot run at all.
    """
    global _FACTS
    if _FACTS is not None:
        return _FACTS
    blank = {"cuda": False, "mps": False, "hf_token": False, "qdrant": False}
    try:
        completed = subprocess.run(
            ["uv", "run", "--no-sync", "python", "-c", _PROBE_SOURCE],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(f"host capability probe could not run: {exc}", file=sys.stderr)
        _FACTS = blank
        return _FACTS
    if completed.returncode != 0:
        print(
            "host capability probe failed; treating every hardware gate as "
            f"closed:\n{completed.stderr.strip()}",
            file=sys.stderr,
        )
        _FACTS = blank
        return _FACTS
    try:
        probed = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        _FACTS = blank
        return _FACTS
    _FACTS = {key: bool(probed.get(key, False)) for key in blank}
    return _FACTS


@dataclass(frozen=True)
class Gate:
    """A precondition a lane needs before it is worth running at all.

    Args:
        reason: What is missing, printed on the SKIPPED line. Phrased as the
            absent thing, because that line is the only trace the lane leaves.
        probe: Returns true when the lane can run here.
    """

    reason: str
    probe: Callable[[], bool]

    def open(self) -> bool:
        """Return true when this lane's precondition is satisfied."""
        return self.probe()


CUDA_GATE = Gate(
    "no CUDA device, no Hugging Face token, or no manifest-verified Qdrant "
    "binary on this host (conftest aborts the tier rather than skipping)",
    lambda: facts()["cuda"] and facts()["hf_token"] and facts()["qdrant"],
)

MPS_GATE = Gate(
    "no Apple-silicon MPS backend on this host",
    lambda: facts()["mps"],
)

PERF_GATE = Gate(
    f"quiet-machine lane not opted into; set {PERF_ENV}=1 on an idle host",
    lambda: bool(os.environ.get(PERF_ENV)),
)
