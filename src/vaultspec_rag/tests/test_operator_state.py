"""The operator state vocabulary: complete labels, honest blocking, no torch."""

from __future__ import annotations

import subprocess
import sys

import pytest

from vaultspec_rag.operator_state._installation import (
    ComputeCapability,
    HardwarePresence,
    InstallRole,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "member",
    [*InstallRole, *HardwarePresence, *ComputeCapability],
    ids=str,
)
def test_every_member_has_a_plain_label(
    member: InstallRole | HardwarePresence | ComputeCapability,
) -> None:
    assert member.label.strip()


@pytest.mark.parametrize("capability", list(ComputeCapability), ids=str)
def test_every_defect_tells_the_operator_what_to_do(
    capability: ComputeCapability,
) -> None:
    if capability.is_defect:
        assert capability.remediation


def test_only_verified_or_unverifiable_capabilities_allow_a_start() -> None:
    allowed = {c for c in ComputeCapability if not c.blocks_start}
    assert allowed == {
        ComputeCapability.READY,
        ComputeCapability.BUILD_PRESENT,
        ComputeCapability.UNKNOWN,
    }


def test_a_client_cannot_serve_but_is_not_broken() -> None:
    client = ComputeCapability.NOT_APPLICABLE
    assert client.blocks_start
    assert not client.is_defect


def test_an_unfinished_check_is_never_reported_as_a_failure() -> None:
    unknown = ComputeCapability.UNKNOWN
    assert not unknown.blocks_start
    assert not unknown.is_defect


def test_importing_the_state_vocabulary_never_loads_torch() -> None:
    """Every service-control path imports this package, and none may pay for torch.

    The child interpreter matters: this one may already hold torch from another
    test, which would make the assertion pass without proving anything.

    Mutation check: a module-scope ``import torch`` in ``_installation`` makes
    the child exit non-zero on this assertion; removing it passes.
    """
    probe = (
        "import sys\n"
        "import vaultspec_rag.operator_state._installation\n"
        "assert 'torch' not in sys.modules, 'the state vocabulary loaded torch'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
