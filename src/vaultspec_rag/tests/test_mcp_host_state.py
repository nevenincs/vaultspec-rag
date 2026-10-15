"""Core's machine-global MCP state, seen from a projection of a workspace.

Core records ownership and executable approvals in the user's home, keyed by
workspace root. These tests run real installs and real core syncs against real
temporary workspaces and prove three things: a projection sees the authority
root's ownership and approvals, it sees nothing else, and the operator's own
home is never written.

Each negative assertion was proven able to fail before it was trusted:

- ``carry_host_state`` granting every launch instead of only the approved ones
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
- ``carry_host_state`` leaving a linked config's ownership at its real
  location fails ``test_a_projection_owns_a_linked_config_through_its_own_file``
  on the externally-managed assertion; restoring it passes.
- ``OwnershipCarry.release`` re-serializing a sidecar the run never touched
  fails ``test_a_run_that_never_touches_the_sidecar_leaves_it_as_found`` on the
  byte comparison; restoring it passes. ``hold`` doing nothing fails
  ``test_held_ownership_is_what_core_finds_at_the_copy`` on the first
  assertion after the swap; restoring it passes. ``hold`` holding a workspace
  whose configs are their own files fails
  ``test_a_workspace_with_no_link_in_the_way_writes_nothing`` on its ``held``
  assertion; restoring it passes.
"""

from __future__ import annotations

import shutil
import stat
from contextvars import Context
from pathlib import Path

import pytest
from vaultspec_core.core.enums import InstallMode, McpScope, McpTargetFormat, Tool
from vaultspec_core.core.home import core_home_layout
from vaultspec_core.core.mcps import (
    mcp_sync,
    mcp_uninstall,
    ownership_path,
    read_ownership,
    write_ownership,
)
from vaultspec_core.core.mcps_ownership import (
    discard_owned_names,
    owned_fingerprints,
    set_owned_fingerprints,
)
from vaultspec_core.core.types import McpTarget

from ..builtins import seed_builtins
from ..commands._install import install_run
from ..commands._mcp_host_state import (
    OwnershipCarry,
    carry_host_state,
    expected_authority_ownership,
    launches_to_enroll,
    projected_core_home,
    rebase_ownership,
)
from ..commands._mcp_topology import SnapshotKind
from ..commands._mcp_trust import LaunchConsent
from ._mcp_consent import (
    approve_install_launches,
    dry_sync,
    grant_launches,
    owned_config_paths,
    rag_tags,
)

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
            carry_host_state(host, mode=InstallMode.TOOL, enrolled=_PROVIDERS)
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


def _claude(path: Path) -> McpTarget:
    return McpTarget(Tool.CLAUDE, McpScope.PROJECT, path, McpTargetFormat.JSON)


def _linked(tmp_path: Path) -> tuple[Path, Path]:
    """Return a workspace with rag installed whose Claude config is now a link.

    The operator moved the config aside and linked it back, and the approval
    and the ownership of rag's entry are where the file really lives, which is
    where core asks about them from then on.
    """
    ws = _installed(tmp_path)
    config = ws / ".mcp.json"
    shared = ws / ".mcp.shared.json"
    sidecar = ownership_path(ws, McpScope.PROJECT)
    state = read_ownership(sidecar)
    owned: dict[str, str | None] = {**owned_fingerprints(state, _claude(config))}
    discard_owned_names(state, _claude(config), set(owned))
    config.replace(shared)
    config.symlink_to(shared.name)
    set_owned_fingerprints(state, _claude(shared), owned)
    write_ownership(sidecar, state)
    grant_launches(ws, ws, mode=InstallMode.TOOL, enrolled=_PROVIDERS)
    return ws, shared


def test_a_projection_owns_a_linked_config_through_its_own_file(
    tmp_path: Path,
) -> None:
    """A projection holds a linked config as a regular file and still owns its entry.

    The authority's ownership is keyed by the link's target. The projection's
    copy of that file is somewhere else, and core asks about ownership there.
    """
    ws, _ = _linked(tmp_path)
    projection = tmp_path / "projection"
    shutil.copytree(ws, projection)
    assert not (projection / ".mcp.json").is_symlink()

    with projected_core_home(ws, projection) as host:
        carry_host_state(host, mode=InstallMode.TOOL, enrolled=_PROVIDERS)
        result = dry_sync(projection, enrolled=_PROVIDERS)

    assert not [w for w in result.warnings if "externally managed" in w]
    assert rag_tags(result) == ["[UNCHANGED]", "[UNCHANGED]"]


def _swapped(ws: Path, shared: Path) -> OwnershipCarry:
    """Capture the carry, then swap the link for a copy as an install does."""
    carry = OwnershipCarry(ws)
    carry.capture(
        Context().run(
            launches_to_enroll, ws, ws, mode=InstallMode.TOOL, enrolled=_PROVIDERS
        )
    )
    config = ws / ".mcp.json"
    config.unlink()
    config.write_bytes(shared.read_bytes())
    return carry


def test_held_ownership_is_what_core_finds_at_the_copy(tmp_path: Path) -> None:
    """Core finds the entry owned at the copy while held, and at the file after.

    The link's target is not where core looks once the link is a copy, and the
    copy is not where it looks once the link is back.
    """
    ws, shared = _linked(tmp_path)
    carry = _swapped(ws, shared)
    assert rag_tags(dry_sync(ws, enrolled=_PROVIDERS))[0] == "[SKIP]"

    carry.hold()

    assert rag_tags(dry_sync(ws, enrolled=_PROVIDERS)) == ["[UNCHANGED]", "[UNCHANGED]"]
    carry.release()
    (ws / ".mcp.json").unlink()
    (ws / ".mcp.json").symlink_to(shared.name)
    assert rag_tags(dry_sync(ws, enrolled=_PROVIDERS)) == ["[UNCHANGED]", "[UNCHANGED]"]
    assert ws.resolve() / ".mcp.json" not in owned_config_paths(ws)


def test_a_run_that_never_touches_the_sidecar_leaves_it_as_found(
    tmp_path: Path,
) -> None:
    """The operator's own bytes come back, even where core would write others."""
    ws, shared = _linked(tmp_path)
    sidecar = ownership_path(ws, McpScope.PROJECT)
    found = sidecar.read_bytes().replace(b"  ", b"\t")
    sidecar.write_bytes(found)
    carry = _swapped(ws, shared)

    carry.hold()
    assert sidecar.read_bytes() != found
    carry.release()

    assert sidecar.read_bytes() == found


def test_a_workspace_with_no_link_in_the_way_writes_nothing(tmp_path: Path) -> None:
    """Nothing is held for a config that is its own file; the sidecar is untouched."""
    ws = _installed(tmp_path)
    sidecar = ownership_path(ws, McpScope.PROJECT)
    found = sidecar.read_bytes().replace(b"  ", b"\t")
    sidecar.write_bytes(found)
    carry = OwnershipCarry(ws)
    carry.capture(
        Context().run(
            launches_to_enroll, ws, ws, mode=InstallMode.TOOL, enrolled=_PROVIDERS
        )
    )

    carry.hold()
    assert carry.held is None
    carry.release()

    assert sidecar.read_bytes() == found


def test_ownership_that_cannot_go_back_fails_the_transaction(tmp_path: Path) -> None:
    """A release that cannot write the sidecar stops the run instead of warning.

    The sidecar and its directory are made read-only once ownership is held,
    so writing it back fails for real: the replace is refused on Windows, and
    the sibling temporary on POSIX. Mutation: recording the failure as a
    warning lets the transaction end normally, which an install then commits,
    and fails the raises assertion; restoring the raise passes.
    """
    ws, shared = _linked(tmp_path)
    consent = LaunchConsent(ws)
    consent.ownership = _swapped(ws, shared)
    sidecar = ownership_path(ws, McpScope.PROJECT)
    writable = {path: path.stat().st_mode for path in (sidecar, sidecar.parent)}

    try:
        with (
            pytest.raises(RuntimeError, match="so the install cannot commit"),
            consent.carried_into_transaction(),
        ):
            assert consent.ownership.held is not None
            sidecar.chmod(stat.S_IREAD)
            sidecar.parent.chmod(stat.S_IREAD | stat.S_IEXEC)
    finally:
        for path, mode in reversed(writable.items()):
            path.chmod(mode)

    assert consent.warnings == []
