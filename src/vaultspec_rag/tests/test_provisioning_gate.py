"""Nothing is fetched or written for an environment that cannot run the service.

Holding the inference library does not make an environment a host that can
serve. A project that depends on that library for its own purposes and adds
this package as a client holds it, and so does a real host between ``install``
writing its torch configuration and the sync that applies it. Both used to be
sent the model files and the Qdrant server by three commands and refused by
the fourth. Every surface is driven here from such an environment and must
fetch nothing, write nothing, say why, and never name a command that would
decline.

Two inputs are pinned, as everywhere in the suite: the installation role and
the answer of the interpreter that would run the daemon. Everything else is
real. The model cache is an empty directory the test owns with the hub's
offline switch set, and the Qdrant release source is a closed loopback port,
so a command that wrongly reached either fetch fails where it stands, in
seconds, without a request leaving the machine - and the Qdrant provisioner's
own lock file in the managed directory shows that it was entered.
"""

from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest

from .._sync_vocabulary import ProvisionAction
from ..commands._install import install_run
from ..commands._provision import (
    LOCAL_STORE_SELECTED,
    ProvisionOutcome,
    ProvisionStep,
    ProvisionStepResult,
)
from ..config._paths import persist_local_only, read_persisted_local_only
from ..config._types import EnvVar
from ..operator_state._installation import (
    ComputeCapability,
    HardwarePresence,
    InstallRole,
)
from ..service_runtime import ERROR_RUNTIME_UNSUPPORTED
from ._cli_helpers import app, runner
from ._model_cache_seed import STAND_IN_DENSE, STAND_IN_RERANKER, seed_model_cache
from .conftest import (
    managed_env,
    pin_daemon_capability,
    pin_hardware_presence,
    pin_install_role,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..commands._models import InstallReport

pytestmark = [pytest.mark.unit]

PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag[mcp]", "sentence-transformers"]\n'
)

#: A release source nothing listens on. A provisioner that is wrongly entered
#: is refused by this machine's own loopback and fails without a request
#: leaving it.
_NO_RELEASE_SOURCE = "https://127.0.0.1:9/qdrant/releases/download"

_CANNOT_RUN = "this environment cannot run the service yet"
_NO_SERVICE_HERE = "no service can run on this machine"
_START_FETCHES = "`vaultspec-rag server start` fetches it"


def _tree(root: Path) -> list[str]:
    """Every path under *root*, so a comparison names whatever appeared."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


@contextmanager
def _occupied_port() -> Generator[int]:
    """Hold a real listening socket and yield its port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield int(sock.getsockname()[1])


@pytest.fixture
def managed(tmp_path: Path) -> Generator[Path]:
    """Managed directories that do not exist yet, and no reachable release.

    Not created, unlike the shared fixtures: whether a command creates the
    managed directory is one of the things under test.
    """
    status = tmp_path / "managed" / "status"
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(status),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "managed" / "storage"),
            EnvVar.QDRANT_RELEASE_BASE_URL.value: _NO_RELEASE_SOURCE,
            EnvVar.LOCAL_ONLY.value: None,
            EnvVar.QDRANT_SERVER.value: None,
            EnvVar.QDRANT_URL.value: None,
            EnvVar.QDRANT_BINARY.value: None,
            EnvVar.QDRANT_BINARY_SHA256.value: None,
            EnvVar.HF_HUB_OFFLINE.value: "1",
        }
    ):
        yield status


@pytest.fixture
def empty_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A model cache in which every configured model is missing."""
    return seed_model_cache(
        monkeypatch,
        tmp_path / "hf-cache",
        missing=[STAND_IN_DENSE, STAND_IN_RERANKER],
    )


@pytest.fixture
def full_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A model cache that already holds every configured model."""
    return seed_model_cache(monkeypatch, tmp_path / "hf-cache")


@pytest.fixture
def machine_with_a_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine something can serve on, whatever this runner has."""
    pin_hardware_presence(monkeypatch, HardwarePresence.NVIDIA_GPU)


@pytest.fixture
def machine_without_an_accelerator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine nothing can serve on, whatever this runner has."""
    pin_hardware_presence(monkeypatch, HardwarePresence.NONE)


@pytest.fixture
def unready_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold the inference library with a torch that cannot use a GPU.

    The state of a project that depends on the library itself, and of a real
    host whose torch configuration is written and not yet synced.
    """
    pin_install_role(monkeypatch, InstallRole.HOST)
    pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    (root / "pyproject.toml").write_text(PROJECT_ONLY, encoding="utf-8", newline="")
    return root


def _outcome(report: InstallReport) -> ProvisionOutcome:
    assert report.provision_outcome is not None
    return report.provision_outcome


def _step(outcome: ProvisionOutcome, step: ProvisionStep) -> ProvisionStepResult:
    return next(result for result in outcome.steps if result.step == step)


@pytest.mark.usefixtures("unready_host", "machine_with_a_gpu")
class TestAHostThatCannotRunTheServiceItself:
    """Every provisioning surface, from one environment that cannot serve.

    The machine can: it has a supported accelerator, so a start runs the
    service from the managed runtime, and what that runtime will need is
    fetched here rather than withheld from it.
    """

    def test_install_provisions_for_the_runtime_that_will_serve(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """Both fetches are entered, because something here will serve.

        The environment's own torch cannot run the service, but the daemon
        does not run in it: a start runs the service from the managed runtime,
        and the model files and the Qdrant server that runtime needs are these
        ones. So neither step is skipped. Both are reached and both report
        their own failure here, which is what this fixture's empty offline
        cache and closed release source are for: a step that was skipped
        reports neither.

        Mutation check: gating the two steps on what this environment can do
        again answers both ``skipped`` and fails the first assertion.
        """
        report = install_run(
            path=workspace, provision=True, configure_torch=False, assume_yes=True
        )

        outcome = _outcome(report)
        for step in (ProvisionStep.MODELS, ProvisionStep.QDRANT):
            result = _step(outcome, step)
            assert result.action == ProvisionAction.FAILED, result.detail
            assert _CANNOT_RUN not in result.detail
            assert _NO_SERVICE_HERE not in result.detail
        assert not outcome.ok
        # The provisioner was entered, which is what left this behind.
        assert managed.exists()
        assert _tree(empty_cache) == []

    def test_install_does_not_record_server_mode_as_chosen(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """No flag named a backend, and nothing was provisioned for one.

        The reason is the run, not the environment: a launcher whose own torch
        cannot serve is served by the managed runtime, so what withholds the
        choice here is a provisioning run that did not finish - this
        fixture's offline cache and closed release source - and the sentence
        says that rather than naming the environment.

        Mutation check: with the choice saved for any host installation, as it
        was, the marker reads ``False`` and the first assertion fails;
        restoring passes.
        """
        del empty_cache
        report = install_run(
            path=workspace, provision=True, configure_torch=False, assume_yes=True
        )

        # The choice is what must not be written. The managed directory is a
        # different question, and the fetch this run now makes for the runtime
        # legitimately creates it; the machine that can serve nothing proves
        # the untouched-directory half.
        assert read_persisted_local_only() is None
        assert "local-only.json" not in _tree(managed)
        backend = _outcome(report).backend
        assert backend is not None
        assert backend.saved is False
        assert backend.local_only is None
        assert "provisioning did not finish" in backend.detail
        assert _CANNOT_RUN not in backend.detail
        assert "runs the managed Qdrant server" in backend.detail

    def test_install_keeps_an_explicit_local_only_choice(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """The operator named the backend; it is saved before the sync.

        The usual project flow is this command, a sync, then a plain start.
        A choice dropped here would have that start download a server the
        operator already declined.

        Mutation check: with an explicit choice held to the same condition as
        the implicit one, nothing is written and the marker assertion fails
        on ``None``; restoring passes.
        """
        del empty_cache
        report = install_run(
            path=workspace,
            provision=True,
            local_only=True,
            configure_torch=False,
            assume_yes=True,
        )

        assert read_persisted_local_only() is True
        assert _tree(managed) == ["local-only.json"]
        backend = _outcome(report).backend
        assert backend is not None
        assert backend.saved is True
        assert backend.local_only is True
        assert "runs no Qdrant server" in backend.detail
        assert LOCAL_STORE_SELECTED in backend.detail

    def test_warmup_fetches_for_the_runtime_too(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """The fetch is entered and fails on the offline cache, not skipped.

        Mutation check: gating the model step on what this environment can do
        again exits zero with nothing fetched, and the exit assertion fails.
        """
        del managed
        result = runner.invoke(app, ["server", "warmup"])

        output = " ".join(result.output.split())
        assert result.exit_code == 1, result.output
        assert "not in the local cache" in output
        assert _NO_SERVICE_HERE not in output
        assert _tree(empty_cache) == []

    def test_the_qdrant_install_verb_fetches_for_the_runtime_too(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Entered, and failing on the closed source rather than skipping.

        Mutation check: gating the verb on what this environment can do again
        answers ``skipped`` and exits zero, failing both assertions.
        """
        del empty_cache
        result = runner.invoke(app, ["server", "qdrant", "install", "--json"])

        assert result.exit_code == 1, result.output
        payload = cast("dict[str, object]", json.loads(result.stdout))
        assert payload["ok"] is False
        assert payload["error"] == "qdrant_provision_failed"
        assert managed.exists()

    def test_qdrant_status_names_the_install_it_now_needs(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """The server is needed here after all, so the next action says so.

        Mutation check: gating status on what this environment can do again
        prints "Not needed here" and no next action, failing both assertions.
        """
        del empty_cache
        del managed
        human = runner.invoke(app, ["server", "qdrant", "status"])

        output = " ".join(human.output.split())
        assert human.exit_code == 0, human.output
        assert "Next action: vaultspec-rag server qdrant install" in output
        assert "Not needed here:" not in output

    def test_start_refuses_before_it_looks_at_the_port_or_the_machine(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """The environment is resolved ahead of every guard that can write.

        A host whose torch cannot use the GPU no longer refuses the operator:
        the daemon would run from the managed runtime instead. This checkout
        is a working tree, which no requirement reproduces, so the runtime
        cannot be created and that is the refusal - and it still arrives
        before anything is written. The start is aimed at a port something
        else holds, so a start that reached the port guard first fails for the
        port instead.

        Mutation check: with the resolution moved back after the port and
        machine guards, the start fails as ``port_in_use`` and the error
        assertion fails; restoring passes.
        """
        del empty_cache
        with _occupied_port() as port:
            result = runner.invoke(
                app, ["server", "start", "--json", "--port", str(port)]
            )

        assert result.exit_code == 1, result.output
        payload = cast("dict[str, object]", json.loads(result.stdout))
        assert payload["error"] == ERROR_RUNTIME_UNSUPPORTED
        assert not managed.exists(), _tree(managed.parent)


@pytest.mark.usefixtures("unready_host", "machine_without_an_accelerator")
class TestAMachineThatCanRunNoServiceAtAll:
    """Nothing is fetched where no environment on the machine could serve.

    The managed runtime is no answer here: a runtime built on a machine with
    no supported accelerator could not run the service either. So the skip and
    its reason stay, and they name the machine rather than the environment.
    """

    def test_install_fetches_nothing_and_says_why(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: dropping the accelerator question answers both
        steps by entering them, which fails on the offline cache and the
        closed source; the skipped assertions then fail on ``failed``.
        """
        report = install_run(
            path=workspace, provision=True, configure_torch=False, assume_yes=True
        )

        outcome = _outcome(report)
        for step in (ProvisionStep.MODELS, ProvisionStep.QDRANT):
            result = _step(outcome, step)
            assert result.action == ProvisionAction.SKIPPED, result.detail
            assert _NO_SERVICE_HERE in result.detail
            assert HardwarePresence.NONE.label in result.detail
            assert _START_FETCHES in result.detail
        assert outcome.ok, "a skip for a machine with no GPU is not a failure"
        assert not managed.exists(), _tree(managed.parent)
        assert _tree(empty_cache) == []

    def test_warmup_fetches_nothing_and_exits_cleanly(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: dropping the accelerator question reaches the
        offline cache, exits 1, and fails the exit assertion.
        """
        result = runner.invoke(app, ["server", "warmup"])

        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert _NO_SERVICE_HERE in output
        assert not managed.exists()
        assert _tree(empty_cache) == []

    def test_the_qdrant_install_verb_fetches_nothing(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: dropping the accelerator question enters the
        provisioner, which fails on the closed source and leaves its lock
        file behind; the action assertion fails on ``failed``.
        """
        del empty_cache
        result = runner.invoke(app, ["server", "qdrant", "install", "--json"])

        assert result.exit_code == 0, result.output
        payload = cast("dict[str, object]", json.loads(result.stdout))
        data = cast("dict[str, object]", payload["data"])
        assert payload["ok"] is True
        assert data["action"] == "skipped"
        assert _NO_SERVICE_HERE in str(data["message"])
        assert not managed.exists(), _tree(managed.parent)


@pytest.mark.usefixtures("client_installation")
class TestAClientLeavesNoDirectoryBehind:
    """Looking for a running service must not create the place it would live."""

    def test_a_refused_start_creates_no_managed_directory(self, managed: Path) -> None:
        """Mutation check: with the status file's path creating its directory
        again, the managed directory exists after the refusal and the
        assertion fails; restoring passes.
        """
        result = runner.invoke(app, ["server", "start", "--json"])

        assert result.exit_code == 1, result.output
        assert not managed.exists(), _tree(managed.parent)

    def test_qdrant_status_tells_a_client_it_needs_nothing(self, managed: Path) -> None:
        result = runner.invoke(app, ["server", "qdrant", "status"])

        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert "Not needed here: not needed by a client installation" in output
        assert "Next action" not in output
        assert not managed.exists()

    def test_install_reports_that_a_client_saves_no_backend_choice(
        self, workspace: Path, managed: Path
    ) -> None:
        report = install_run(
            path=workspace, provision=True, local_only=True, assume_yes=True
        )

        assert read_persisted_local_only() is None
        assert not managed.exists()
        backend = _outcome(report).backend
        assert backend is not None
        assert backend.saved is False
        assert "client installation" in backend.detail


@pytest.mark.usefixtures("inference_host")
class TestAHostThatCanRunTheService:
    """The other direction: a host that can serve is provisioned and recorded."""

    def test_a_clean_run_records_server_mode(
        self, workspace: Path, managed: Path, full_cache: Path
    ) -> None:
        del full_cache
        report = install_run(
            path=workspace,
            provision=True,
            provision_skip={"qdrant"},
            configure_torch=False,
            assume_yes=True,
        )

        outcome = _outcome(report)
        assert outcome.ok
        assert _step(outcome, ProvisionStep.MODELS).action == ProvisionAction.UNCHANGED
        assert read_persisted_local_only() is False
        assert _tree(managed) == ["local-only.json"]
        backend = outcome.backend
        assert backend is not None
        assert backend.saved is True
        assert backend.local_only is False
        assert "runs the managed Qdrant server" in backend.detail

    def test_a_failed_run_does_not_record_server_mode(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """A run that could not provision has not chosen server mode.

        Mutation check: with the choice saved whether or not a step failed,
        as it was, the marker reads ``False`` and the assertion fails;
        restoring passes.
        """
        del empty_cache
        report = install_run(
            path=workspace,
            provision=True,
            provision_skip={"qdrant"},
            configure_torch=False,
            assume_yes=True,
        )

        outcome = _outcome(report)
        assert _step(outcome, ProvisionStep.MODELS).action == ProvisionAction.FAILED
        assert read_persisted_local_only() is None
        assert not managed.exists()
        backend = outcome.backend
        assert backend is not None
        assert backend.saved is False
        assert "provisioning did not finish" in backend.detail

    def test_a_failed_run_still_keeps_an_explicit_local_only_choice(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        del managed, empty_cache
        report = install_run(
            path=workspace,
            provision=True,
            local_only=True,
            configure_torch=False,
            assume_yes=True,
        )

        outcome = _outcome(report)
        assert _step(outcome, ProvisionStep.MODELS).action == ProvisionAction.FAILED
        assert read_persisted_local_only() is True
        assert outcome.backend is not None
        assert outcome.backend.saved is True

    def test_a_preview_saves_nothing(
        self, workspace: Path, managed: Path, full_cache: Path
    ) -> None:
        del full_cache
        report = install_run(
            path=workspace, provision=True, local_only=True, dry_run=True
        )

        assert read_persisted_local_only() is None
        assert not managed.exists()
        backend = _outcome(report).backend
        assert backend is not None
        assert backend.saved is False
        assert "preview" in backend.detail

    @pytest.mark.parametrize(
        ("exported", "reason"),
        [
            ({EnvVar.LOCAL_ONLY.value: "1"}, LOCAL_STORE_SELECTED),
            ({EnvVar.QDRANT_SERVER.value: "0"}, LOCAL_STORE_SELECTED),
            (
                {EnvVar.QDRANT_URL.value: "http://qdrant.invalid:6333"},
                EnvVar.QDRANT_URL.value,
            ),
        ],
        ids=["local-only", "server-mode-off", "remote-address"],
    )
    def test_install_fetches_no_server_the_exported_settings_rule_out(
        self,
        workspace: Path,
        managed: Path,
        full_cache: Path,
        exported: dict[str, str],
        reason: str,
    ) -> None:
        """An install with no backend flag follows the exported settings.

        Mutation check: with the Qdrant step decided by the flag alone, as it
        was, the provisioner is entered, fails on the closed source, and the
        action assertion fails on ``failed``; restoring passes.
        """
        del full_cache
        with managed_env(**exported):
            report = install_run(
                path=workspace, provision=True, configure_torch=False, assume_yes=True
            )

        qdrant = _step(_outcome(report), ProvisionStep.QDRANT)
        assert qdrant.action == ProvisionAction.SKIPPED, qdrant.detail
        assert reason in qdrant.detail
        assert "bin" not in _tree(managed)

    def test_install_does_not_read_back_the_choice_it_is_about_to_write(
        self, workspace: Path, managed: Path, full_cache: Path
    ) -> None:
        """A saved local-only choice does not stop an install choosing again.

        An install with no flag is how an operator returns to the managed
        server. If it honoured the choice an earlier install saved, nothing
        but deleting the file by hand could undo ``install --local-only``.
        Previewed, so the step's intent is read without a download.

        Mutation check: with the saved choice consulted like any other
        setting, the step is skipped for the on-disk store and the action
        assertion fails on ``skipped``; restoring passes.
        """
        del full_cache
        managed.mkdir(parents=True)
        persist_local_only(True)

        report = install_run(path=workspace, provision=True, dry_run=True)

        qdrant = _step(_outcome(report), ProvisionStep.QDRANT)
        assert qdrant.action == ProvisionAction.DRY_RUN, qdrant.detail
        assert read_persisted_local_only() is True

    def test_qdrant_status_names_the_install_command_when_one_is_needed(
        self, managed: Path
    ) -> None:
        """The other direction of the status gate: a real need is still named."""
        del managed
        result = runner.invoke(app, ["server", "qdrant", "status"])

        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert "Next action: vaultspec-rag server qdrant install" in output
        assert "Not needed here" not in output

    def test_qdrant_status_says_the_on_disk_store_needs_no_server(
        self, managed: Path
    ) -> None:
        del managed
        with managed_env(**{EnvVar.LOCAL_ONLY.value: "1"}):
            result = runner.invoke(app, ["server", "qdrant", "status"])

        output = " ".join(result.output.split())
        assert f"Not needed here: {LOCAL_STORE_SELECTED}" in output
        assert "Next action" not in output
