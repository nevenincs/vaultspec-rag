"""Core's machine-global MCP state, seen from a projection of a workspace.

Core records ownership and executable approvals in the user's home, keyed by
workspace root. These tests run real installs and real core syncs against real
temporary workspaces and prove three things: a projection sees the authority
root's ownership and approvals, it sees nothing else, and the operator's own
home is never written.

Each negative assertion was proven able to fail before it was trusted:

- ``carry_consent`` granting every launch instead of only the approved ones
  fails ``test_a_projection_is_approved_only_for_launches_the_operator_approved``
  on its unapproved-launch assertion; restoring it passes.
- ``rebase_ownership`` moving a record's path but keeping its old key fails
  ``test_rebased_ownership_is_accepted_by_core_and_round_trips`` when core
  refuses to read the result; restoring it passes.
- ``projected_core_home`` leaving the user's own home in place instead of
  switching to the throwaway one fails
  ``test_a_projection_never_writes_the_operators_home`` on its first assertion;
  restoring it passes. Overwriting the operator's ownership on entry fails the
  same test on the unchanged-home assertion; restoring it passes.
"""

from __future__ import annotations

import shutil
from contextvars import Context
from pathlib import Path

import pytest
from vaultspec_core.core.enums import InstallMode, McpScope, Tool
from vaultspec_core.core.home import core_home_layout
from vaultspec_core.core.mcps import (
    mcp_sync,
    mcp_uninstall,
    ownership_path,
    read_ownership,
)

from ..builtins import seed_builtins
from ..commands._install import install_run
from ..commands._mcp_host_state import (
    carry_consent,
    expected_authority_ownership,
    projected_core_home,
    rebase_ownership,
)
from ..commands._mcp_topology import SnapshotKind
from ._mcp_consent import approve_install_launches, grant_launches

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_mcp_trust_home")]

_PROVIDERS = (Tool.CLAUDE, Tool.CODEX)


def _installed(tmp_path: Path) -> Path:
    """Return a workspace with rag installed and enrolled for both providers."""
    ws = tmp_path / "ws"
    ws.mkdir()
    approve_install_launches(ws, install_mcp=True, mode=InstallMode.TOOL)
    report = install_run(
        path=ws,
        install_mcp=True,
        mode=InstallMode.TOOL,
        provision=False,
        configure_torch=False,
    )
    assert not report.mcp_sync_failed
    return ws


def _home_files() -> dict[str, bytes]:
    """Capture every file in the user's core home."""
    root = core_home_layout().root
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_a_projection_never_writes_the_operators_home(tmp_path: Path) -> None:
    """Core run inside a projection writes the throwaway home, never the user's.

    Pruning rag from the projection makes core rewrite its ownership, which
    only prunes anything because the authority's ownership was carried in.
    """
    ws = _installed(tmp_path)
    projection = tmp_path / "projection"
    shutil.copytree(ws, projection)
    operator_home = Path.home()
    operator_files = _home_files()
    authority_ownership = ownership_path(ws, McpScope.PROJECT).read_bytes()

    with projected_core_home(ws, projection) as host:
        assert Path.home() != operator_home
        assert host.work_ownership.is_file()
        result = Context().run(
            mcp_uninstall,
            projection,
            dry_run=False,
            provider="all",
            scope="project",
            names=frozenset({"vaultspec-rag"}),
        )
        replayed = expected_authority_ownership(host)

    assert result.pruned == len(_PROVIDERS)
    # Pruning the only managed entry empties the sidecar, and core then removes it.
    assert replayed.kind is SnapshotKind.ABSENT
    assert Path.home() == operator_home
    assert not host.home.exists()
    assert _home_files() == operator_files
    assert ownership_path(ws, McpScope.PROJECT).read_bytes() == authority_ownership


def test_rebased_ownership_is_accepted_by_core_and_round_trips(tmp_path: Path) -> None:
    """Ownership moved to another root is valid to core and moves back unchanged."""
    ws = _installed(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    original = ownership_path(ws, McpScope.PROJECT).read_bytes()

    moved = rebase_ownership(original, ws, other)

    assert moved != original
    destination = tmp_path / "moved-ownership.json"
    destination.write_bytes(moved)
    targets = read_ownership(destination)["targets"]
    assert targets
    for key, record in targets.items():
        path = record.get("path")
        assert path is not None
        assert key == f"{record.get('provider')}:{record.get('scope')}:{path}"
        assert Path(path).is_relative_to(other.resolve())
    assert rebase_ownership(moved, other, ws) == original


def test_unreadable_ownership_passes_through_untouched(tmp_path: Path) -> None:
    """Bytes core would refuse are left alone, so a projection fails like the root."""
    corrupt = b"{not-json"

    assert rebase_ownership(corrupt, tmp_path / "a", tmp_path / "b") == corrupt


def test_a_projection_is_approved_only_for_launches_the_operator_approved(
    tmp_path: Path,
) -> None:
    """A projection enrolls what the authority approved and skips what it did not."""
    ws = tmp_path / "ws"
    ws.mkdir()
    seed_builtins(ws / ".vaultspec")

    def preview(label: str) -> list[list[str]]:
        projection = tmp_path / label
        shutil.copytree(ws, projection)
        with projected_core_home(ws, projection) as host:
            carry_consent(host, mode=InstallMode.TOOL, enrolled=_PROVIDERS)
            result = Context().run(
                mcp_sync,
                dry_run=True,
                mode=InstallMode.TOOL,
                provider="all",
                scope="project",
                target_dir=projection,
                enrolled=_PROVIDERS,
            )
        return [list(item) for item in result.items]

    unapproved = preview("before-approval")
    assert ["vaultspec-rag", "[SKIP]"] in unapproved
    assert ["vaultspec-rag", "[ADD]"] not in unapproved

    grant_launches(ws, ws, mode=InstallMode.TOOL, enrolled=_PROVIDERS)

    assert ["vaultspec-rag", "[ADD]"] in preview("after-approval")
