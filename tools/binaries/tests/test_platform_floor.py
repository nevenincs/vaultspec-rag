"""Guards tying the declared glibc floor to the matrix that has to meet it.

The floor is a property of the artifact, not of this repository: the linker
records whatever the build's libc offers and the loader refuses the
binary on anything older. ``check_platform_floor`` reads it back out of the
built artifact, which is the only place it can honestly be measured, and that
check runs in CI where an artifact exists.

What can be checked from source is the WIRING around it: every Linux target
the matrix builds must declare a floor, or the check inspects nothing for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from tools.binaries.build_pyapp import GLIBC_FLOOR

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


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
    whatever its build produced.
    """
    targets = [
        leg["target"] for leg in _legs(repo_root) if "linux-gnu" in leg["target"]
    ]

    assert targets, "no Linux target in the matrix; this guard is vacuous"
    for target in targets:
        assert target in GLIBC_FLOOR, f"{target} is built but declares no floor"
