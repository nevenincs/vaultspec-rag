"""Core's machine-global MCP state, made visible to a projection of a workspace.

Core keeps two records outside the repository, in the operator's home, both
keyed by the workspace root: which native MCP entries it owns, and which
executable launches the operator approved. A preview or a replay runs core
against a projection at a different root, so core would plan it as a workspace
that owns nothing and approved nothing, and the plan would never match what the
real root does.

``projected_core_home`` gives such a run a throwaway home, carries the
authority root's ownership into it re-keyed to the projection, and
``carry_consent`` carries over exactly the launches the operator already
approved for the authority root. The operator's own home is only ever read.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from vaultspec_core.core.enums import McpScope, McpTargetFormat, Tool
from vaultspec_core.core.home import core_home_layout
from vaultspec_core.core.mcps import (
    collect_mcp_servers,
    ownership_path,
    ownership_target_key,
    resolve_mcp_targets,
    write_ownership,
)
from vaultspec_core.core.mcps_native import normalized_sources
from vaultspec_core.core.mcps_trust import McpApproval, approved_sources, grant
from vaultspec_core.core.types import McpTarget, SyncResult

from ._mcp_topology import (
    NodeSnapshot,
    SnapshotKind,
    file_snapshot,
    restore_file_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from vaultspec_core.core.enums import InstallMode
    from vaultspec_core.core.mcps_ownership import OwnershipState

#: The variables the platform consults for the user's home directory: the first
#: on Windows, the second everywhere else.
_HOME_VARIABLES = ("USERPROFILE", "HOME")


@dataclass(frozen=True, slots=True)
class HostProjection:
    """One projection root and the authority root whose host state it borrows."""

    #: The real workspace root whose ownership and approvals govern.
    authority: Path
    #: The projection root core is run against.
    work: Path
    #: The core home holding the authority's state, as it was before any
    #: override. Read from, never written.
    authority_home: Path
    #: The throwaway core home the projection runs under.
    home: Path
    #: Where the projection's ownership sidecar lives inside ``home``.
    work_ownership: Path


@dataclass(frozen=True, slots=True)
class LaunchToEnroll:
    """One MCP launch a sync of *work* would enroll, keyed both ways."""

    target: McpTarget
    authority_target: McpTarget
    name: str
    path: Path
    authority_path: Path
    config: dict[str, object]
    digest: str


@contextmanager
def _user_home(home: Path) -> Generator[None]:
    """Make *home* the user's home directory for the platform, then put it back."""
    saved = {name: os.environ.get(name) for name in _HOME_VARIABLES}
    for name in _HOME_VARIABLES:
        os.environ[name] = str(home)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _serialized(state: dict[str, object]) -> bytes:
    """Return *state* in the exact bytes core's own writer produces."""
    with tempfile.TemporaryDirectory(prefix="vaultspec-rag-ownership-") as raw:
        path = Path(raw) / "ownership.json"
        write_ownership(path, cast("OwnershipState", cast("object", state)))
        return path.read_bytes()


def _rebased_record(
    record: dict[str, object], source: Path, destination: Path
) -> tuple[str, dict[str, object]] | None:
    """Return one ownership record moved from *source* to *destination*."""
    provider, scope, raw_path = (
        record.get(field) for field in ("provider", "scope", "path")
    )
    if not (
        isinstance(provider, str)
        and isinstance(scope, str)
        and isinstance(raw_path, str)
    ):
        return None
    try:
        relative = Path(raw_path).relative_to(source)
        moved = McpTarget(
            Tool(provider),
            McpScope(scope),
            destination / relative,
            McpTargetFormat.JSON,
        )
    except ValueError:
        return None
    return ownership_target_key(moved), {**record, "path": str(moved.path.resolve())}


def rebase_ownership(payload: bytes, source: Path, destination: Path) -> bytes:
    """Return the ownership sidecar *payload* with *source* records at *destination*.

    Bytes core would refuse to read pass through untouched, so a projection
    fails on them exactly the way the real root does.
    """
    try:
        parsed = cast("object", json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, ValueError):
        return payload
    if not isinstance(parsed, dict):
        return payload
    state = cast("dict[str, object]", parsed)
    targets = state.get("targets")
    if not isinstance(targets, dict):
        return payload
    moved_targets: dict[str, object] = {}
    changed = False
    for key, raw_record in cast("dict[str, object]", targets).items():
        rebased = (
            _rebased_record(
                cast("dict[str, object]", raw_record),
                source.resolve(),
                destination.resolve(),
            )
            if isinstance(raw_record, dict)
            else None
        )
        if rebased is None:
            moved_targets[key] = raw_record
            continue
        moved_targets[rebased[0]] = rebased[1]
        changed = True
    if not changed:
        return payload
    return _serialized({**state, "targets": moved_targets})


@contextmanager
def projected_core_home(authority: Path, work: Path) -> Generator[HostProjection]:
    """Run core against *work* as though it were *authority*, under a private home.

    The operator's home is untouched: the authority's ownership is copied out
    of it into a temporary home, re-keyed to *work*, and every core call made
    inside the block reads and writes that copy.
    """
    authority_home = core_home_layout().root
    authority_ownership = ownership_path(authority, McpScope.PROJECT)
    with (
        tempfile.TemporaryDirectory(prefix="vaultspec-rag-core-home-") as raw,
        _user_home(Path(raw)),
    ):
        work_ownership = ownership_path(work, McpScope.PROJECT)
        original = file_snapshot(authority_ownership)
        if original.kind is SnapshotKind.FILE and isinstance(original.payload, bytes):
            restore_file_snapshot(
                work_ownership,
                NodeSnapshot(
                    SnapshotKind.FILE,
                    rebase_ownership(original.payload, authority, work),
                    mode=original.mode,
                ),
            )
        yield HostProjection(
            authority=authority,
            work=work,
            authority_home=authority_home,
            home=core_home_layout().root,
            work_ownership=work_ownership,
        )


def expected_authority_ownership(host: HostProjection) -> NodeSnapshot:
    """Return the ownership sidecar a real run would leave, as the projection did.

    Core's writes into the projection's home, translated back to the authority
    root, are the exact bytes the real root is expected to hold afterwards.
    """
    written = file_snapshot(host.work_ownership)
    if written.kind is SnapshotKind.FILE and isinstance(written.payload, bytes):
        return NodeSnapshot(
            SnapshotKind.FILE,
            rebase_ownership(written.payload, host.work, host.authority),
            mode=written.mode,
        )
    return written


def launches_to_enroll(
    authority: Path,
    work: Path,
    *,
    mode: InstallMode,
    enrolled: Iterable[Tool] | None,
) -> list[LaunchToEnroll]:
    """List every launch a sync of *work* would enroll, with *authority*'s paths.

    Must run inside a core context of its own: resolving the targets
    initialises one for *work*.
    """
    targets = resolve_mcp_targets(
        "all", scope=McpScope.PROJECT, target_dir=work, enrolled=enrolled
    )
    digests: dict[Path, str] = {}
    sources = collect_mcp_servers(mode=mode, target=work, digests=digests)
    launches: list[LaunchToEnroll] = []
    for target in targets:
        authority_target = replace(
            target, path=authority / target.path.relative_to(work)
        )
        for name, (path, config) in normalized_sources(
            sources, target, SyncResult()
        ).items():
            launches.append(
                LaunchToEnroll(
                    target=target,
                    authority_target=authority_target,
                    name=name,
                    path=path,
                    authority_path=authority / path.relative_to(work),
                    config=config,
                    digest=digests[path],
                )
            )
    return launches


def approved_launches(
    launches: Iterable[LaunchToEnroll],
    authority: Path,
    *,
    home: Path | None = None,
) -> list[LaunchToEnroll]:
    """Return the *launches* the operator already approved for *authority*.

    Consent is asked of core itself, at the authority's own paths and in the
    operator's home (or *home*), so a launch whose definition or rendered
    command changed since it was approved is not among them.
    """
    launches = list(launches)
    approved: list[LaunchToEnroll] = []
    for target in {launch.target for launch in launches}:
        group = [launch for launch in launches if launch.target == target]
        names = approved_sources(
            {launch.name: (launch.authority_path, launch.config) for launch in group},
            {launch.authority_path: launch.digest for launch in group},
            authority,
            group[0].authority_target,
            SyncResult(),
            home=home,
        )
        approved.extend(launch for launch in group if launch.name in names)
    return approved


def carry_consent(
    host: HostProjection,
    *,
    mode: InstallMode,
    enrolled: Iterable[Tool] | None,
) -> None:
    """Approve in the projection exactly the launches approved for the authority.

    Consent is asked of core against the authority root, in the operator's own
    home, so a launch the operator never approved stays unapproved in the
    projection and is skipped there as it will be for real.
    """
    approvals = [
        McpApproval.capture(
            host.work,
            launch.target,
            launch.name,
            launch.path,
            launch.config,
            launch.digest,
        )
        for launch in approved_launches(
            launches_to_enroll(host.authority, host.work, mode=mode, enrolled=enrolled),
            host.authority,
            home=host.authority_home,
        )
    ]
    if approvals:
        grant(approvals, home=host.home)
