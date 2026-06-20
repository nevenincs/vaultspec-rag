"""Unit tests for the unified provisioning front door.

Exercises real orchestration over the real backends with no mocks and
no network: the qdrant step runs against a temp-isolated managed dir
pre-seeded exactly as a verified provision leaves it (proving the
``unchanged`` idempotent no-op without downloading), the torch step
patches a real temp ``pyproject.toml`` via the real ``torch_config``
backend, and the model step exercises the skip / dry-run / opt-out
paths plus the real Hugging Face cache probe. The verify-before-execute
security contract of the qdrant provisioner is never weakened to make a
test pass - the idempotency path is proven by pre-seeding, the way
``test_qdrant_runtime`` does.

See the plan ``2026-06-13-server-first-default-plan`` (W02.P04) and the
ADR ``2026-06-13-provisioning-setup-adr``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from ..commands import (
    ProvisionAction,
    ProvisionOutcome,
    ProvisionStep,
    ProvisionStepResult,
    provision_dependencies,
    provision_models,
)
from ..config import EnvVar, reset_config
from ..qdrant_runtime import (
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
    asset_for_platform,
    binary_filename,
    file_sha256,
    qdrant_bin_dir,
)
from ..torch_config import TorchConfigState, detect_state

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
    """Point the managed service dir (and thus the qdrant bin dir) at tmp."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
    reset_config()
    try:
        yield tmp_path
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


def test_operator_symlink_binary_is_refused(
    isolated_status_dir: Path,  # noqa: ARG001  # managed-dir isolation
    tmp_path: Path,
) -> None:
    # H5 (security): an operator-supplied binary path that is a symlink must be
    # refused, never followed - copying it would dereference the link and could
    # register attacker content (TOCTOU) under an operator-blessed manifest.
    from ..qdrant_runtime import QdrantProvisionAction, provision

    real = tmp_path / "real_qdrant"
    real.write_bytes(b"#!/bin/sh\necho real\n")
    link = tmp_path / "link_qdrant"
    try:
        os.symlink(real, link)
    except OSError:
        pytest.fail("Cannot create symlink - test requires symlink support")

    report = provision(binary=link)
    assert report.action == QdrantProvisionAction.FAILED
    assert "symlink" in report.message.lower()
    # Nothing was registered into the managed dir.
    assert not (qdrant_bin_dir() / binary_filename()).exists()


def test_has_provisioned_binary_reflects_managed_install(
    isolated_status_dir: Path,  # noqa: ARG001  # managed-dir isolation
) -> None:
    # H3/H4 helper: drives the "unverified env/PATH binary shadows a verified
    # install" warning. False with no managed install, True once one is seeded.
    from ..qdrant_runtime._resolve import has_provisioned_binary

    assert has_provisioned_binary() is False
    _seed_verified_install()
    assert has_provisioned_binary() is True


def test_clean_provisioned_skips_symlinked_version_dir(
    isolated_status_dir: Path,  # noqa: ARG001  # managed-dir isolation
    tmp_path: Path,
) -> None:
    # M2 (security): a symlink/junction among the version dirs must be skipped,
    # never recursed - rmtree through a reparse point would delete the target's
    # contents (out-of-scope data loss on Windows).
    from ..qdrant_runtime._provision import clean_provisioned

    base = qdrant_bin_dir().parent
    base.mkdir(parents=True, exist_ok=True)
    real = base / "0.0.1"
    real.mkdir()
    (real / "marker").write_text("x", encoding="utf-8")

    external = tmp_path / "external_precious"
    external.mkdir()
    (external / "precious").write_text("keep me", encoding="utf-8")
    link = base / "9.9.9"
    try:
        os.symlink(external, link, target_is_directory=True)
    except OSError:
        pytest.fail("Cannot create symlink - test requires symlink support")

    removed = clean_provisioned()
    assert "0.0.1" in removed
    assert not real.exists()
    assert "9.9.9" not in removed  # the symlink was skipped, not recursed
    assert (external / "precious").exists()  # target contents untouched


def test_child_env_excludes_secrets_keeps_essentials() -> None:
    # M6 (security): the qdrant child env passes only OS-operation + QDRANT__*
    # vars, never the daemon's secrets.
    from pathlib import Path as _Path

    from ..qdrant_runtime._supervise import QdrantSupervisor

    prev = os.environ.get("MY_FAKE_SECRET_TOKEN")
    os.environ["MY_FAKE_SECRET_TOKEN"] = "do-not-leak"
    try:
        sup = QdrantSupervisor(
            _Path("qdrant"), http_port=6333, storage_dir=_Path("storage")
        )
        env = sup._child_env()
        assert "MY_FAKE_SECRET_TOKEN" not in env
        assert env["QDRANT__SERVICE__HOST"] == "127.0.0.1"
        assert env["QDRANT__SERVICE__HTTP_PORT"] == "6333"
        # PATH is an OS-operation var and must survive the curation.
        if "PATH" in os.environ:
            assert "PATH" in env
    finally:
        if prev is None:
            os.environ.pop("MY_FAKE_SECRET_TOKEN", None)
        else:
            os.environ["MY_FAKE_SECRET_TOKEN"] = prev


def _seed_verified_install() -> Path:
    """Pre-seed the managed dir exactly as a verified provision leaves it.

    Mirrors ``test_qdrant_runtime._seed_verified_install`` so the front
    door's qdrant step reports ``unchanged`` with zero network I/O.
    """
    version_dir = qdrant_bin_dir()
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(b"preseeded-binary")
    asset = asset_for_platform()
    manifest = {
        "version": QDRANT_SERVER_VERSION,
        "asset": asset,
        "asset_sha256": QDRANT_ASSET_SHA256[asset],
        "binary_sha256": file_sha256(binary),
        "source": "download",
        "provisioned_at": "2026-06-12T00:00:00+00:00",
    }
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return binary


class TestOutcomeModel:
    def test_status_aggregates_to_mixed_when_steps_disagree(self) -> None:
        outcome = ProvisionOutcome(
            steps=[
                ProvisionStepResult(ProvisionStep.TORCH, ProvisionAction.CREATED),
                ProvisionStepResult(ProvisionStep.MODELS, ProvisionAction.UNCHANGED),
            ]
        )
        assert outcome.status == "mixed"
        assert outcome.ok is True

    def test_status_is_the_common_action_when_steps_agree(self) -> None:
        outcome = ProvisionOutcome(
            steps=[
                ProvisionStepResult(ProvisionStep.TORCH, ProvisionAction.UNCHANGED),
                ProvisionStepResult(ProvisionStep.MODELS, ProvisionAction.UNCHANGED),
            ]
        )
        assert outcome.status == "unchanged"

    def test_status_is_failed_when_any_step_failed(self) -> None:
        outcome = ProvisionOutcome(
            steps=[
                ProvisionStepResult(ProvisionStep.TORCH, ProvisionAction.CREATED),
                ProvisionStepResult(
                    ProvisionStep.QDRANT, ProvisionAction.FAILED, "boom"
                ),
            ]
        )
        assert outcome.status == "failed"
        assert outcome.ok is False

    def test_result_for_finds_the_matching_step(self) -> None:
        result = ProvisionStepResult(ProvisionStep.MODELS, ProvisionAction.UNCHANGED)
        outcome = ProvisionOutcome(steps=[result])
        assert outcome.result_for(ProvisionStep.MODELS) is result
        assert outcome.result_for(ProvisionStep.QDRANT) is None

    def test_to_dict_is_json_serialisable_and_honest(self) -> None:
        outcome = ProvisionOutcome(
            steps=[
                ProvisionStepResult(
                    ProvisionStep.TORCH,
                    ProvisionAction.CREATED,
                    "configured; sync pending",
                    sync_pending=True,
                ),
            ],
            dry_run=False,
        )
        data = outcome.to_dict()
        json.dumps(data)  # must not raise
        assert data["status"] == "created"
        assert data["dry_run"] is False
        step = outcome.steps[0].to_dict()
        assert step["step"] == "torch"
        assert step["action"] == "created"
        assert step["sync_pending"] is True


class TestModelStep:
    def test_skip_set_opts_out_with_reason(self) -> None:
        result = provision_models(skip={"models"})
        assert result.action == ProvisionAction.SKIPPED
        assert result.detail
        assert result.step == ProvisionStep.MODELS

    def test_cached_models_report_unchanged_with_no_download(self) -> None:
        # The model step never downloads under dry-run: a host with the
        # configured repos already cached reports ``unchanged``; a host
        # without them reports ``dry_run`` (the would-download preview).
        # Either way no network is touched, so the assertion holds on a
        # warm dev host and a cold CI runner alike (hermetic, no auth).
        result = provision_models(dry_run=True)
        assert result.action in {
            ProvisionAction.UNCHANGED,
            ProvisionAction.DRY_RUN,
            ProvisionAction.SKIPPED,
        }
        if result.action == ProvisionAction.UNCHANGED:
            assert "cached" in result.detail


class TestTorchStep:
    def test_front_door_configures_torch_with_sync_pending(
        self, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            local_only=True,  # skip qdrant download
            skip={"models"},  # skip the model fetch
            assume_yes=True,
        )
        torch = outcome.result_for(ProvisionStep.TORCH)
        assert torch is not None
        assert torch.action == ProvisionAction.CREATED
        assert torch.sync_pending is True
        assert "sync pending" in torch.detail
        # The real backend actually patched the pyproject.
        assert (
            detect_state(consumer_workspace / "pyproject.toml")
            == TorchConfigState.CANONICAL
        )

    def test_front_door_is_idempotent_on_second_torch_run(
        self, consumer_workspace: Path
    ) -> None:
        first = provision_dependencies(
            consumer_workspace, local_only=True, skip={"models"}, assume_yes=True
        )
        first_torch = first.result_for(ProvisionStep.TORCH)
        assert first_torch is not None
        assert first_torch.action == ProvisionAction.CREATED

        second = provision_dependencies(
            consumer_workspace, local_only=True, skip={"models"}, assume_yes=True
        )
        torch = second.result_for(ProvisionStep.TORCH)
        assert torch is not None
        assert torch.action == ProvisionAction.UNCHANGED

    def test_configure_torch_false_skips_the_step(
        self, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            local_only=True,
            skip={"models"},
            configure_torch=False,
        )
        torch = outcome.result_for(ProvisionStep.TORCH)
        assert torch is not None
        assert torch.action == ProvisionAction.SKIPPED


class TestQdrantStep:
    def test_local_only_skips_qdrant_with_reason(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            local_only=True,
            skip={"torch", "models"},
        )
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.SKIPPED
        assert "local-only" in qdrant.detail
        # local-only must not have provisioned anything into the
        # temp-isolated managed dir.
        assert not (isolated_status_dir / "bin").exists()

    def test_skip_token_opts_out_qdrant_without_local_only(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            skip={"torch", "models", "qdrant"},
        )
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.SKIPPED
        assert not (isolated_status_dir / "bin").exists()

    def test_preseeded_install_reports_unchanged_no_network(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        binary = _seed_verified_install()
        assert binary.is_relative_to(isolated_status_dir)
        before = binary.stat().st_mtime_ns

        outcome = provision_dependencies(
            consumer_workspace,
            skip={"torch", "models"},
        )
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.UNCHANGED
        # An unchanged no-op must not rewrite the verified binary.
        assert binary.stat().st_mtime_ns == before

    def test_dry_run_previews_qdrant_without_writing(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            skip={"torch", "models"},
            dry_run=True,
        )
        assert outcome.dry_run is True
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.DRY_RUN
        # Dry-run must not have provisioned a binary into the isolated dir.
        assert not (isolated_status_dir / "bin").exists()


class TestFrontDoorComposition:
    def test_every_considered_dependency_appears_in_the_outcome(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        binary = _seed_verified_install()
        assert binary.is_relative_to(isolated_status_dir)
        outcome = provision_dependencies(
            consumer_workspace,
            skip={"models"},
            assume_yes=True,
        )
        steps = {r.step for r in outcome.steps}
        assert steps == {
            ProvisionStep.TORCH,
            ProvisionStep.MODELS,
            ProvisionStep.QDRANT,
        }
        # The skipped model step is still represented, so the report is
        # complete rather than silently dropping opted-out dependencies.
        models = outcome.result_for(ProvisionStep.MODELS)
        assert models is not None
        assert models.action == ProvisionAction.SKIPPED


class TestFrontDoorIdempotency:
    """Whole-front-door idempotency, dry-run, and local-only skip.

    These exercise the orchestrator end-to-end (not a single step) against
    real backends with no mocks and no network: torch patches a real temp
    pyproject, qdrant runs against a preseeded temp-isolated managed dir,
    and the model step uses the real Hugging Face cache probe (asserted
    only on the network-free outcomes a cached or skipped dev host emits).
    """

    def test_second_run_reports_unchanged_with_no_network(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        binary = _seed_verified_install()
        assert binary.is_relative_to(isolated_status_dir)

        # First run configures torch (created) and verifies the preseeded
        # qdrant binary (unchanged). Models are opted out so the front door
        # never touches the network for a fetch.
        first = provision_dependencies(
            consumer_workspace,
            skip={"models"},
            assume_yes=True,
        )
        first_torch = first.result_for(ProvisionStep.TORCH)
        assert first_torch is not None
        assert first_torch.action == ProvisionAction.CREATED

        before = binary.stat().st_mtime_ns

        # Second run: torch is already configured and the qdrant binary is
        # already verified, so each satisfied dependency reports
        # ``unchanged`` and the verified binary is never rewritten. The
        # opted-out model step stays ``skipped`` (its own honest outcome),
        # so the aggregate is ``mixed`` - per-step idempotency is the
        # contract, not a single collapsed status.
        second = provision_dependencies(
            consumer_workspace,
            skip={"models"},
            assume_yes=True,
        )
        torch = second.result_for(ProvisionStep.TORCH)
        qdrant = second.result_for(ProvisionStep.QDRANT)
        models = second.result_for(ProvisionStep.MODELS)
        assert torch is not None and torch.action == ProvisionAction.UNCHANGED
        assert qdrant is not None and qdrant.action == ProvisionAction.UNCHANGED
        assert models is not None and models.action == ProvisionAction.SKIPPED
        # An idempotent no-op must not have rewritten the verified binary.
        assert binary.stat().st_mtime_ns == before

    def test_satisfied_front_door_is_unchanged_on_second_run(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        # Idempotency of the controllable steps: with the binary seeded and
        # torch configured by the first run, the second run reports both
        # torch and qdrant ``unchanged``. The model step is opted out so the
        # test is hermetic (no network / no model cache assumption); the
        # model step's own cached/dry-run contract is covered by
        # ``TestModelStep``.
        binary = _seed_verified_install()
        assert binary.is_relative_to(isolated_status_dir)
        provision_dependencies(
            consumer_workspace, skip={"models"}, assume_yes=True
        )  # warm torch

        second = provision_dependencies(
            consumer_workspace, skip={"models"}, assume_yes=True
        )
        torch = second.result_for(ProvisionStep.TORCH)
        qdrant = second.result_for(ProvisionStep.QDRANT)
        assert torch is not None and torch.action == ProvisionAction.UNCHANGED
        assert qdrant is not None and qdrant.action == ProvisionAction.UNCHANGED

    def test_dry_run_previews_every_step_without_writing(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            skip={"models"},
            dry_run=True,
            assume_yes=True,
        )
        assert outcome.dry_run is True
        torch = outcome.result_for(ProvisionStep.TORCH)
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        assert torch is not None and torch.action == ProvisionAction.DRY_RUN
        assert torch.sync_pending is True
        assert qdrant is not None and qdrant.action == ProvisionAction.DRY_RUN
        # A preview must not have patched the real pyproject nor provisioned
        # a binary into the isolated managed dir.
        assert (
            detect_state(consumer_workspace / "pyproject.toml")
            != TorchConfigState.CANONICAL
        )
        assert not (isolated_status_dir / "bin").exists()

    def test_local_only_skips_only_the_binary_step(
        self, isolated_status_dir: Path, consumer_workspace: Path
    ) -> None:
        outcome = provision_dependencies(
            consumer_workspace,
            local_only=True,
            skip={"models"},
            assume_yes=True,
        )
        qdrant = outcome.result_for(ProvisionStep.QDRANT)
        torch = outcome.result_for(ProvisionStep.TORCH)
        assert qdrant is not None
        assert qdrant.action == ProvisionAction.SKIPPED
        assert "local-only" in qdrant.detail
        # local-only is the binary escape hatch only: torch still ran.
        assert torch is not None
        assert torch.action == ProvisionAction.CREATED
        # No binary was provisioned into the isolated managed dir.
        assert not (isolated_status_dir / "bin").exists()
