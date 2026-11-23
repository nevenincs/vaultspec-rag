"""Every test file runs in exactly one shard, and every shard has a job.

A sharded suite fails silently in two ways: a file that belongs to no shard is
never run, and a shard no job runs takes its files with it. Both leave every
job green.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from dev.guards import _workflows as workflows
from vaultspec_rag.tests._shards import SHARD_ENV, selected_shard, shard_of

pytestmark = [pytest.mark.unit, pytest.mark.repo]

_TEST_TREES = ("src/vaultspec_rag/tests", "tools", "dev")


def _test_files() -> list[str]:
    """Return every test file the suite collects, as pytest names it."""
    root = workflows.repository_root()
    return sorted(
        path.relative_to(root).as_posix()
        for tree in _TEST_TREES
        for path in (root / tree).glob("**/test_*.py")
    )


@pytest.mark.parametrize("count", [1, 3, 6])
def test_every_file_belongs_to_exactly_one_shard(count: int) -> None:
    """Mutation proof: returning a shard above *count* for some files failed
    this on the range assertion; restoring the modulus passed.
    """
    files = _test_files()
    assert files, "no test file was found; refusing to pass vacuously"
    shards = {name: shard_of(f"{name}::test_case", count) for name in files}
    assert set(shards.values()) <= set(range(1, count + 1))
    if count > 1:
        # Nothing so lopsided that one machine carries most of the suite.
        largest = max(
            sum(1 for shard in shards.values() if shard == index)
            for index in range(1, count + 1)
        )
        assert largest < len(files) * 2 / count


def test_a_file_lands_in_the_same_shard_on_every_platform() -> None:
    """Mutation proof: hashing the path as written failed this on the
    comparison; restoring the forward-slash form passed.
    """
    posix = "src/vaultspec_rag/tests/test_example.py::test_case"
    windows = "src\\vaultspec_rag\\tests\\test_example.py::test_case"
    assert shard_of(posix, 5) == shard_of(windows, 5)


@pytest.mark.parametrize("raw", ["0/3", "4/3", "1", "a/3", "1/0", "1/3/5", "-1/3"])
def test_a_malformed_shard_is_refused(raw: str) -> None:
    """Mutation proof: treating an unreadable value as no shard at all failed
    every case here on ``pytest.raises``; restoring the refusal passed.
    """
    with pytest.raises(ValueError, match=SHARD_ENV):
        selected_shard({SHARD_ENV: raw})


def test_no_shard_selects_the_whole_suite() -> None:
    assert selected_shard({}) is None
    assert selected_shard({SHARD_ENV: "2/3"}) == (2, 3)


def test_every_shard_a_job_declares_has_a_leg() -> None:
    """A job that names a shard count runs every index of it, once.

    Mutation proof: dropping one index from a matrix failed this naming the
    job and its shards; restoring it passed.
    """
    directory = workflows.repository_root() / ".github" / "workflows"
    sharded = 0
    for workflow in sorted(path.name for path in directory.glob("*.yml")):
        jobs = cast("dict[str, dict[str, Any]]", workflows.document(workflow)["jobs"])
        for job_id, job in jobs.items():
            env = cast("dict[str, object]", job.get("env") or {})
            template = str(env.get(SHARD_ENV, ""))
            if not template:
                continue
            sharded += 1
            prefix, _, count = template.rpartition("/")
            assert prefix == "${{ matrix.shard }}", f"{workflow}:{job_id}: {template}"
            declared = job["strategy"]["matrix"]["shard"]
            assert declared == list(range(1, int(count) + 1)), (
                f"{workflow}:{job_id} runs shards {declared} of {count}"
            )
            assert job["strategy"].get("fail-fast") is False, (
                f"{workflow}:{job_id} would cancel the other shards on one failure"
            )
    assert sharded, "no sharded job was found; refusing to pass vacuously"
