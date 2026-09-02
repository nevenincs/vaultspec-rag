"""Teardown reclaims a session root without taking the failure evidence.

The session root holds two very different things side by side: the
machine-singleton tree (isolated status dir and Qdrant storage), which is the
bulk of a run's footprint and carries no diagnostics, and ``basetemp``, which
holds the ``tmp_path`` directories pytest retains under
``tmp_path_retention_policy = "failed"``. Teardown removed the root wholesale,
so a failing run's evidence was destroyed by the cleanup meant to protect the
disk, and an inherited root was never reclaimed at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._test_isolation import reclaim_singleton_paths, singleton_child_names

if TYPE_CHECKING:
    from pathlib import Path


def _populate(root: Path, worker: str | None = None) -> tuple[Path, Path]:
    """Lay out a session root the way ``pytest_configure`` does."""
    machine_singleton, basetemp = singleton_child_names(worker)
    heavy = root / machine_singleton / "qdrant-server" / "storage"
    heavy.mkdir(parents=True)
    (heavy / "segment.bin").write_bytes(b"stand-in for a real collection")
    evidence = root / basetemp / "test_something0"
    evidence.mkdir(parents=True)
    (evidence / "evidence.log").write_text("why it failed", encoding="utf-8")
    return root / machine_singleton, root / basetemp


@pytest.mark.unit
def test_a_failed_session_keeps_its_evidence_and_still_drops_the_heavy_tree(
    tmp_path: Path,
) -> None:
    """The one thing cleanup must not take is why the run failed."""
    root = tmp_path / "vaultspec-rag-pytest-failed"
    root.mkdir()
    machine_singleton, basetemp = _populate(root)

    reclaim_singleton_paths(
        root, owned_root=True, owned_pair=True, keep_diagnostics=True
    )

    assert not machine_singleton.exists()
    assert (basetemp / "test_something0" / "evidence.log").read_text(
        encoding="utf-8"
    ) == "why it failed"
    assert root.exists()


@pytest.mark.unit
def test_a_green_session_leaves_nothing_behind(tmp_path: Path) -> None:
    """Nothing is worth keeping from a run with no failures."""
    root = tmp_path / "vaultspec-rag-pytest-green"
    root.mkdir()
    _populate(root)

    reclaim_singleton_paths(
        root, owned_root=True, owned_pair=True, keep_diagnostics=False
    )

    assert not root.exists()


@pytest.mark.unit
def test_an_inherited_root_is_reclaimed_without_removing_the_root(
    tmp_path: Path,
) -> None:
    """An xdist worker owns the pair it wrote, never the root it was handed.

    Before this, a process that inherited its root reclaimed nothing at all: the
    ownership flag gated the whole teardown, so every worker's storage tree
    survived the session, and a root established outside the system temp dir was
    never swept either.
    """
    root = tmp_path / "vaultspec-rag-pytest-shared"
    root.mkdir()
    controller_singleton, controller_basetemp = _populate(root)
    worker_singleton, worker_basetemp = _populate(root, worker="gw0")

    reclaim_singleton_paths(
        root,
        owned_root=False,
        owned_pair=True,
        keep_diagnostics=False,
        worker="gw0",
    )

    assert not worker_singleton.exists()
    assert not worker_basetemp.exists()
    assert root.exists()
    assert controller_singleton.exists()
    assert controller_basetemp.exists()


@pytest.mark.unit
def test_reclaim_tolerates_a_root_that_is_already_gone(tmp_path: Path) -> None:
    """The atexit backstop runs after normal teardown already reclaimed."""
    reclaim_singleton_paths(
        tmp_path / "never-created",
        owned_root=True,
        owned_pair=True,
        keep_diagnostics=False,
    )


@pytest.mark.unit
def test_worker_names_are_distinct_so_participants_never_collide(
    tmp_path: Path,
) -> None:
    """One root holds the controller's pair and every worker's pair at once."""
    del tmp_path
    assert singleton_child_names(None) == ("machine-singleton", "pytest-temp")
    assert singleton_child_names("gw3") == (
        "machine-singleton-gw3",
        "pytest-temp-gw3",
    )


@pytest.mark.unit
def test_a_nested_subprocess_never_reclaims_its_live_parents_pair(
    tmp_path: Path,
) -> None:
    """A child inherits the root and the worker id, so it derives the same names.

    Mutation proof: dropping the ``owned_pair`` gate made this delete the
    parent's basetemp, and the real suite reported it as five fixture setup
    errors reading ``FileNotFoundError: ... pytest-temp-gw10``.
    """
    root = tmp_path / "vaultspec-rag-pytest-parent"
    root.mkdir()
    machine_singleton, basetemp = _populate(root, worker="gw10")

    reclaim_singleton_paths(
        root,
        owned_root=False,
        owned_pair=False,
        keep_diagnostics=False,
        worker="gw10",
    )

    assert machine_singleton.exists()
    assert (basetemp / "test_something0" / "evidence.log").exists()
