"""Topology-safe filesystem boundary for required project MCP nodes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from contextvars import Context
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import cast

from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
    init_paths,
)

from .._atomic_write import replace_atomically
from .._workspace_layout import (
    MCP_OWNERSHIP_MANIFEST,
    PROVIDERS_MANIFEST,
    VAULT_DATA_DIR,
    WORKSPACE_DIR,
    WORKSPACE_MANIFEST,
    WORKSPACE_MCPS,
    WORKSPACE_RULES,
    workspace_directories,
)
from ..builtins import list_builtins


class SnapshotKind(Enum):
    ABSENT = auto()
    FILE = auto()
    SYMLINK = auto()
    DIRECTORY = auto()
    JUNCTION = auto()


@dataclass(frozen=True)
class NodeSnapshot:
    kind: SnapshotKind
    payload: bytes | str | None = None
    target_is_directory: bool = False
    mode: int | None = None


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    link_count: int


@dataclass(frozen=True)
class _RequiredLink:
    path: Path
    link: NodeSnapshot
    target: Path
    target_node: NodeSnapshot
    target_identity: _FileIdentity


@dataclass(frozen=True)
class _OwnedNode:
    snapshot: NodeSnapshot
    identity: _FileIdentity | None


@dataclass(frozen=True)
class LifecycleTransactionInventory:
    """Every workspace node the RAG install lifecycle may mutate."""

    files: tuple[Path, ...]
    containers: tuple[Path, ...]
    managed_trees: tuple[Path, ...]

    def collision(self, path: Path) -> Path | None:
        """Return the lifecycle authority that aliases *path*, if any."""
        key = _normalized(path)
        for candidate in (*self.files, *self.containers):
            if _normalized(candidate) == key:
                return candidate
        for tree in self.managed_trees:
            if _is_within(tree, path):
                return tree
        return None


@dataclass
class RequiredMcpTopology:
    """Validated required-node topology captured before lifecycle mutation."""

    root: Path
    nodes: tuple[tuple[Path, NodeSnapshot], ...]
    identities: tuple[tuple[Path, _FileIdentity], ...]
    links: tuple[_RequiredLink, ...]
    mcp_sources: tuple[Path, ...]
    _owned_nodes: dict[str, list[_OwnedNode]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def disenrollment_links(self) -> tuple[_RequiredLink, ...]:
        """Return links whose own logical node can be changed by RAG removal."""
        extra_sources = {
            _normalized(path)
            for path in self.mcp_sources
            if path.name != _RAG_MCP_SOURCE.name
        }
        return tuple(
            linked
            for linked in self.links
            if _normalized(linked.path) not in extra_sources
        )

    def projection_snapshot(self, path: Path) -> NodeSnapshot:
        """Return effective regular bytes for a validated required link."""
        normalized = _normalized(path)
        for linked in self.links:
            if _normalized(linked.path) == normalized:
                return linked.target_node
        return file_snapshot(path)

    def materialize(self) -> None:
        """Replace required links temporarily with captured local regular nodes."""
        # Validate the complete capture before the first write.  In particular,
        # a detected operator race must never trigger a stale-snapshot rollback
        # when this transaction has not changed anything yet.
        for path, snapshot in self.nodes:
            _require_unchanged(path, snapshot)
        for path, identity in self.identities:
            _require_identity(path, identity)
        for linked in self.links:
            _require_unchanged(linked.target, linked.target_node)
            _require_identity(linked.target, linked.target_identity)
        current_sources = {
            _normalized(path) for path in _discover_mcp_sources(self.root)
        }
        captured_sources = {
            _normalized(source)
            for source in self.mcp_sources
            if source.exists() or source.is_symlink()
        }
        if current_sources != captured_sources:
            raise OSError(
                "required MCP topology changed during transaction: canonical source set"
            )

        try:
            for linked in self.links:
                payload = _regular_payload(linked.target_node, linked.target)
                _remove_transaction_node(linked.path)
                self._record_owned_node(
                    linked.path,
                    snapshot=NodeSnapshot(SnapshotKind.ABSENT),
                )
                _restore_regular_file(
                    linked.path,
                    payload,
                    linked.target_node.mode,
                )
                self._record_owned_node(linked.path)
        except Exception:
            rollback = self.restore()
            if rollback:
                raise OSError(
                    "required MCP topology materialization failed and rollback "
                    f"was incomplete: {'; '.join(rollback)}"
                ) from None
            raise

    def populate_projection(self, destination: Path) -> None:
        """Recreate captured effective required state under a temporary root."""
        destination.mkdir(parents=True, exist_ok=True)
        linked = {_normalized(item.path): item for item in self.links}
        for path, snapshot in self.nodes:
            projected = destination / path.relative_to(self.root)
            required_link = linked.get(_normalized(path))
            effective = (
                required_link.target_node if required_link is not None else snapshot
            )
            restore_file_snapshot(projected, effective)

    def capture_expected_projection(self, projection: Path) -> None:
        """Journal exact replay output as the only transaction-owned post-state."""
        self._owned_nodes.clear()
        for path, original in self.nodes:
            projected = projection / path.relative_to(self.root)
            expected = file_snapshot(projected)
            if path == self.root / MCP_OWNERSHIP_MANIFEST:
                expected = _rebase_ownership_snapshot(
                    expected,
                    projection=projection,
                    destination=self.root,
                )
            if expected != original:
                self._owned_nodes.setdefault(_normalized(path), []).append(
                    _OwnedNode(expected, None)
                )

    def finish(self, *, commit: bool) -> list[str]:
        """Publish logical bytes through captured targets or restore on failure."""
        if not commit:
            return self.restore()
        published: list[tuple[_RequiredLink, NodeSnapshot, _FileIdentity]] = []
        try:
            final_nodes: list[tuple[_RequiredLink, NodeSnapshot]] = []
            for linked in self.links:
                _require_unchanged(linked.target, linked.target_node)
                _require_identity(linked.target, linked.target_identity)
                final = file_snapshot(linked.path)
                if final.kind is not SnapshotKind.FILE:
                    raise OSError(
                        "required linked MCP node cannot be removed while preserving "
                        f"its topology: {linked.path}"
                    )
                final_nodes.append((linked, final))
            for linked, final in final_nodes:
                final_payload = _regular_payload(final, linked.path)
                original_payload = _regular_payload(
                    linked.target_node,
                    linked.target,
                )
                if (
                    final_payload != original_payload
                    or final.mode != linked.target_node.mode
                ):
                    _restore_regular_file(
                        linked.target,
                        final_payload,
                        linked.target_node.mode,
                    )
                    published.append(
                        (
                            linked,
                            file_snapshot(linked.target),
                            _regular_identity(linked.target),
                        )
                    )
                restore_file_snapshot(linked.path, linked.link)
        except Exception as exc:
            rollback = _rollback_published_targets(published)
            rollback.extend(self.restore())
            detail = f"required MCP topology commit failed: {exc}"
            if rollback:
                detail += f"; rollback failed: {'; '.join(rollback)}"
            return [detail]
        return []

    def restore(self) -> list[str]:
        """CAS-restore transaction-owned nodes without overwriting newer data."""
        errors: list[str] = []
        for path, original in self.nodes:
            current = file_snapshot(path)
            if current == original:
                continue
            owned = self._owned_nodes.get(_normalized(path), [])
            if not any(_matches_owned_node(path, current, item) for item in owned):
                errors.append(
                    f"{path}: concurrent update preserved; transaction node was "
                    "not rolled back"
                )
                continue
            try:
                restore_file_snapshot(path, original)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        return errors

    def _record_owned_node(
        self,
        path: Path,
        *,
        snapshot: NodeSnapshot | None = None,
    ) -> None:
        key = _normalized(path)
        captured = snapshot or file_snapshot(path)
        identity = (
            _regular_identity(path) if captured.kind is SnapshotKind.FILE else None
        )
        self._owned_nodes.setdefault(key, []).append(_OwnedNode(captured, identity))


_REQUIRED_MCP_STATIC_RELATIVE_PATHS = (
    Path(".mcp.json"),
    Path(".codex") / "config.toml",
    MCP_OWNERSHIP_MANIFEST,
    PROVIDERS_MANIFEST,
    WORKSPACE_MANIFEST,
    Path("pyproject.toml"),
)
_RAG_MCP_SOURCE = WORKSPACE_MCPS / "vaultspec-rag.builtin.json"

_WORKSPACE_CONTAINERS = workspace_directories()

# Core's provider hook writer owns these native files and sidecars.  Keep the
# paths in the same lifecycle inventory as Core-derived ToolConfig paths so a
# required link can never redirect MCP publication into a later hook sync.
_PROVIDER_HOOK_FILES = (
    Path(".claude") / "settings.json",
    Path(".claude") / ".vaultspec-hooks.json",
    Path(".gemini") / "settings.json",
    Path(".gemini") / ".vaultspec-hooks.json",
    Path(".codex") / "hooks.json",
    Path(".codex") / ".vaultspec-hooks.json",
    Path(".agents") / "hooks.json",
)

_CORE_ROOT_FILES = (
    Path(".gitignore"),
    Path(".gitattributes"),
    Path(".pre-commit-config.yaml"),
)

_PROVIDER_FILE_ATTRIBUTES = (
    "config_file",
    "native_config_file",
    "rule_ref_config_file",
    "system_file",
    "mcp_config_file",
)

_PROVIDER_TREE_ATTRIBUTES = (
    "rules_dir",
    "skills_dir",
    "agents_dir",
    "workflows_dir",
)


def lifecycle_transaction_inventory(target: Path) -> LifecycleTransactionInventory:
    """Build the single path authority shared by every MCP lifecycle phase.

    File entries cover direct writes and advisory locks.  Managed trees cover
    provider resource directories that Core may add to or prune, plus optional
    install/uninstall trees such as ``.venv`` and ``.vault/data``.  Provider
    paths come from Core's current ``ToolConfig`` mapping in an isolated
    projection so this inspection neither mutates the workspace nor replaces a
    caller's active Core context.
    """
    root = Path(os.path.abspath(target))
    files = {
        *required_mcp_paths(root),
        root / "uv.lock",
        *(root / relative for relative in _CORE_ROOT_FILES),
        *(root / WORKSPACE_DIR / relative for relative in list_builtins()),
        *(root / relative for relative in _PROVIDER_HOOK_FILES),
    }
    containers = {root / relative for relative in _WORKSPACE_CONTAINERS}
    managed_trees = {
        root / VAULT_DATA_DIR,
        root / WORKSPACE_RULES,
        root / ".venv",
    }

    provider_files, provider_containers, provider_trees = _provider_paths(root)
    files.update(provider_files)
    containers.update(provider_containers)
    managed_trees.update(provider_trees)

    locks = {path.with_suffix(path.suffix + ".lock") for path in files}
    files.update(locks)
    return LifecycleTransactionInventory(
        files=tuple(sorted(files, key=_normalized)),
        containers=tuple(sorted(containers, key=_normalized)),
        managed_trees=tuple(sorted(managed_trees, key=_normalized)),
    )


def _provider_paths(root: Path) -> tuple[set[Path], set[Path], set[Path]]:
    """Resolve provider outputs from Core without touching *root*."""
    with tempfile.TemporaryDirectory(prefix="vaultspec-rag-provider-paths-") as raw:
        projection = Path(raw) / "workspace"
        (projection / WORKSPACE_DIR).mkdir(parents=True)
        context = Context().run(init_paths, projection)

        files: set[Path] = set()
        containers: set[Path] = set()
        managed_trees: set[Path] = set()
        for config in context.tool_configs.values():
            for attribute in _PROVIDER_FILE_ATTRIBUTES:
                projected = cast("Path | None", getattr(config, attribute))
                if projected is None:
                    continue
                translated = _translate_projection_path(projected, projection, root)
                files.add(translated)
                containers.add(translated.parent)
            for attribute in _PROVIDER_TREE_ATTRIBUTES:
                projected = cast("Path | None", getattr(config, attribute))
                if projected is None:
                    continue
                translated = _translate_projection_path(projected, projection, root)
                containers.add(translated)
                managed_trees.add(translated)
        return files, containers, managed_trees


def _translate_projection_path(path: Path, projection: Path, root: Path) -> Path:
    """Map one Core-derived projection path back into the real workspace."""
    return root / path.relative_to(projection)


def _rebase_ownership_snapshot(
    snapshot: NodeSnapshot,
    *,
    projection: Path,
    destination: Path,
) -> NodeSnapshot:
    """Translate Core's replay-root ownership paths to real workspace paths."""
    if snapshot.kind is not SnapshotKind.FILE or not isinstance(
        snapshot.payload, bytes
    ):
        return snapshot
    try:
        parsed = cast("object", json.loads(snapshot.payload.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return snapshot
    if not isinstance(parsed, dict):
        return snapshot
    state = cast("dict[str, object]", parsed)
    targets = state.get("targets")
    if not isinstance(targets, dict):
        return snapshot
    target_records = cast("dict[str, object]", targets)

    projection_root = projection.resolve()
    destination_root = destination.resolve()
    changed = False
    for raw_record in target_records.values():
        if not isinstance(raw_record, dict):
            continue
        record = cast("dict[str, object]", raw_record)
        raw_path = record.get("path")
        if not isinstance(raw_path, str):
            continue
        try:
            relative = Path(raw_path).relative_to(projection_root)
        except ValueError:
            continue
        record["path"] = str((destination_root / relative).resolve())
        changed = True
    if not changed:
        return snapshot
    payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return NodeSnapshot(
        kind=SnapshotKind.FILE,
        payload=payload,
        mode=snapshot.mode,
    )


def required_mcp_paths(target: Path) -> tuple[Path, ...]:
    """Return native state plus every canonical source Core will reconcile."""
    root = Path(os.path.abspath(target))
    static = tuple(root / relative for relative in _REQUIRED_MCP_STATIC_RELATIVE_PATHS)
    sources = _discover_mcp_sources(root)
    rag_source = root / _RAG_MCP_SOURCE
    return (*static, *dict.fromkeys((rag_source, *sources)))


def required_mcp_transaction_paths(target: Path) -> tuple[Path, ...]:
    """Return required content nodes followed by their advisory lock nodes."""
    required = required_mcp_paths(target)
    return (
        *required,
        *(path.with_suffix(path.suffix + ".lock") for path in required),
    )


def inspect_required_mcp_topology(target: Path) -> RequiredMcpTopology:
    """Validate and capture required nodes without following unsafe topology."""
    root = Path(os.path.abspath(target))
    required = required_mcp_paths(root)
    lifecycle = lifecycle_transaction_inventory(root)
    transaction_paths = (
        *required,
        *(path.with_suffix(path.suffix + ".lock") for path in required),
    )
    nodes: list[tuple[Path, NodeSnapshot]] = []
    identities: list[tuple[Path, _FileIdentity]] = []
    captured: list[_RequiredLink] = []
    seen_targets: dict[str, Path] = {}

    for path in required:
        snapshot, identity, linked = _capture_required_node(
            root,
            path,
            lifecycle,
            seen_targets,
        )
        nodes.append((path, snapshot))
        if identity is not None:
            identities.append((path, identity))
        if linked is not None:
            captured.append(linked)
    for lock_path in transaction_paths[len(required) :]:
        _validate_plain_parents(root, lock_path)
        lock_snapshot = file_snapshot(lock_path)
        if lock_snapshot.kind not in {
            SnapshotKind.ABSENT,
            SnapshotKind.FILE,
            SnapshotKind.DIRECTORY,
        }:
            raise OSError(
                f"unsafe required MCP topology at {lock_path}: lock nodes cannot "
                f"be {lock_snapshot.kind.name.lower()}"
            )
        nodes.append((lock_path, lock_snapshot))
        if lock_snapshot.kind is SnapshotKind.FILE:
            identity = _regular_identity(lock_path)
            _reject_hard_links(lock_path, identity)
            identities.append((lock_path, identity))
    return RequiredMcpTopology(
        root=root,
        nodes=tuple(nodes),
        identities=tuple(identities),
        links=tuple(captured),
        mcp_sources=tuple(
            path for path in required if path.parent == root / WORKSPACE_MCPS
        ),
    )


def _capture_required_node(
    root: Path,
    path: Path,
    lifecycle: LifecycleTransactionInventory,
    seen_targets: dict[str, Path],
) -> tuple[NodeSnapshot, _FileIdentity | None, _RequiredLink | None]:
    _validate_plain_parents(root, path)
    snapshot = file_snapshot(path)
    if snapshot.kind is SnapshotKind.FILE:
        identity = _regular_identity(path)
        _reject_hard_links(path, identity)
        return snapshot, identity, None
    if snapshot.kind is SnapshotKind.ABSENT:
        return snapshot, None, None
    if snapshot.kind is not SnapshotKind.SYMLINK:
        raise OSError(
            f"unsafe required MCP topology at {path}: expected a regular file "
            f"or absent node, found {snapshot.kind.name.lower()}"
        )
    return (
        snapshot,
        None,
        _capture_required_link(
            root,
            path,
            snapshot,
            lifecycle,
            seen_targets,
        ),
    )


def _capture_required_link(
    root: Path,
    path: Path,
    snapshot: NodeSnapshot,
    lifecycle: LifecycleTransactionInventory,
    seen_targets: dict[str, Path],
) -> _RequiredLink:
    if not isinstance(snapshot.payload, str):
        raise TypeError(f"required MCP link has no target text: {path}")
    raw_target = Path(snapshot.payload)
    if raw_target.is_absolute():
        raise OSError(
            f"unsafe required MCP topology at {path}: absolute links are not followed"
        )
    linked_target = Path(os.path.abspath(path.parent / raw_target))
    if not _is_within(root, linked_target):
        raise OSError(
            f"unsafe required MCP topology at {path}: relative link escapes the project"
        )
    _validate_plain_parents(root, linked_target)
    target_snapshot = file_snapshot(linked_target)
    if target_snapshot.kind is not SnapshotKind.FILE:
        raise OSError(
            f"unsafe required MCP topology at {path}: link target must be one "
            f"existing regular file, found {target_snapshot.kind.name.lower()}"
        )
    target_identity = _regular_identity(linked_target)
    _reject_hard_links(linked_target, target_identity)
    target_key = _normalized(linked_target)
    collision = lifecycle.collision(linked_target)
    if collision is not None:
        required_keys = {
            _normalized(candidate) for candidate in required_mcp_transaction_paths(root)
        }
        if _normalized(collision) in required_keys:
            raise OSError(
                f"unsafe required MCP topology at {path}: link target overlaps a "
                "required MCP node"
            )
        raise OSError(
            f"unsafe required MCP topology at {path}: link target overlaps a "
            f"lifecycle output at {collision}"
        )
    if prior := seen_targets.get(target_key):
        raise OSError(
            f"unsafe required MCP topology at {path}: link target aliases "
            f"required node {prior}"
        )
    seen_targets[target_key] = path
    return _RequiredLink(
        path=path,
        link=snapshot,
        target=linked_target,
        target_node=target_snapshot,
        target_identity=target_identity,
    )


def _discover_mcp_sources(root: Path) -> tuple[Path, ...]:
    """Enumerate the exact direct ``*.json`` source set used by Core."""
    directory = root / WORKSPACE_MCPS
    _validate_plain_parents(root, directory / "source.json")
    snapshot = file_snapshot(directory)
    if snapshot.kind is SnapshotKind.ABSENT:
        return ()
    if snapshot.kind is not SnapshotKind.DIRECTORY:
        raise OSError(
            f"unsafe required MCP topology at {directory}: canonical source "
            f"container is {snapshot.kind.name.lower()}"
        )
    with os.scandir(directory) as entries:
        names = sorted(
            entry.name for entry in entries if Path(entry.name).match("*.json")
        )
    return tuple(directory / name for name in names)


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_within(root: Path, path: Path) -> bool:
    try:
        return os.path.commonpath(
            (_normalized(root), _normalized(path))
        ) == _normalized(root)
    except ValueError:
        return False


def _validate_plain_parents(root: Path, path: Path) -> None:
    """Reject linked, junction, or non-directory containers below the root."""
    relative = Path(os.path.relpath(path, root))
    current = root
    for part in relative.parts[:-1]:
        current /= part
        snapshot = file_snapshot(current)
        if snapshot.kind is SnapshotKind.ABSENT:
            return
        if snapshot.kind is not SnapshotKind.DIRECTORY:
            raise OSError(
                f"unsafe required MCP topology at {path}: container {current} is "
                f"{snapshot.kind.name.lower()}"
            )


def _regular_payload(snapshot: NodeSnapshot, path: Path) -> bytes:
    if snapshot.kind is not SnapshotKind.FILE or not isinstance(
        snapshot.payload, bytes
    ):
        raise TypeError(f"regular-file snapshot has no byte payload: {path}")
    return snapshot.payload


def _require_unchanged(path: Path, expected: NodeSnapshot) -> None:
    if file_snapshot(path) != expected:
        raise OSError(f"required MCP topology changed during transaction: {path}")


def _regular_identity(path: Path) -> _FileIdentity:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"required MCP node is no longer a regular file: {path}")
    return _FileIdentity(
        device=int(metadata.st_dev),
        inode=int(metadata.st_ino),
        link_count=int(metadata.st_nlink),
    )


def _require_identity(path: Path, expected: _FileIdentity) -> None:
    if _regular_identity(path) != expected:
        raise OSError(f"required MCP file identity changed during transaction: {path}")


def _reject_hard_links(path: Path, identity: _FileIdentity) -> None:
    if identity.link_count > 1:
        raise OSError(
            f"unsafe required MCP topology at {path}: regular file has "
            f"{identity.link_count} hard links and cannot be atomically updated "
            "without changing alias topology"
        )


def _matches_owned_node(
    path: Path,
    current: NodeSnapshot,
    owned: _OwnedNode,
) -> bool:
    if current != owned.snapshot:
        return False
    if owned.identity is None:
        return True
    try:
        return _regular_identity(path) == owned.identity
    except OSError:
        return False


def _rollback_published_targets(
    published: list[tuple[_RequiredLink, NodeSnapshot, _FileIdentity]],
) -> list[str]:
    """CAS-restore targets written by this transaction, preserving newer data."""
    errors: list[str] = []
    for linked, written_snapshot, written_identity in reversed(published):
        try:
            if (
                file_snapshot(linked.target) != written_snapshot
                or _regular_identity(linked.target) != written_identity
            ):
                errors.append(
                    f"{linked.target}: concurrent update preserved; transaction "
                    "target was not rolled back"
                )
                continue
            restore_file_snapshot(linked.target, linked.target_node)
        except Exception as exc:
            errors.append(f"{linked.target}: {exc}")
    return errors


def file_snapshot(path: Path) -> NodeSnapshot:
    """Capture exact payload and filesystem-node topology without following links."""
    if path.is_junction():
        return NodeSnapshot(SnapshotKind.JUNCTION, os.readlink(path), True)
    if path.is_symlink():
        metadata = path.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        directory_link = path.is_dir() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0)
        )
        return NodeSnapshot(
            SnapshotKind.SYMLINK,
            os.readlink(path),
            directory_link,
        )
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return NodeSnapshot(SnapshotKind.ABSENT)
    if stat.S_ISREG(metadata.st_mode):
        return NodeSnapshot(
            SnapshotKind.FILE,
            path.read_bytes(),
            mode=stat.S_IMODE(metadata.st_mode),
        )
    if stat.S_ISDIR(metadata.st_mode):
        return NodeSnapshot(
            SnapshotKind.DIRECTORY,
            mode=stat.S_IMODE(metadata.st_mode),
        )
    raise OSError(f"unsupported transactional node type at {path}")


def _remove_transaction_node(path: Path) -> None:
    current = file_snapshot(path)
    if current.kind is SnapshotKind.ABSENT:
        return
    if current.kind in {SnapshotKind.DIRECTORY, SnapshotKind.JUNCTION}:
        path.rmdir()
        return
    path.unlink()


def _restore_regular_file(path: Path, payload: bytes, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.rollback-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode, follow_symlinks=False)
        replace_atomically(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _restore_junction(path: Path, target: str) -> None:
    if os.name != "nt":
        raise OSError(f"cannot restore Windows junction on {os.name}: {path}")
    powershell_target = target
    if target.startswith("\\\\?\\UNC\\"):
        powershell_target = "\\\\" + target[8:]
    elif target.startswith("\\\\?\\"):
        powershell_target = target[4:]
    environment = {
        **os.environ,
        "VAULTSPEC_JUNCTION_PATH": str(path),
        "VAULTSPEC_JUNCTION_TARGET": powershell_target,
    }
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "New-Item -ItemType Junction -Path $env:VAULTSPEC_JUNCTION_PATH "
        "-Target $env:VAULTSPEC_JUNCTION_TARGET | Out-Null"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        env=environment,
        timeout=15,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        printable = "".join(
            character if character.isprintable() else " " for character in stderr
        )
        diagnostic = " ".join(printable.split())[:400] or "no stderr"
        raise OSError(
            f"junction restore failed for {path} "
            f"(exit {completed.returncode}: {diagnostic})"
        )


def restore_file_snapshot(path: Path, snapshot: NodeSnapshot) -> None:
    """Restore one transactional node without following operator-owned links."""
    if file_snapshot(path) == snapshot:
        return
    _remove_transaction_node(path)
    if snapshot.kind is SnapshotKind.ABSENT:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.kind is SnapshotKind.FILE:
        _restore_regular_file(path, _regular_payload(snapshot, path), snapshot.mode)
        return
    if snapshot.kind is SnapshotKind.DIRECTORY:
        path.mkdir(mode=snapshot.mode or 0o777)
        if snapshot.mode is not None:
            path.chmod(snapshot.mode)
        return
    if not isinstance(snapshot.payload, str):
        raise TypeError(f"link snapshot has no target payload: {path}")
    if snapshot.kind is SnapshotKind.SYMLINK:
        os.symlink(
            snapshot.payload,
            path,
            target_is_directory=snapshot.target_is_directory,
        )
        return
    _restore_junction(path, snapshot.payload)


def rollback_file_snapshots(snapshots: dict[Path, NodeSnapshot]) -> list[str]:
    """Restore transaction snapshots and return any rollback diagnostics."""
    errors: list[str] = []
    for path, snapshot in snapshots.items():
        try:
            restore_file_snapshot(path, snapshot)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return errors
