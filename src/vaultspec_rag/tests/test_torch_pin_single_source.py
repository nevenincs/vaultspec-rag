"""The tool-env torch pin has one source: the lockfile.

The remediation command names a wheel by exact version, so a stale pin hands an
operator a URL for a release their project no longer uses. The lockfile is the
only place that version is decided; this file exists so a lock bump that
forgets the runtime mirror fails here rather than in someone's terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..torch_config._constants import TORCH_TOOL_PIN_VERSION
from ..torch_config._lockfile import LockedTorchVersionError, locked_torch_version

pytestmark = [pytest.mark.unit]


def _repository_root() -> Path | None:
    """Return the checkout root, or None when running from an installed wheel."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "uv.lock").is_file():
            return candidate
    return None


def test_the_runtime_pin_mirrors_the_locked_version() -> None:
    """The constant equals what the lockfile pins, base version for base version.

    Guard assertion: these are two spellings of one fact, and the constant is
    the copy that cannot derive itself at runtime. Nothing else notices when it
    drifts.
    """
    root = _repository_root()
    if root is None:
        pytest.skip("no lockfile reachable; running from an installed distribution")

    locked = locked_torch_version(root)

    assert locked.partition("+")[0] == TORCH_TOOL_PIN_VERSION


def test_an_unreadable_lockfile_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """A missing or ambiguous lockfile raises instead of inventing a version."""
    with pytest.raises(LockedTorchVersionError):
        locked_torch_version(tmp_path)
