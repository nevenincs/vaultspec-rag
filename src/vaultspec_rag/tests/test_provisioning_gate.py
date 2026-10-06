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
from ..operator_state._installation import ComputeCapability, InstallRole
from ._cli_helpers import app, runner
from ._model_cache_seed import STAND_IN_DENSE, STAND_IN_RERANKER, seed_model_cache
from .conftest import managed_env, pin_daemon_capability, pin_install_role

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


@pytest.mark.usefixtures("unready_host")
class TestAHostThatCannotRunTheServiceYet:
    """Every provisioning surface, from one environment that cannot serve."""

    def test_install_fetches_nothing_and_says_what_will(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """Both fetches are skipped, with the reason and the command that fetches.

        Mutation check: with the model and Qdrant steps gated on the role
        alone, as they were, the model step reaches the offline cache and
        fails, and the Qdrant step enters the provisioner and fails on the
        closed source; the skipped assertions fail on ``failed``. Restoring
        the judgement passes.
        """
        report = install_run(
            path=workspace, provision=True, configure_torch=False, assume_yes=True
        )

        outcome = _outcome(report)
        for step in (ProvisionStep.MODELS, ProvisionStep.QDRANT):
            result = _step(outcome, step)
            assert result.action == ProvisionAction.SKIPPED, result.detail
            assert _CANNOT_RUN in result.detail
            assert ComputeCapability.CPU_ONLY_BUILD.label in result.detail
            assert _START_FETCHES in result.detail
        assert outcome.ok, "a skip for an unready host must not read as a failure"
        assert not managed.exists(), _tree(managed.parent)
        assert _tree(empty_cache) == []

    def test_install_does_not_record_server_mode_as_chosen(
        self, workspace: Path, managed: Path, empty_cache: Path
    ) -> None:
        """No flag named a backend, and nothing was provisioned for one.

        Mutation check: with the choice saved for any host installation, as it
        was, the marker reads ``False`` and the first assertion fails;
        restoring passes.
        """
        del empty_cache
        report = install_run(
            path=workspace, provision=True, configure_torch=False, assume_yes=True
        )

        assert read_persisted_local_only() is None
        assert not managed.exists()
        backend = _outcome(report).backend
        assert backend is not None
        assert backend.saved is False
        assert backend.local_only is None
        assert _CANNOT_RUN in backend.detail
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

    def test_warmup_fetches_nothing_and_exits_cleanly(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: with the model step gated on the role alone, the
        fetch reaches the offline cache, the command exits 1, and the exit
        assertion fails; restoring passes.
        """
        result = runner.invoke(app, ["server", "warmup"])

        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert _CANNOT_RUN in output
        assert "`vaultspec-rag server start` fetches it" in output
        assert not managed.exists()
        assert _tree(empty_cache) == []

    def test_the_qdrant_install_verb_fetches_nothing(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: with the verb gated on the role alone, the
        provisioner is entered, fails on the closed source and leaves its lock
        file; the action assertion fails on ``failed``. Restoring passes.
        """
        del empty_cache
        result = runner.invoke(app, ["server", "qdrant", "install", "--json"])

        assert result.exit_code == 0, result.output
        payload = cast("dict[str, object]", json.loads(result.stdout))
        data = cast("dict[str, object]", payload["data"])
        assert payload["ok"] is True
        assert data["action"] == "skipped"
        assert _CANNOT_RUN in str(data["message"])
        assert not managed.exists(), _tree(managed.parent)

    def test_qdrant_status_does_not_send_it_to_install(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """Mutation check: with status no longer asking the judgement, the
        install command is named as the next action and the assertion on it
        fails; restoring passes.
        """
        del empty_cache
        human = runner.invoke(app, ["server", "qdrant", "status"])
        structured = runner.invoke(app, ["server", "qdrant", "status", "--json"])

        output = " ".join(human.output.split())
        assert human.exit_code == 0, human.output
        assert "Executable: not installed" in output
        assert "Not needed here:" in output
        assert _CANNOT_RUN in output
        assert "Next action" not in output
        assert "server qdrant install" not in output
        payload = cast("dict[str, object]", json.loads(structured.stdout))
        data = cast("dict[str, object]", payload["data"])
        assert _CANNOT_RUN in str(data["server_unneeded"])
        assert not managed.exists()

    def test_start_refuses_before_it_looks_at_the_port_or_the_machine(
        self, managed: Path, empty_cache: Path
    ) -> None:
        """The judgement comes ahead of every guard that can write.

        The start is aimed at a port something else holds, so a start that
        reached the port guard first fails for the port instead.

        Mutation check: with the judgement moved back after the port and
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
        assert payload["error"] == "service_env_no_gpu"
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
