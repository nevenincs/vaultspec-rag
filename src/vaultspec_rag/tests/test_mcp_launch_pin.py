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
from ._separate_installation import build_installation

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_DEFINITION = "mcps/vaultspec-rag.builtin.json"
_SPEC_KEY = "_vaultspec_mode_tool_spec"

#: Seeds the bundled builtins from inside an installation and reports the launch
#: it wrote, with the version and package location the interpreter resolved, so
#: a caller can tell it ran against the installation it built.
_SEED_FROM_AN_INSTALLATION = """
import json
import pathlib
import sys
from importlib import metadata

import vaultspec_rag
from vaultspec_rag.builtins import seed_builtins

target = pathlib.Path(json.loads(sys.argv[1])[0])
seed_builtins(target)
definition = json.loads(
    (target / "mcps/vaultspec-rag.builtin.json").read_text(encoding="utf-8")
)
print(json.dumps({
    "spec": definition["_vaultspec_mode_tool_spec"],
    "version": metadata.version("vaultspec-rag"),
    "package": str(pathlib.Path(vaultspec_rag.__file__).parent),
}))
"""


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


@pytest.mark.parametrize(
    ("version", "pinned"),
    [
        pytest.param("0.7.0", True, id="release"),
        pytest.param("0.7.0.dev3", False, id="development"),
        pytest.param("0.7.0+local", False, id="local"),
    ],
)
def test_only_a_version_an_index_serves_is_pinned(
    tmp_path: Path, version: str, pinned: bool
) -> None:
    """A checkout's own version would make the launch unresolvable.

    Each case seeds from a separate installation of this package whose
    distribution record states the version, so the production reader reads it
    from where an installer wrote it. The assertion on the version and package
    path proves the run was in that installation and not in this one.

    Mutation: returning ``str(version)`` without the development and local
    check in ``_published_release`` fails the ``development`` and ``local``
    cases on the spec, and the ``release`` case still passes; deleting the
    pin fails the ``release`` case. Restored, all three pass.
    """
    installation = build_installation(
        tmp_path / "installation", version=version, direct_url=None
    )
    seeded = installation.run(_SEED_FROM_AN_INSTALLATION, str(tmp_path / "seeded"))

    assert seeded["version"] == version
    assert str(seeded["package"]).startswith(str(installation.root))
    assert seeded["spec"] == (
        f"vaultspec-rag[mcp]=={version}" if pinned else "vaultspec-rag[mcp]"
    )
