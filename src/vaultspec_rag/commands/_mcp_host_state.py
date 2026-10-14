"""Core's machine-global MCP state, made visible to a projection of a workspace.

Core keeps two records outside the repository, in the operator's home, both
keyed by the workspace root: which native MCP entries it owns, and which
executable launches the operator approved. A preview or a replay runs core
against a projection at a different root, so core would plan it as a workspace
that owns nothing and approved nothing, and the plan would never match what the
real root does.

``projected_core_home`` gives such a run a throwaway home, carries the
authority root's ownership into it re-keyed to the projection, and
``carry_host_state`` carries over exactly the launches the operator already
approved for the authority root, with the ownership of any native config the
projection holds under another name than the authority's. The operator's own
home is only ever read by a projection.

An install also holds a linked native config as a regular copy while it
syncs, and core keys both records by the resolved path of that config, so
``OwnershipCarry`` moves the ownership to the copy for the run and back to
where the config really lives once it is over.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from vaultspec_core.core.enums import McpScope
from vaultspec_core.core.helpers import atomic_write_bytes
from vaultspec_core.core.home import core_home_layout
from vaultspec_core.core.mcps import (
    collect_mcp_servers,
    ownership_path,
    resolve_mcp_targets,
    write_ownership,
)
from vaultspec_core.core.mcps_native import normalized_sources
from vaultspec_core.core.mcps_trust import McpApproval, approved_sources, grant
from vaultspec_core.core.types import SyncResult

from ._mcp_topology import (
    NodeSnapshot,
    SnapshotKind,
    file_snapshot,
    restore_file_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Mapping

    from vaultspec_core.core.enums import InstallMode, Tool
    from vaultspec_core.core.mcps_ownership import OwnershipState
    from vaultspec_core.core.types import McpTarget

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


def _destination(
    record: object, relocate: Callable[[Path], Path | None]
) -> tuple[str, Path] | None:
    """Return the key and path one ownership record moves to, if it moves."""
    if not isinstance(record, dict):
        return None
    provider, scope, raw_path = (
        cast("dict[str, object]", record).get(name)
        for name in ("provider", "scope", "path")
    )
    if not (
        isinstance(provider, str)
        and isinstance(scope, str)
        and isinstance(raw_path, str)
    ):
        return None
    destination = relocate(Path(raw_path))
    if destination is None or destination == Path(raw_path):
        return None
    return f"{provider}:{scope}:{destination}", destination


def _moved(payload: bytes, relocate: Callable[[Path], Path | None]) -> bytes:
    """Return the ownership sidecar *payload* with records moved to new paths.

    *relocate* names where the record at a path goes, or ``None`` to leave it.
    A record keeps its provider, scope and fingerprints, its key follows its
    path, and one moved onto another record's path replaces it. Bytes core would
    refuse to read pass through untouched, so a projection fails on them
    exactly the way the real root does.
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
    kept: dict[str, object] = {}
    moved: dict[str, object] = {}
    for key, record in cast("dict[str, object]", targets).items():
        destination = _destination(record, relocate)
        if destination is None:
            kept[key] = record
            continue
        new_key, path = destination
        moved[new_key] = {**cast("dict[str, object]", record), "path": str(path)}
    if not moved:
        return payload
    return _serialized({**state, "targets": {**kept, **moved}})


def _rebased(path: Path, source: Path, destination: Path) -> Path | None:
    """Return where *path*, which lies under *source*, lies under *destination*.

    The result is resolved, as core keys it: a config that is a link under
    *destination* is keyed by the file it really is.
    """
    try:
        return (destination / path.relative_to(source)).resolve()
    except ValueError:
        return None


def rebase_ownership(payload: bytes, source: Path, destination: Path) -> bytes:
    """Return the ownership sidecar *payload* with *source* records at *destination*."""
    root, moved_root = source.resolve(), destination.resolve()
    return _moved(payload, lambda path: _rebased(path, root, moved_root))


def _move_in(sidecar: Path, moves: Mapping[Path, Path]) -> None:
    """Move the ownership records at the *moves* keys to their values in *sidecar*.

    The file is replaced in one atomic step, as core replaces it, so a failure
    leaves the bytes that were there: this file is the operator's own record.
    """
    current = file_snapshot(sidecar)
    if current.kind is not SnapshotKind.FILE or not isinstance(current.payload, bytes):
        return
    moved = _moved(current.payload, moves.get)
    if moved != current.payload:
        atomic_write_bytes(sidecar, moved)


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
    root, are the exact bytes the real root is expected to hold afterwards. A
    config that is a link in the authority is keyed by its real location, which
    is where an install leaves its ownership once its links are back.
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


def carry_host_state(
    host: HostProjection,
    *,
    mode: InstallMode,
    enrolled: Iterable[Tool] | None,
) -> None:
    """Make the projection see what the operator already decided for the authority.

    Approvals are asked of core against the authority root, in the operator's
    own home, so a launch the operator never approved stays unapproved in the
    projection and is skipped there as it will be for real. Ownership is
    already there under the authority's paths; where a config is a link in the
    authority and a regular file in the projection, it is moved to the
    projection's file, the one place core will look.
    """
    launches = launches_to_enroll(
        host.authority, host.work, mode=mode, enrolled=enrolled
    )
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
            launches, host.authority, home=host.authority_home
        )
    ]
    if approvals:
        grant(approvals, home=host.home)
    authority, work = host.authority.resolve(), host.work.resolve()
    moves: dict[Path, Path] = {}
    for launch in launches:
        real = _rebased(launch.authority_target.path.resolve(), authority, work)
        if real is not None:
            moves[real] = launch.target.path.resolve()
    _move_in(host.work_ownership, moves)


@dataclass(frozen=True, slots=True)
class _HeldOwnership:
    """The sidecar around the move to the copies, and the way back."""

    sidecar: Path
    before: NodeSnapshot
    after: NodeSnapshot
    back: dict[Path, Path]


@dataclass(slots=True)
class OwnershipCarry:
    """Where core keeps the ownership of native configs an install swaps for copies.

    Core keys ownership by the resolved path of the native config. While an
    install holds a linked config as a regular copy, core syncs, and records
    what it owns, at the copy's path, and no later sync looks there: it asks
    about the link's target. ``hold`` moves the ownership found at each real
    location to its copy for the run, so the install does not meet its own
    entry as somebody else's, and ``release`` moves what the run left at the
    copy back to the real location, so a later sync finds it owned.
    """

    root: Path
    #: Each native config the run syncs, as the workspace names it, and where it
    #: really lives.
    real: dict[Path, Path] = field(default_factory=dict)
    held: _HeldOwnership | None = field(default=None, init=False)

    def capture(self, launches: Iterable[LaunchToEnroll]) -> None:
        """Note where each config of *launches* really lives, before any swap."""
        self.real = {
            launch.authority_target.path: launch.authority_target.path.resolve()
            for launch in launches
        }

    def hold(self) -> None:
        """Move the ownership at each real location to the copy that stands in for it.

        Writes nothing when no config is a copy of a link.
        """
        copies = {
            real: copy
            for config, real in self.real.items()
            if (copy := config.resolve()) != real
        }
        if not copies:
            return
        sidecar = ownership_path(self.root, McpScope.PROJECT)
        before = file_snapshot(sidecar)
        _move_in(sidecar, copies)
        self.held = _HeldOwnership(
            sidecar,
            before,
            file_snapshot(sidecar),
            {copy: real for real, copy in copies.items()},
        )

    def release(self) -> None:
        """Move the ownership at each copy back to the real location it stands for.

        A sidecar the run never touched goes back exactly as it was found.
        """
        held, self.held = self.held, None
        if held is None:
            return
        if file_snapshot(held.sidecar) != held.after:
            _move_in(held.sidecar, held.back)
        elif isinstance(held.before.payload, bytes) and held.before != held.after:
            atomic_write_bytes(held.sidecar, held.before.payload)
