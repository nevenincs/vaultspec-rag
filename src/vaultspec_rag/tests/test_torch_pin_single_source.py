"""The accelerated torch version has one source: the lockfile.

The binary build names the accelerated torch version, and the lockfile is the
only place that version is decided. This file exists so a derivation that
cannot read it fails here rather than shipping a version nobody chose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..torch_config._lockfile import LockedTorchVersionError, locked_torch_version

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_an_unreadable_lockfile_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """A missing or ambiguous lockfile raises instead of inventing a version."""
    with pytest.raises(LockedTorchVersionError):
        locked_torch_version(tmp_path)
