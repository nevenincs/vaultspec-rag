"""The one judgement of whether an environment can run the service.

Every command that fetches the model files or the Qdrant server, and every
report that would name a command to fetch them, asks this judgement. Most of
the suite pins its two inputs - the installation role and the answer of the
interpreter that would run the daemon - because both are facts about the
machine. The first tests here pin nothing: they run the real judgement on this
machine's real environment, through a real child interpreter, and hold it to
what this process can read about the same environment by other means. They are
what stands between the pinned fixture and production.
"""

from __future__ import annotations

import sys
from importlib import metadata

import pytest

from ..operator_state import _environment_probe
from ..operator_state._compute import ProbeDepth, metadata_verdict
from ..operator_state._installation import ComputeCapability, InstallRole
from ..operator_state._service_environment import (
    ServiceEnvironment,
    judge_service_environment,
)
from .conftest import pin_daemon_capability, pin_install_role

pytestmark = [pytest.mark.unit]


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


class TestTheRealJudgementOfThisEnvironment:
    """Nothing pinned: the real role, a real child interpreter, real answers."""

    def test_the_metadata_judgement_matches_what_this_environment_holds(
        self,
    ) -> None:
        """The child's reading and this process's reading describe one place.

        The expected verdict is worked out here from the installed
        distributions, which is the input the child is supposed to be reading.
        A judgement that returned a constant, or probed some other
        interpreter, disagrees on at least one of the two lanes the suite
        runs in: the accelerator-free lane is a client, the GPU lane is not.
        """
        expected = metadata_verdict(
            _version("sentence-transformers"), _version("torch"), sys.platform
        )

        judged = judge_service_environment(sys.executable, ProbeDepth.METADATA)

        assert judged.interpreter == sys.executable
        assert judged.capability is expected
        assert judged.is_client is (_version("sentence-transformers") is None)
        assert judged.can_run_service is (not expected.blocks_start)

    def test_the_verify_judgement_is_the_one_a_start_would_act_on(self) -> None:
        """The default depth agrees with the probe a start has always made.

        The real child imports torch in this machine's real environment. The
        judgement may only refuse where that probe's own answer blocks a
        start, and may only accept where it does not.
        """
        facts = _environment_probe.probe_interpreter(sys.executable, ProbeDepth.VERIFY)

        judged = judge_service_environment(sys.executable)

        assert judged.capability is facts.compute.capability
        assert judged.can_run_service is (not facts.compute.capability.blocks_start)
        if judged.capability is ComputeCapability.READY:
            assert not judged.is_client


#: An interpreter that does not exist. Asking it anything answers that it is
#: missing, so a judgement that names it and comes back with any other
#: capability was reached without starting it.
_NO_INTERPRETER = "no-such-interpreter-for-the-service-environment-tests"


class TestHowTheJudgementIsReached:
    """The role is asked first and for free; a host is asked what it can do."""

    def test_asking_the_missing_interpreter_says_it_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The premise of the two tests that rely on not having asked it."""
        pin_install_role(monkeypatch, InstallRole.HOST)

        judged = judge_service_environment(_NO_INTERPRETER, ProbeDepth.METADATA)

        assert judged.capability is ComputeCapability.INTERPRETER_MISSING

    def test_a_client_is_judged_without_starting_an_interpreter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation check: with the role no longer asked first, the missing
        interpreter is started and the capability assertion fails with
        ``interpreter_missing``; restoring passes.
        """
        pin_install_role(monkeypatch, InstallRole.CLIENT)

        judged = judge_service_environment(_NO_INTERPRETER)

        assert judged.capability is ComputeCapability.NOT_APPLICABLE
        assert judged.is_client
        assert not judged.can_run_service

    def test_the_running_interpreter_is_judged_when_none_is_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_install_role(monkeypatch, InstallRole.CLIENT)

        assert judge_service_environment().interpreter == sys.executable

    @pytest.mark.parametrize(
        ("capability", "can_run"),
        [
            (ComputeCapability.READY, True),
            # A check that did not finish does not refuse, as on a start.
            (ComputeCapability.UNKNOWN, True),
            (ComputeCapability.BUILD_PRESENT, True),
            (ComputeCapability.TORCH_MISSING, False),
            (ComputeCapability.TORCH_IMPORT_FAILED, False),
            (ComputeCapability.CPU_ONLY_BUILD, False),
            (ComputeCapability.NO_DEVICE, False),
            (ComputeCapability.MPS_POLICY_REFUSED, False),
            (ComputeCapability.INTERPRETER_MISSING, False),
        ],
    )
    def test_a_host_is_judged_on_what_its_interpreter_can_do(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capability: ComputeCapability,
        can_run: bool,
    ) -> None:
        """Holding the inference library is not enough to be provisioned for.

        Mutation check: with the judgement reduced to the role alone, as the
        provisioning gate was, every refusing row answers that it can run the
        service and fails here; restoring passes.
        """
        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, capability)

        judged = judge_service_environment("daemon-python")

        assert judged == ServiceEnvironment("daemon-python", capability)
        assert judged.can_run_service is can_run
        assert not judged.is_client

    def test_an_answer_already_in_hand_is_not_asked_for_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation check: with the handed-over answer ignored, the missing
        interpreter is started and the capability assertion fails with
        ``interpreter_missing``; restoring passes.
        """
        pin_install_role(monkeypatch, InstallRole.HOST)

        judged = judge_service_environment(
            _NO_INTERPRETER, probed=ComputeCapability.CPU_ONLY_BUILD
        )

        assert judged.capability is ComputeCapability.CPU_ONLY_BUILD
        assert not judged.can_run_service

    def test_the_role_outranks_an_answer_already_in_hand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_install_role(monkeypatch, InstallRole.CLIENT)

        judged = judge_service_environment(
            _NO_INTERPRETER, probed=ComputeCapability.READY
        )

        assert judged.is_client

    def test_the_reason_carries_the_probes_own_diagnosis(self) -> None:
        judged = ServiceEnvironment(
            "python", ComputeCapability.TORCH_IMPORT_FAILED, "ImportError: DLL"
        )

        assert judged.reason == (
            f"{ComputeCapability.TORCH_IMPORT_FAILED.label} (ImportError: DLL)"
        )
