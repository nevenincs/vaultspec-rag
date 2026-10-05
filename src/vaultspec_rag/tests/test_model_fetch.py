"""The one model fetch every command reaches through the provisioning front door.

``install``, ``server warmup`` and the preflight of ``server start`` all ensure
the model files through the same step, so what is proven here holds for all
three: the cache is probed per repository, a missing repository is a preview
under dry-run and a loud failure with the hub offline, every repository is
attempted before the result comes back, and the probe is reported through
whatever sink the command supplied.

The model cache is a directory the test seeds and the product's own probe
reads, with the hub's offline switch set, so no outcome depends on which
weights the host holds and nothing can be downloaded. The download branch
itself needs the network and is left to the accelerator tier.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from .._sync_vocabulary import ProvisionAction
from ..commands._install import install_run
from ..commands._model_fetch import MODELS_OFFLINE
from ..commands._provision import ProvisionStep, provision_models
from ..config._settings import configured_model_repos
from ..config._types import EnvVar
from ._model_cache_seed import seed_model_cache
from ._provision_fixtures import result_for
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]

_ABSENT_MODEL = "vaultspec-test/absent-dense"

PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


class _RecordingProgress:
    """A sink that keeps what the front door reported, for assertions.

    An implementation of the front door's own reporting protocol, not a
    substitute for anything: the fetch runs unchanged and this is simply where
    it was told to report.
    """

    def __init__(self) -> None:
        self.stages: list[str] = []
        self.downloads: list[str] = []

    def stage(self, label: str) -> None:
        self.stages.append(label)

    @contextmanager
    def download(self, heading: str) -> Generator[type[Any] | None]:
        self.downloads.append(heading)
        yield None


@pytest.fixture(autouse=True)
def offline_hub() -> Generator[None]:
    """Set the hub's offline switch, so no test here can start a download."""
    with managed_env(**{EnvVar.HF_HUB_OFFLINE.value: "1"}):
        yield


def test_a_fully_cached_inventory_is_unchanged_and_names_every_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")
    inventory = configured_model_repos()
    progress = _RecordingProgress()

    result = provision_models(progress=progress)

    assert result.step == ProvisionStep.MODELS
    assert result.action == ProvisionAction.UNCHANGED
    assert result.detail == f"all {len(inventory)} model repos already cached"
    assert [(repo.label, repo.repo, repo.detail) for repo in result.repos] == [
        (label, repo, "cached") for label, repo in inventory
    ]
    assert progress.stages == [
        f"Checking the cache for {label} ({position}/{len(inventory)})"
        for position, (label, _repo) in enumerate(inventory, start=1)
    ]
    assert progress.downloads == []


def test_a_missing_repo_with_the_hub_offline_fails_and_names_the_remedy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline is honoured: a missing model is a failure, not a download.

    The missing repository is the first in the inventory and exists nowhere.
    The later ones are still probed and reported, because a fetch that stopped
    at the first unavailable repository would hide the next.

    Mutation check: with the offline branch removed from the fetch, the hub is
    asked for the repository and the step fails as ``models_fetch_failed`` -
    failing the code assertion, and the download assertion with the heading
    it recorded. Restoring the branch passes.
    """
    progress = _RecordingProgress()
    with managed_env(**{EnvVar.EMBEDDING_MODEL.value: _ABSENT_MODEL}):
        seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL])
        inventory = configured_model_repos()
        assert inventory[0][1] == _ABSENT_MODEL, "premise: the first repo is absent"

        result = provision_models(progress=progress)

    assert progress.downloads == [], "a download was attempted with the hub offline"
    assert result.action == ProvisionAction.FAILED
    assert result.code == MODELS_OFFLINE
    assert _ABSENT_MODEL in result.detail
    assert EnvVar.HF_HUB_OFFLINE.value in result.detail
    assert "vaultspec-rag server warmup" in result.detail
    assert [repo.action for repo in result.repos] == [
        ProvisionAction.FAILED,
        *[ProvisionAction.UNCHANGED] * (len(inventory) - 1),
    ]


def test_a_missing_repo_under_dry_run_is_previewed_not_fetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    progress = _RecordingProgress()
    with managed_env(**{EnvVar.EMBEDDING_MODEL.value: _ABSENT_MODEL}):
        seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL])

        result = provision_models(dry_run=True, progress=progress)

    assert progress.downloads == []
    assert result.action == ProvisionAction.DRY_RUN
    assert result.code == ""
    assert result.detail == f"would download 1 missing model repo(s): {_ABSENT_MODEL}"


def test_install_reports_the_model_probe_through_the_sink_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_status_dir: Path,
) -> None:
    """``install`` reaches the same fetch and reports it the same way.

    The sink arrives at the model step through the install orchestration, so
    an install shows the cache probe and the download it is waiting on in the
    words the service verbs use.
    """
    del isolated_status_dir
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")
    workspace = tmp_path / "consumer"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        PROJECT_ONLY, encoding="utf-8", newline=""
    )
    inventory = configured_model_repos()
    progress = _RecordingProgress()

    report = install_run(
        path=workspace,
        provision=True,
        local_only=True,
        assume_yes=True,
        provision_progress=progress,
    )

    outcome = report.provision_outcome
    assert outcome is not None
    models = result_for(outcome, ProvisionStep.MODELS)
    assert models is not None
    assert models.action == ProvisionAction.UNCHANGED
    assert progress.stages == [
        f"Checking the cache for {label} ({position}/{len(inventory)})"
        for position, (label, _repo) in enumerate(inventory, start=1)
    ]
