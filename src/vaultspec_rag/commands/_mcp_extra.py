"""Reconcile the optional MCP extra at RAG's resolved dependency surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from tomlkit import TOMLDocument
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    InstallMode,
)

from ..torch_config._constants import (
    _TABLE_LIKE_TYPES,  # pyright: ignore[reportPrivateUsage]  # shared toml surface
    TableLike,
    tget,
)
from ..torch_config._inspect import load_pyproject
from ..torch_config._mutate import write_doc_preserving_shape
from ._mode import RAG_DISTRIBUTION_NAME

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT_DEPS = "[project].dependencies"
_OPTIONAL_PREFIX = "[project.optional-dependencies]."
_DEV_GROUP = "[dependency-groups].dev"
_UV_DEV = "[tool.uv].dev-dependencies"
_EXTRA = "mcp"


@dataclass(frozen=True)
class McpExtraOwnership:
    """The exact requirement edit RAG may later reverse."""

    location: str
    managed: str
    original: str | None
    created_surface: bool = False


@dataclass
class McpExtraReport:
    """Structured result for an MCP-extra reconciliation."""

    action: str = "skipped"
    location: str = ""
    conflicts: list[str] = field(default_factory=list)


def _as_table(value: object) -> TableLike | None:
    return value if isinstance(value, _TABLE_LIKE_TYPES) else None


def _requirement(value: object) -> Requirement | None:
    if not isinstance(value, str):
        return None
    try:
        return Requirement(value)
    except InvalidRequirement:
        return None


def _is_rag_requirement(value: object) -> bool:
    parsed = _requirement(value)
    return (
        parsed is not None and canonicalize_name(parsed.name) == RAG_DISTRIBUTION_NAME
    )


def _with_mcp_extra(value: str) -> str:
    parsed = Requirement(value)
    extras = sorted({*parsed.extras, _EXTRA})
    name = f"{parsed.name}[{','.join(extras)}]"
    rendered = f"{name} @ {parsed.url}" if parsed.url else f"{name}{parsed.specifier}"
    if parsed.marker:
        rendered = f"{rendered}; {parsed.marker}"
    return rendered


def _dependency_lists(doc: TOMLDocument) -> list[tuple[str, list[object]]]:
    found: list[tuple[str, list[object]]] = []
    project = _as_table(tget(doc, "project"))
    if project is not None:
        dependencies = tget(project, "dependencies")
        if isinstance(dependencies, list):
            found.append((_PROJECT_DEPS, cast("list[object]", dependencies)))
        optional = _as_table(tget(project, "optional-dependencies"))
        if optional is not None:
            for name, entries in optional.items():  # pyright: ignore[reportUnknownVariableType]
                if isinstance(entries, list):
                    found.append(
                        (
                            f"{_OPTIONAL_PREFIX}{name}",
                            cast("list[object]", entries),
                        )
                    )

    groups = _as_table(tget(doc, "dependency-groups"))
    if groups is not None:
        dev = tget(groups, "dev")
        if isinstance(dev, list):
            found.append((_DEV_GROUP, cast("list[object]", dev)))

    tool = _as_table(tget(doc, "tool"))
    uv = _as_table(tget(tool, "uv")) if tool is not None else None
    if uv is not None:
        dev = tget(uv, "dev-dependencies")
        if isinstance(dev, list):
            found.append((_UV_DEV, cast("list[object]", dev)))
    return found


def _top_level_array(
    doc: TOMLDocument,
    table_name: str,
    array_name: str,
    *,
    create: bool,
) -> list[object] | None:
    value = (
        doc.setdefault(table_name, tomlkit.table()) if create else tget(doc, table_name)
    )
    table = _as_table(value)
    if table is None:
        return None
    entries = tget(table, array_name)
    if entries is None and create:
        entries = tomlkit.array()
        table[array_name] = entries
    return cast("list[object]", entries) if isinstance(entries, list) else None


def _entries_at(
    doc: TOMLDocument, location: str, *, create: bool
) -> list[object] | None:
    if location == _PROJECT_DEPS:
        return _top_level_array(doc, "project", "dependencies", create=create)
    if location == _DEV_GROUP:
        return _top_level_array(doc, "dependency-groups", "dev", create=create)

    for candidate, entries in _dependency_lists(doc):
        if candidate == location:
            return entries
    return None


def _ownership_table(doc: TOMLDocument, *, create: bool) -> TableLike | None:
    tool_value = (
        doc.setdefault("tool", tomlkit.table()) if create else tget(doc, "tool")
    )
    tool = _as_table(tool_value)
    if tool is None:
        return None
    rag_value = (
        tool.setdefault("vaultspec-rag", tomlkit.table())
        if create
        else tget(tool, "vaultspec-rag")
    )
    rag = _as_table(rag_value)
    if rag is None:
        return None
    value = (
        rag.setdefault("mcp-extra", tomlkit.table())
        if create
        else tget(rag, "mcp-extra")
    )
    return _as_table(value)


def _read_ownership(doc: TOMLDocument) -> McpExtraOwnership | None:
    table = _ownership_table(doc, create=False)
    if table is None:
        return None
    location = tget(table, "location")
    managed = tget(table, "managed")
    original = tget(table, "original")
    added = tget(table, "added")
    created_surface = tget(table, "created-surface") is True
    if not isinstance(location, str) or not isinstance(managed, str):
        return None
    if added is True:
        return McpExtraOwnership(location, managed, None, created_surface)
    if isinstance(original, str):
        return McpExtraOwnership(location, managed, original, created_surface)
    return None


def _write_ownership(doc: TOMLDocument, ownership: McpExtraOwnership) -> None:
    table = _ownership_table(doc, create=True)
    if table is None:
        raise TypeError("pyproject.toml [tool.vaultspec-rag] is not a table")
    table["location"] = ownership.location
    table["managed"] = ownership.managed
    if ownership.created_surface:
        table["created-surface"] = True
    else:
        table.pop("created-surface", None)  # pyright: ignore[reportUnknownMemberType]
    if ownership.original is None:
        table["added"] = True
        table.pop("original", None)  # pyright: ignore[reportUnknownMemberType]
    else:
        table["original"] = ownership.original
        table.pop("added", None)  # pyright: ignore[reportUnknownMemberType]


def _clear_ownership(doc: TOMLDocument) -> None:
    tool = _as_table(tget(doc, "tool"))
    rag = _as_table(tget(tool, "vaultspec-rag")) if tool is not None else None
    if rag is None or "mcp-extra" not in rag:
        return
    del rag["mcp-extra"]
    if not rag:
        del cast("TableLike", tool)["vaultspec-rag"]
    if tool is not None and not tool:
        del doc["tool"]


def _drop_empty_created_surface(doc: TOMLDocument, location: str) -> None:
    """Remove an empty dependency container created by this reconciliation."""
    if location == _PROJECT_DEPS:
        project = _as_table(tget(doc, "project"))
        if project is not None and tget(project, "dependencies") == []:
            del project["dependencies"]
        return
    if location == _DEV_GROUP:
        groups = _as_table(tget(doc, "dependency-groups"))
        if groups is not None and tget(groups, "dev") == []:
            del groups["dev"]
            if not groups:
                del doc["dependency-groups"]


def _restore_owned(doc: TOMLDocument, ownership: McpExtraOwnership) -> str | None:
    entries = _entries_at(doc, ownership.location, create=False)
    if entries is None:
        return f"owned MCP-extra surface {ownership.location} is missing"
    for index, entry in enumerate(entries):
        if entry != ownership.managed:
            continue
        if ownership.original is None:
            entries.pop(index)
            if ownership.created_surface:
                _drop_empty_created_surface(doc, ownership.location)
        else:
            entries[index] = ownership.original
        _clear_ownership(doc)
        return None
    return (
        f"owned MCP-extra requirement at {ownership.location} has drifted; "
        "refusing to rewrite it"
    )


def _location_matches_mode(location: str, mode: InstallMode) -> bool:
    if mode is InstallMode.DEPENDENCY:
        return location.startswith("[project]")
    return location in {_DEV_GROUP, _UV_DEV}


def _target_for_mode(
    doc: TOMLDocument,
    mode: InstallMode,
    *,
    allow_unexpected: bool = False,
) -> tuple[str | None, str | None, list[str]]:
    candidates = [
        (location, entries, index, entry)
        for location, entries in _dependency_lists(doc)
        for index, entry in enumerate(entries)
        if isinstance(entry, str) and _is_rag_requirement(entry)
    ]
    runtime = [item for item in candidates if item[0].startswith("[project]")]
    dev = [item for item in candidates if item[0] in {_DEV_GROUP, _UV_DEV}]
    expected = runtime if mode is InstallMode.DEPENDENCY else dev
    unexpected = dev if mode is InstallMode.DEPENDENCY else runtime
    if unexpected and not allow_unexpected:
        return (
            None,
            None,
            [
                f"vaultspec-rag is declared at {item[0]}, outside {mode.value} mode"
                for item in unexpected
            ],
        )
    if len(expected) > 1:
        return (
            None,
            None,
            [
                "vaultspec-rag has multiple declarations for the resolved mode: "
                + ", ".join(item[0] for item in expected)
            ],
        )
    if expected:
        location, _entries, _index, value = expected[0]
        return location, value, []
    default = _PROJECT_DEPS if mode is InstallMode.DEPENDENCY else _DEV_GROUP
    return default, None, []


def _disable_mcp_extra(
    pyproject: Path,
    doc: TOMLDocument,
    ownership: McpExtraOwnership | None,
    *,
    dry_run: bool,
) -> McpExtraReport:
    report = McpExtraReport()
    if ownership is None:
        report.action = "already-absent"
        return report
    report.location = ownership.location
    conflict = _restore_owned(doc, ownership)
    if conflict is not None:
        report.action = "conflict"
        report.conflicts.append(conflict)
        return report
    report.action = "would-remove" if dry_run else "removed"
    if not dry_run:
        write_doc_preserving_shape(pyproject, doc)
    return report


def _prepare_owned_move(
    doc: TOMLDocument,
    ownership: McpExtraOwnership | None,
    mode: InstallMode,
) -> tuple[McpExtraReport | None, bool]:
    if ownership is None:
        return None, False
    report = McpExtraReport(location=ownership.location)
    entries = _entries_at(doc, ownership.location, create=False)
    if entries is None or ownership.managed not in entries:
        report.action = "conflict"
        report.conflicts.append(
            f"owned MCP-extra requirement at {ownership.location} has drifted"
        )
        return report, False
    if _location_matches_mode(ownership.location, mode):
        report.action = "already"
        return report, False
    conflict = _restore_owned(doc, ownership)
    if conflict is not None:
        report.action = "conflict"
        report.conflicts.append(conflict)
        return report, False
    return None, True


def _complete_unowned_target_move(
    pyproject: Path,
    doc: TOMLDocument,
    report: McpExtraReport,
    *,
    moving: bool,
    dry_run: bool,
) -> McpExtraReport:
    if not moving:
        report.action = "already"
        return report
    report.action = "would-move" if dry_run else "moved"
    if not dry_run:
        write_doc_preserving_shape(pyproject, doc)
    return report


def _enable_mcp_extra(
    pyproject: Path,
    doc: TOMLDocument,
    ownership: McpExtraOwnership | None,
    *,
    mode: InstallMode,
    dry_run: bool,
) -> McpExtraReport:
    report = McpExtraReport()
    terminal, moving = _prepare_owned_move(doc, ownership, mode)
    if terminal is not None:
        return terminal

    location, original, conflicts = _target_for_mode(
        doc,
        mode,
        allow_unexpected=moving,
    )
    if location is None:
        report.action = "conflict"
        report.conflicts.extend(conflicts)
        return report
    report.location = location
    surface_existed = any(
        candidate == location for candidate, _entries in _dependency_lists(doc)
    )
    entries = _entries_at(doc, location, create=True)
    if entries is None:
        report.action = "conflict"
        report.conflicts.append(f"{location} is not an array")
        return report

    if original is not None:
        parsed = Requirement(original)
        if _EXTRA in parsed.extras:
            return _complete_unowned_target_move(
                pyproject,
                doc,
                report,
                moving=moving,
                dry_run=dry_run,
            )
        managed = _with_mcp_extra(original)
        entries[entries.index(original)] = managed
    else:
        managed = f"{RAG_DISTRIBUTION_NAME}[{_EXTRA}]"
        entries.append(managed)
    _write_ownership(
        doc,
        McpExtraOwnership(
            location,
            managed,
            original,
            created_surface=original is None and not surface_existed,
        ),
    )
    report.action = (
        ("would-move" if dry_run else "moved")
        if moving
        else ("would-apply" if dry_run else "applied")
    )
    if not dry_run:
        write_doc_preserving_shape(pyproject, doc)
    return report


def reconcile_mcp_extra(
    pyproject: Path,
    *,
    mode: InstallMode,
    enabled: bool,
    dry_run: bool = False,
) -> McpExtraReport:
    """Reconcile RAG's optional MCP extra without moving dependency placement."""
    doc = load_pyproject(pyproject)
    if doc is None:
        action = "tool" if mode is InstallMode.TOOL and enabled else "absent"
        return McpExtraReport(action=action)

    ownership = _read_ownership(doc)
    if mode is InstallMode.TOOL and enabled and ownership is None:
        return McpExtraReport(action="tool")
    if not enabled or mode is InstallMode.TOOL:
        return _disable_mcp_extra(pyproject, doc, ownership, dry_run=dry_run)
    return _enable_mcp_extra(pyproject, doc, ownership, mode=mode, dry_run=dry_run)


__all__ = ["McpExtraReport", "reconcile_mcp_extra"]
