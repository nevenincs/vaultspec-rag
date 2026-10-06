"""A project checkout cannot hand its own code to the model download child.

A model is fetched by ``install``, by ``server warmup`` and by the first
``server start``, each of which is typed inside a project checkout. The fetch
runs in a child process so that it can be stopped, and that child must run the
installed package whatever the checkout ships under the same name.

The child is the one the production fetch starts. The hub client is told it is
offline, so the child runs its whole start-up, asks for the repository, is
refused before any connection is opened, reports that one failure and ends.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from ..commands._hub_failure import HubFailure
from ..commands._model_download import download_snapshot
from .test_python_child_shadowing import (
    _checkout,
    _plant_module,
    _plant_package,
    _run_in,
    unswitched,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

__all__ = ["unswitched"]

_ABSENT_REPOSITORY = "vaultspec-rag-tests/not-a-repository"


@pytest.fixture
def offline_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unswitched: None
) -> None:
    """The download child reaches no hub and writes to no real cache."""
    del unswitched
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hub"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub" / "cache"))


def test_the_model_download_child_does_not_import_from_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline_hub: None
) -> None:
    """A model fetch run from a checkout downloads with the installed package.

    Shown to fail on the command the fetch built before it used the command
    builder - the interpreter, the module switch and the module, with no
    safe-path flag: the planted package ran in place of the download child,
    the first assertion fired, and the download was reported as having died.
    Passes on the builder's command.
    """
    del offline_hub
    checkout = _checkout(tmp_path, "checkout")
    package_ran = _plant_package(checkout)
    dependency_ran = _plant_module(checkout, "huggingface_hub")
    monkeypatch.chdir(checkout)

    outcome = download_snapshot(_ABSENT_REPOSITORY, revision=None)

    assert not package_ran.exists(), "the checkout's package ran as the download"
    assert not dependency_ran.exists(), "the checkout's module ran in the download"
    # The real child ran far enough to ask the hub client and report its answer.
    assert outcome.failure is not None
    assert outcome.failure is not HubFailure.DIED, outcome.message


def test_the_download_child_started_the_old_way_runs_the_checkout(
    tmp_path: Path, offline_hub: None
) -> None:
    """Control: both plants are live for the download child's module."""
    del offline_hub
    command = [
        sys.executable,
        "-m",
        "vaultspec_rag.commands._model_download_child",
        _ABSENT_REPOSITORY,
    ]
    both = _checkout(tmp_path, "both")
    package_ran = _plant_package(both)
    only_dependency = _checkout(tmp_path, "dependency")
    dependency_ran = _plant_module(only_dependency, "huggingface_hub")

    _run_in(both, command)
    _run_in(only_dependency, command)

    assert package_ran.exists()
    assert dependency_ran.exists()
