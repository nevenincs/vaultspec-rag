"""Guards tying the declared glibc floor to the matrix that has to meet it.

The floor is a property of the artifact, not of this repository: the linker
records whatever the build machine's libc offers and the loader refuses the
binary on anything older. ``check_platform_floor`` reads it back out of the
built artifact, which is the only place it can honestly be measured, and that
check runs in CI where an artifact exists.

What can be checked from source is the WIRING around it, and that is what
breaks. The guards here exist because this project has already been on the
wrong side of them: v0.4.15 pinned a manylinux image to a runner that could not
start one, and the aarch64 leg then built natively at glibc 2.39 while the
table still had to be corrected by hand to say so.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

from tools.binaries.build_pyapp import GLIBC_FLOOR

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: ``quay.io/pypa/manylinux_2_28_aarch64@sha256:...`` -> ``(2, 28)``.
_MANYLINUX = re.compile(r"manylinux_(\d+)_(\d+)_")


def _legs(repo_root: Path) -> list[dict[str, str]]:
    workflow = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
            encoding="utf-8"
        )
    )
    return workflow["jobs"]["build"]["strategy"]["matrix"]["include"]


def test_every_linux_gnu_target_built_by_ci_declares_a_floor(
    repo_root: Path,
) -> None:
    """A new Linux leg must not escape the check by omission from the table.

    Omission is silent in the direction that matters: ``check_platform_floor``
    inspects nothing for a target it cannot find, so an undeclared leg ships
    whatever its build host produced.
    """
    targets = [
        leg["target"] for leg in _legs(repo_root) if "linux-gnu" in leg["target"]
    ]

    assert targets, "no Linux target in the matrix; this guard is vacuous"
    for target in targets:
        assert target in GLIBC_FLOOR, f"{target} is built but declares no floor"


def test_no_build_leg_uses_a_job_container(
    repo_root: Path,
) -> None:
    """Every leg builds natively on the runner it names.

    No fleet host exposes a container runtime: the x86_64 Linux host has
    neither docker nor podman on PATH, and the ARM64 runner is itself a
    container with no socket mounted and no client in its image. A
    ``container:`` on any leg therefore dies in ``Initialize containers``
    before checkout, which is how v0.4.15 published no Linux binary at all.

    A runner named for a container runtime does not prove it exposes one; that
    inference previously sat in this file and was wrong.

    Mutation proof: putting the manylinux image back on ``linux-x86_64`` made
    this fail naming that leg; removing it made it pass.
    """
    offenders = [
        f"{leg['name']} -> {leg['container']}"
        for leg in _legs(repo_root)
        if leg.get("container")
    ]

    assert not offenders, (
        "these legs ask for a job container, which no fleet host can start: "
        f"{offenders}"
    )


def test_an_uncontainerised_linux_leg_is_not_silently_trusted(
    repo_root: Path,
) -> None:
    """A Linux leg with no image inherits its host's glibc, so say which ones.

    This does not fail such a leg - building natively is a legitimate choice
    when no host can run the image, and this project shipped aarch64 that way
    for several releases. It fails only if one exists while claiming a floor
    lower than the pinned legs, which is the combination that cannot be true:
    an unpinned build cannot promise a floor below what its host provides.
    """
    pinned = [
        GLIBC_FLOOR[leg["target"]]
        for leg in _legs(repo_root)
        if _MANYLINUX.search(leg.get("container") or "")
        and leg["target"] in GLIBC_FLOOR
    ]
    if not pinned:
        pytest.skip("no pinned leg to compare against")
    lowest_pinned = min(pinned)

    for leg in _legs(repo_root):
        if leg.get("container") or "linux-gnu" not in leg["target"]:
            continue
        target = leg["target"]
        assert GLIBC_FLOOR[target] >= lowest_pinned, (
            f"{target} builds with no pinned image yet declares a floor below "
            f"the pinned legs; an unpinned build cannot promise that"
        )
