"""Unit tests for install-time provisioning wiring and local-only persistence.

Exercises the real install orchestration (:func:`install_run`) over the
real backends with no mocks and no network: the qdrant step is dropped via
``local_only`` / ``provision_skip`` and the model step is opted out, so the
provisioning front door runs without touching the GPU or the network. The
local-only persistence is a real round-trip through the managed service
directory (isolated to ``tmp_path`` via ``VAULTSPEC_RAG_STATUS_DIR``), and
the config resolver's precedence is asserted against the real env / marker
/ default chain.

See the plan ``2026-06-13-server-first-default-plan`` (W02.P05) and the
ADRs ``2026-06-13-provisioning-setup-adr`` /
``2026-06-13-server-first-default-adr``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..commands import ProvisionAction, ProvisionStep, install_run
from ..config import (
    EnvVar,
    get_config,
    persist_local_only,
    read_persisted_local_only,
    reset_config,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    yield
    reset_config()


@pytest.fixture
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the managed service dir at a temp path for marker isolation."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    status = tmp_path / "managed"
    os.environ[EnvVar.STATUS_DIR.value] = str(status)
    reset_config()
    try:
        yield status
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


@pytest.fixture
def consumer_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "consumer"
    ws.mkdir()
    (ws / "pyproject.toml").write_text(PROJECT_ONLY, encoding="utf-8", newline="")
    return ws


@pytest.fixture
def _clear_local_only_env() -> Iterator[None]:
    """Ensure no ambient local-only env leaks into precedence assertions."""
    saved: dict[str, str | None] = {
        EnvVar.LOCAL_ONLY.value: os.environ.pop(EnvVar.LOCAL_ONLY.value, None),
        EnvVar.QDRANT_SERVER.value: os.environ.pop(EnvVar.QDRANT_SERVER.value, None),
    }
    reset_config()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestLocalOnlyPersistenceRoundTrip:
    def test_no_marker_reads_none(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        assert read_persisted_local_only() is None

    def test_persist_true_round_trips(self, isolated_status_dir: Path) -> None:
        path = persist_local_only(True)
        assert path.exists()
        assert path.parent == isolated_status_dir
        assert read_persisted_local_only() is True

    def test_persist_false_round_trips(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        persist_local_only(False)
        assert read_persisted_local_only() is False

    def test_persist_overwrites_prior_choice(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        persist_local_only(True)
        assert read_persisted_local_only() is True
        persist_local_only(False)
        assert read_persisted_local_only() is False

    def test_marker_is_well_formed_json(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        path = persist_local_only(True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == {"local_only": True}

    def test_malformed_marker_reads_as_absent(self, isolated_status_dir: Path) -> None:
        isolated_status_dir.mkdir(parents=True, exist_ok=True)
        (isolated_status_dir / "local-only.json").write_text(
            "not json at all", encoding="utf-8"
        )
        assert read_persisted_local_only() is None

    def test_marker_without_key_reads_as_absent(
        self, isolated_status_dir: Path
    ) -> None:
        isolated_status_dir.mkdir(parents=True, exist_ok=True)
        (isolated_status_dir / "local-only.json").write_text(
            json.dumps({"other": 1}), encoding="utf-8"
        )
        assert read_persisted_local_only() is None


class TestLocalOnlyResolutionPrecedence:
    """Precedence: explicit env/flag > persisted config > module default."""

    @pytest.mark.usefixtures("_clear_local_only_env")
    def test_default_wins_with_no_marker_and_no_env(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        cfg = get_config()
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is True

    @pytest.mark.usefixtures("_clear_local_only_env")
    def test_persisted_true_overrides_default(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        persist_local_only(True)
        reset_config()
        cfg = get_config()
        assert cfg.local_only is True
        assert cfg.effective_server_mode() is False

    @pytest.mark.usefixtures("_clear_local_only_env")
    def test_persisted_false_keeps_server_mode(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        persist_local_only(False)
        reset_config()
        cfg = get_config()
        assert cfg.local_only is False
        assert cfg.effective_server_mode() is True

    def test_env_overrides_persisted_marker(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        # Marker says local-only; the explicit env knob set falsey must win.
        persist_local_only(True)
        prev = os.environ.get(EnvVar.LOCAL_ONLY.value)
        os.environ[EnvVar.LOCAL_ONLY.value] = "0"
        reset_config()
        try:
            cfg = get_config()
            assert cfg.local_only is False
            assert cfg.effective_server_mode() is True
        finally:
            if prev is None:
                os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
            else:
                os.environ[EnvVar.LOCAL_ONLY.value] = prev
            reset_config()

    def test_env_true_overrides_persisted_false(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        persist_local_only(False)
        prev = os.environ.get(EnvVar.LOCAL_ONLY.value)
        os.environ[EnvVar.LOCAL_ONLY.value] = "1"
        reset_config()
        try:
            cfg = get_config()
            assert cfg.local_only is True
            assert cfg.effective_server_mode() is False
        finally:
            if prev is None:
                os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
            else:
                os.environ[EnvVar.LOCAL_ONLY.value] = prev
            reset_config()


class TestInstallProvisionWiring:
    def test_no_provision_leaves_outcome_none(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(path=consumer_workspace, provision=False, assume_yes=True)
        assert report.provision_outcome is None

    def test_local_only_install_skips_qdrant_and_persists(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        outcome = report.provision_outcome
        assert outcome is not None
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.SKIPPED
        assert "local-only" in qdrant.detail
        # The local backend selection is persisted for `server start`.
        assert read_persisted_local_only() is True

    def test_default_provision_persists_server_mode_selection(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        # Skip both network steps so the front door runs offline while the
        # persistence still records the deliberate server-mode selection.
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=False,
            provision_skip={"models", "qdrant"},
            assume_yes=True,
        )
        assert report.provision_outcome is not None
        assert read_persisted_local_only() is False

    def test_skip_tokens_opt_out_named_steps(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        outcome = report.provision_outcome
        assert outcome is not None
        models = outcome.result_for(ProvisionStep.MODELS)
        assert models is not None
        assert models.action == ProvisionAction.SKIPPED
        assert "opted out" in models.detail

    def test_torch_is_opted_out_of_the_front_door(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        # Enrollment configures torch directly; the front door must not
        # re-run it, so its torch result is an honest opted-out skip while
        # the report's own torch fields carry the real applied state.
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        outcome = report.provision_outcome
        assert outcome is not None
        torch = outcome.result_for(ProvisionStep.TORCH)
        assert torch is not None
        assert torch.action == ProvisionAction.SKIPPED
        assert report.torch_config_action == "applied"

    def test_dry_run_provision_previews_without_persisting(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=True,
            dry_run=True,
            assume_yes=True,
        )
        outcome = report.provision_outcome
        assert outcome is not None
        assert outcome.dry_run is True
        # A preview must never write runtime state.
        assert read_persisted_local_only() is None

    def test_report_to_dict_carries_provisioning(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(
            path=consumer_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        payload = report.to_dict()
        assert "provisioning" in payload
        provisioning = payload["provisioning"]
        assert isinstance(provisioning, dict)
        steps = provisioning["steps"]
        assert isinstance(steps, list)
        entries = cast("list[dict[str, object]]", steps)
        seen = {entry["step"] for entry in entries}
        assert seen == {"torch", "models", "qdrant"}

    def test_no_provision_to_dict_provisioning_is_none(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        report = install_run(path=consumer_workspace, provision=False, assume_yes=True)
        assert report.to_dict()["provisioning"] is None


class TestInstallCliFlags:
    """The CLI maps its per-dependency opt-out flags onto the skip tokens.

    Driven in ``--dry-run`` so the front door previews every step without
    touching the network, the GPU, or the persistence marker; the JSON
    envelope is the contract these assertions read.
    """

    def _provisioning(self, output: str) -> dict[str, object]:
        # ``install --json`` prints the report dict directly (not the
        # shared envelope), so ``provisioning`` is a top-level key.
        report = json.loads(output)
        provisioning = report["provisioning"]
        assert isinstance(provisioning, dict)
        return provisioning

    def _action_for(self, provisioning: dict[str, object], step: str) -> str:
        steps = provisioning["steps"]
        assert isinstance(steps, list)
        entries = cast("list[dict[str, object]]", steps)
        for entry in entries:
            if entry["step"] == step:
                return str(entry["action"])
        raise AssertionError(f"step {step} absent from provisioning outcome")

    def test_local_only_flag_skips_qdrant(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(consumer_workspace),
                "--local-only",
                "--dry-run",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        provisioning = self._provisioning(result.output)
        assert self._action_for(provisioning, "qdrant") == ProvisionAction.SKIPPED

    def test_skip_models_flag_maps_to_skip_token(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(consumer_workspace),
                "--skip-models",
                "--local-only",
                "--dry-run",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        provisioning = self._provisioning(result.output)
        assert self._action_for(provisioning, "models") == ProvisionAction.SKIPPED

    def test_skip_qdrant_flag_maps_to_skip_token(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(consumer_workspace),
                "--skip-qdrant",
                "--dry-run",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        provisioning = self._provisioning(result.output)
        assert self._action_for(provisioning, "qdrant") == ProvisionAction.SKIPPED

    def test_no_provision_flag_disables_front_door(
        self, consumer_workspace: Path, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(consumer_workspace),
                "--no-provision",
                "--dry-run",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        report = json.loads(result.output)
        assert report["provisioning"] is None
