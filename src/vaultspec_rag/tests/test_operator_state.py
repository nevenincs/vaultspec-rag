"""The operator state vocabulary: complete labels, honest blocking, no torch."""

from __future__ import annotations

import subprocess
import sys

import pytest

from vaultspec_rag.operator_state._features import PreprocessHookState, TypesafeState
from vaultspec_rag.operator_state._installation import (
    ComputeCapability,
    HardwarePresence,
    InstallRole,
)
from vaultspec_rag.operator_state._service import (
    DegradationReason,
    HealthVerdict,
    ServiceLifecycle,
)

Labelled = (
    InstallRole
    | HardwarePresence
    | ComputeCapability
    | ServiceLifecycle
    | HealthVerdict
    | DegradationReason
    | TypesafeState
    | PreprocessHookState
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "member",
    [
        *InstallRole,
        *HardwarePresence,
        *ComputeCapability,
        *ServiceLifecycle,
        *HealthVerdict,
        *DegradationReason,
        *TypesafeState,
        *PreprocessHookState,
    ],
    ids=lambda member: f"{type(member).__name__}.{member.name}",
)
def test_every_member_has_a_plain_label(member: Labelled) -> None:
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


def test_lifecycle_keeps_the_broker_exit_contract() -> None:
    """Supervisors key on 0 running, 3 stopped, 4 fault and 5 starting."""
    codes = {member: member.exit_code for member in ServiceLifecycle}
    assert codes.pop(ServiceLifecycle.RUNNING) == 0
    assert codes.pop(ServiceLifecycle.STOPPED) == 3
    assert codes.pop(ServiceLifecycle.STARTING) == 5
    assert set(codes.values()) == {4}


@pytest.mark.parametrize("lifecycle", list(ServiceLifecycle), ids=str)
def test_every_down_lifecycle_tells_the_operator_what_to_do(
    lifecycle: ServiceLifecycle,
) -> None:
    assert (lifecycle.remediation is None) is lifecycle.is_live


def test_a_paused_service_is_neither_serving_nor_broken() -> None:
    serving = {verdict for verdict in HealthVerdict if verdict.is_serving}
    assert serving == {HealthVerdict.READY, HealthVerdict.DEGRADED}


@pytest.mark.parametrize("hooks", list(PreprocessHookState), ids=str)
def test_hooks_that_do_not_run_as_configured_say_why(
    hooks: PreprocessHookState,
) -> None:
    needs_action = hooks in {
        PreprocessHookState.DISABLED,
        PreprocessHookState.INVALID_CONFIG,
    }
    assert bool(hooks.remediation) is needs_action


def test_typesafe_is_enabled_by_any_key_state_but_off() -> None:
    enabled = {state for state in TypesafeState if state.is_enabled}
    assert enabled == set(TypesafeState) - {TypesafeState.OFF}


def test_importing_the_state_vocabulary_never_loads_torch() -> None:
    """Every service-control path imports this package, and none may pay for torch.

    The child interpreter matters: this one may already hold torch from another
    test, which would make the assertion pass without proving anything.

    Mutation check: a module-scope ``import torch`` in any of the three modules
    makes the child exit non-zero on this assertion; removing it passes.
    """
    probe = (
        "import sys\n"
        "import vaultspec_rag.operator_state._features\n"
        "import vaultspec_rag.operator_state._installation\n"
        "import vaultspec_rag.operator_state._service\n"
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
