"""The seeded MCP launch names the release this installation runs.

``uvx --from vaultspec-rag[mcp]`` resolves the newest published release, so an
unpinned launch puts the assistant on a release other than the service's the
day a new one ships, and a client refuses a service of another release.
"""

from __future__ import annotations

import json
from importlib import metadata
from typing import TYPE_CHECKING

import pytest

from ..builtins import seed_builtins

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_DEFINITION = "mcps/vaultspec-rag.builtin.json"
_SPEC_KEY = "_vaultspec_mode_tool_spec"


def _seeded_spec(target: Path) -> str:
    seed_builtins(target)
    return json.loads((target / _DEFINITION).read_text(encoding="utf-8"))[_SPEC_KEY]


def test_the_seeded_launch_pins_this_release(tmp_path: Path) -> None:
    # Seeding the bundled text unchanged fails here with the bare spec.
    assert _seeded_spec(tmp_path) == (
        f"vaultspec-rag[mcp]=={metadata.version('vaultspec-rag')}"
    )


def test_a_reseed_of_the_pinned_file_is_unchanged(tmp_path: Path) -> None:
    # Classifying against the bundled bytes instead of the seeded text reads
    # every forced reseed as an update.
    seed_builtins(tmp_path)
    again = dict(seed_builtins(tmp_path, force=True))
    assert again[_DEFINITION] == "[UNCHANGED]"


@pytest.mark.parametrize("version", ["0.7.0.dev3", "0.7.0+local"])
def test_a_version_no_index_serves_is_not_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    """A checkout's own version would make the launch unresolvable.

    The installed version is the one input substituted: a checkout cannot be
    made to carry a development version from inside a test. Dropping the
    development and local test fails this on the pinned spec.
    """

    def installed(name: str) -> str:
        return version if name == "vaultspec-rag" else metadata.version(name)

    monkeypatch.setattr(metadata, "version", installed)
    assert _seeded_spec(tmp_path) == "vaultspec-rag[mcp]"
