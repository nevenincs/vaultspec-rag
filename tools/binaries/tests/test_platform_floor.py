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


def test_a_pinned_manylinux_image_declares_the_floor_it_actually_provides(
    repo_root: Path,
) -> None:
    """A containerised leg's image and its declared floor must not drift apart.

    Pinning the build environment is what turns the floor from something the
    host happens to satisfy into something the build enforces - but only while
    the two agree. Bumping the image to ``manylinux_2_34`` without moving the
    table would leave this project promising 2.28 and shipping an artifact that
    needs 2.34, and every distribution between the two would fail at load time
    with a missing symbol version rather than anything CI reported.

    The reverse drift is just as wrong and reads as conservative: a floor
    declared ABOVE what the image provides drops platforms the binary would in
    fact have run on.
    """
    checked = 0
    for leg in _legs(repo_root):
        image = leg.get("container") or ""
        match = _MANYLINUX.search(image)
        if match is None:
            continue
        provided = (int(match.group(1)), int(match.group(2)))
        target = leg["target"]

        assert target in GLIBC_FLOOR, (
            f"{target} builds in {image} but declares no floor"
        )
        assert GLIBC_FLOOR[target] == provided, (
            f"{target} builds in an image providing glibc "
            f"{provided[0]}.{provided[1]} but declares "
            f"{GLIBC_FLOOR[target][0]}.{GLIBC_FLOOR[target][1]}"
        )
        checked += 1

    assert checked, "no leg pins a manylinux image; this guard is vacuous"


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
