"""Whether an environment can run the search service, judged in one place.

The model files and the Qdrant server are of use only to an environment that
can run the service, so every command that would fetch either asks this first,
and every report that would tell an operator to fetch either asks it before
naming a command. One judgement, because two disagree: when provisioning asked
only which distributions were installed and a start asked what the interpreter
could do, a project that merely depended on the inference library was sent
downloads by three commands and refused by the fourth.

The judgement is the one a start makes of the interpreter that will run the
daemon. The installation role is read in this process, which costs nothing. A
host is then asked what it can do in a child of that interpreter, so the
caller never imports torch.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from . import _compute, _environment_probe
from ._compute import ProbeDepth
from ._installation import ComputeCapability, InstallRole

__all__ = ["ServiceEnvironment", "judge_service_environment"]


@dataclass(frozen=True, slots=True)
class ServiceEnvironment:
    """What one interpreter's environment can do for the service.

    Attributes:
        interpreter: The interpreter that was judged.
        capability: Why it can or cannot run inference.
        detail: The probe's own diagnosis, when it had one.
    """

    interpreter: str
    capability: ComputeCapability
    detail: str | None = None

    @property
    def can_run_service(self) -> bool:
        """Whether a service started in this environment would be allowed.

        A check that did not finish does not refuse: a start proceeds on one
        and lets the daemon's own load be the backstop, so provisioning does
        too.
        """
        return not self.capability.blocks_start

    @property
    def is_client(self) -> bool:
        """Whether this is a client installation, which never runs the service."""
        return self.capability is ComputeCapability.NOT_APPLICABLE

    @property
    def reason(self) -> str:
        """The capability in words, with the probe's diagnosis when it has one."""
        return self.capability.label + (f" ({self.detail})" if self.detail else "")


def judge_service_environment(
    interpreter: str | None = None,
    depth: ProbeDepth = ProbeDepth.VERIFY,
    *,
    probed: ComputeCapability | None = None,
) -> ServiceEnvironment:
    """Judge whether the environment of *interpreter* can run the service.

    Both readings go through their modules rather than names bound at import,
    which is what lets a caller pin either one.

    Args:
        interpreter: The interpreter that would run the daemon. A command
            that spawns the daemon names the one it resolved; left out, the
            running interpreter is judged, which is the same environment.
        depth: How far the capability check goes. The verify depth imports
            torch in the child and is what a command about to fetch or start
            needs; the metadata depth reads installed versions only, and is
            for a report that must stay fast. The metadata depth never claims
            a working device and never refuses one it could not check.
        probed: The capability an earlier step of the same command already
            obtained from this interpreter at the verify depth. The probe
            costs seconds and two runs of it can disagree, so a command that
            holds an answer hands it over and none is started here.
    """
    judged = sys.executable if interpreter is None else interpreter
    if _compute.installed_role()[0] is not InstallRole.HOST:
        return ServiceEnvironment(judged, ComputeCapability.NOT_APPLICABLE)
    if probed is not None:
        return ServiceEnvironment(judged, probed)
    compute = _environment_probe.probe_interpreter(judged, depth).compute
    return ServiceEnvironment(judged, compute.capability, compute.detail)
