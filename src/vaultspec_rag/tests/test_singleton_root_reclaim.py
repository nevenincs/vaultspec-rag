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

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._singleton_root_fixtures import reclaim_singleton_paths, singleton_child_names


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


@pytest.mark.unit
@pytest.mark.parametrize("worker", [None, "gw3"])
@pytest.mark.parametrize("fails", [False, True])
def test_nested_pytest_tmp_path_preserves_live_parent_files(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    worker: str | None,
    fails: bool,
) -> None:
    """A real nested factory must not erase the running parent's basetemp.

    Before process-qualified names, the real child tmp_path fixture erased
    parent-sentinel and this test failed with FileNotFoundError. After repair,
    successful and failing children preserved it and their own cleanup contract.
    """
    sentinel = tmp_path / "parent-sentinel"
    sentinel.write_text("parent remains live", encoding="utf-8")
    storage = Path(os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"])
    storage.mkdir(parents=True, exist_ok=True)
    lock = storage.parent / "parent-lock-witness"
    lock.write_text("parent storage remains", encoding="utf-8")
    child_test = tmp_path / "test_nested_factory.py"
    child_config = tmp_path / "pytest.ini"
    child_config.write_text(
        "[pytest]\nasyncio_default_fixture_loop_scope = function\n"
        "markers =\n    unit: CPU-only isolation test\n",
        encoding="utf-8",
    )
    child_test.write_text(
        "import json, os\nfrom pathlib import Path\nimport pytest\n"
        "@pytest.mark.unit\n"
        "def test_factory(tmp_path):\n"
        "    storage = Path(os.environ['VAULTSPEC_RAG_QDRANT_STORAGE_DIR'])\n"
        "    print('CHILD_DIRS=' + json.dumps({\n"
        "        'singleton': storage.parent.parent.name,\n"
        "        'basetemp': tmp_path.parent.name}), flush=True)\n"
        "    (tmp_path / 'child-evidence').write_text('child failure')\n"
        f"    assert {not fails!r}\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    if worker is None:
        environment.pop("PYTEST_XDIST_WORKER", None)
    else:
        environment["PYTEST_XDIST_WORKER"] = worker
    root = Path(environment["_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(child_config),
            "-p",
            "conftest",
            f"--confcutdir={tmp_path}",
            str(child_test),
            "-q",
            "-s",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        env=environment,
    )
    assert sentinel.read_text(encoding="utf-8") == "parent remains live"
    assert lock.read_text(encoding="utf-8") == "parent storage remains"
    assert result.returncode == int(fails), result.stdout + result.stderr
    records = [
        json.loads(line.removeprefix("CHILD_DIRS="))
        for line in result.stdout.splitlines()
        if line.startswith("CHILD_DIRS=")
    ]
    assert len(records) == 1
    match records[0]:
        case {"singleton": str() as singleton_name, "basetemp": str() as temp_name}:
            assert Path(singleton_name).name == singleton_name
            assert Path(temp_name).name == temp_name
            child_singleton = root / singleton_name
            child_temp = root / temp_name
        case _:
            pytest.fail("child did not identify its own session directories")
    assert not child_singleton.exists()
    if fails:
        evidence = list(child_temp.rglob("child-evidence"))
        assert len(evidence) == 1
        assert evidence[0].read_text() == "child failure"
    else:
        assert not child_temp.exists()
    assert Path(request.config.option.basetemp).is_dir()
