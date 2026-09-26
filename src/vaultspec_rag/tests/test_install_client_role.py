"""A client installation is never torch-configured or provisioned.

Without the ``gpu`` extra every search runs in the vaultspec-rag service, so
install must neither prompt for the cu130 torch index nor add a torch
dependency to the consumer's ``pyproject.toml``, and it downloads nothing the
host installation already provides. Real filesystem, real ``tomlkit``, real
install orchestration; the installation role is the one pinned input, so the
client path is exercised on a GPU workstation too.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..commands._install import install_run
from ..commands._provision import ProvisionStep
from ..config._paths import persist_local_only, read_persisted_local_only
from ..torch_config import _direct_dep, _mutate
from ..torch_config._constants import TorchConfigAction
from ._cli_helpers import app, runner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("client_installation")]

PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-client"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag[mcp]"]\n'
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def client_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "client"
    ws.mkdir()
    (ws / "pyproject.toml").write_text(PROJECT_ONLY, encoding="utf-8", newline="")
    return ws


def test_upgrade_never_asks_to_patch_the_torch_index(client_workspace: Path) -> None:
    """The reported defect: ``install --upgrade`` on a client prompted for torch.

    Mutation check: removing the client gate from the torch-config step asks
    the cu130 question here, failing the ``prompts`` assertion; restoring the
    gate passes.
    """
    pyproject = client_workspace / "pyproject.toml"
    before = _sha(pyproject)
    prompts: list[str] = []

    def record(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    install_run(path=client_workspace, confirm=record)
    report = install_run(path=client_workspace, upgrade=True, confirm=record)

    assert prompts == []
    assert report.action == "upgrade"
    assert report.torch_config_action is TorchConfigAction.NOT_APPLICABLE
    assert _sha(pyproject) == before


def test_already_patched_client_gains_no_torch_dependency(
    client_workspace: Path,
) -> None:
    """A cu130 block left by an earlier install must not pull torch in.

    Mutation check: without the client gate the canonical-state branch adds
    ``torch>=2.4`` to ``[project].dependencies``, failing the direct-dep
    assertion; restoring the gate passes.
    """
    pyproject = client_workspace / "pyproject.toml"
    _mutate.apply_patch(pyproject)
    before = _sha(pyproject)

    report = install_run(path=client_workspace, upgrade=True, assume_yes=True)

    assert _direct_dep.has_direct_torch_dep(pyproject) == (False, "")
    assert report.torch_direct_dep_action == "skipped"
    assert _sha(pyproject) == before


def test_sync_request_gives_a_client_no_torch_advice(client_workspace: Path) -> None:
    """``--sync`` only reinstalls torch, which a client does not have.

    Mutation check: dropping the client exemption from the ``--sync``
    advisory tells this client to run ``uv sync --reinstall-package torch``,
    failing the warnings assertion; restoring it passes.
    """
    report = install_run(path=client_workspace, assume_yes=True, sync_after=True)

    assert report.torch_sync_action == "skipped"
    assert not [w for w in report.warnings if "torch" in w.lower()]


def test_a_client_provisions_nothing_and_keeps_the_host_backend_choice(
    client_workspace: Path, isolated_status_dir: Path
) -> None:
    """A client downloads nothing and must not overwrite the host's backend.

    The local-only marker lives in the per-user status directory the host
    installation's ``server start`` reads, so a client persisting its own run's
    choice would silently switch the host's storage backend.

    Mutation check: removing the client branch from provisioning runs the front
    door and persists this run's ``local_only=True`` over the host's ``False``,
    failing the marker assertion; restoring the branch passes. ``local_only``
    and the models opt-out also keep that mutated run off the network.
    """
    _ = isolated_status_dir
    persist_local_only(False)

    report = install_run(
        path=client_workspace,
        provision=True,
        local_only=True,
        provision_skip={"models"},
        assume_yes=True,
    )

    assert read_persisted_local_only() is False
    outcome = report.provision_outcome
    assert outcome is not None
    assert {result.step for result in outcome.steps} == set(ProvisionStep)
    assert all(result.action == ProvisionAction.SKIPPED for result in outcome.steps)
    assert all("client installation" in result.detail for result in outcome.steps)


def test_a_client_is_not_asked_for_hugging_face_credentials(
    client_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client downloads no models, so a missing token is not its concern.

    The token is forced absent because the real one is machine state: the hub
    fixes its token file location when it is imported, so a test cannot
    redirect it in-process, and a developer's stored login would otherwise
    hide the warning in both directions.

    Mutation check: dropping the role from the credential warning's gate warns
    this client, failing the assertion; restoring it passes.
    """
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "get_token", lambda: None)

    report = install_run(path=client_workspace, assume_yes=True)

    assert not [w for w in report.warnings if "HuggingFace" in w]


def test_cli_upgrade_reports_torch_as_not_needed(client_workspace: Path) -> None:
    """A client upgrade succeeds and says torch is not needed, not skipped.

    Before the gate, the non-interactive runner left the patch unconfirmed
    and the command exited 2 asking for ``--yes``.
    """
    result = runner.invoke(
        app, ["install", "--target", str(client_workspace), "--upgrade"]
    )

    assert result.exit_code == 0, result.output
    assert (
        "PyTorch configuration: not needed (this installation is a client)"
        in result.output
    )
    assert "cu130" not in result.output
