"""Manage the direct ``torch`` dependency in a consumer's pyproject.

uv applies ``[tool.uv.sources]`` only to direct dependencies, so the
cu130 source pin is a no-op until ``torch`` appears as a direct dep.
This submodule detects that condition across every dependency surface
(PEP 621 / 735, uv dev-deps, Poetry, PDM, Hatch) and, when rag manages
it, adds or removes the direct entry under a marker key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from tomlkit import TOMLDocument

from ._constants import (
    _MANAGED_DIRECT_DEP_KEY,  # pyright: ignore[reportPrivateUsage]  # intra-package constant
    _TABLE_LIKE_TYPES,  # pyright: ignore[reportPrivateUsage]  # intra-package constant
    DIRECT_TORCH_REQUIREMENT,
    DirectTorchDepReport,
    TableLike,
    logger,
)
from ._inspect import load_pyproject
from ._mutate import write_doc_preserving_shape

if TYPE_CHECKING:
    from pathlib import Path


def _tget(mapping: TableLike | TOMLDocument, key: str) -> object:
    """Typed wrapper for tomlkit Container.get() which returns Unknown.

    tomlkit's Container inherits from an unparameterised dict, so
    .get() has return type ``Unknown | None`` in strict mode.
    Centralising the cast here keeps all other call sites clean.
    """
    return cast("object", mapping.get(key))  # pyright: ignore[reportUnknownMemberType]


def _is_torch_requirement(req: object) -> bool:
    """Return True if ``req`` (a PEP 508 entry) names ``torch``.

    Delegates name extraction to :class:`packaging.requirements.Requirement`,
    which is the spec-compliant PEP 508 parser shared across the modern
    Python packaging toolchain (uv, hatch, poetry-core). The parser
    handles extras (``torch[extra]``), version
    specifiers (``torch>=2.4``, ``torch (>=2.4)``), URL form
    (``torch @ https://...``), and PEP 508 markers
    (``torch ; sys_platform == 'linux'``) without the manual
    boundary-splitting that earlier versions of this predicate used.

    Names are compared after :func:`packaging.utils.canonicalize_name`
    so PEP 503/PEP 508 normalisation rules apply: case, ``-`` / ``_``
    / ``.`` separators all collapse to a single canonical form.

    Non-string inputs return False (tomlkit can yield dict-form
    entries, integers, comments - the predicate must stay total).
    Inputs that are syntactically invalid PEP 508 also return False
    rather than raising.
    """
    if not isinstance(req, str):
        return False
    text = req.strip()
    if not text:
        return False
    try:
        parsed = Requirement(text)
    except InvalidRequirement as exc:
        logger.debug("dep %r unparseable as PEP 508: %s", text, exc)
        return False
    return canonicalize_name(parsed.name) == "torch"


def _iter_dep_lists(doc: TOMLDocument) -> list[tuple[str, list[object]]]:
    """Yield ``(label, sequence)`` for every direct-dependency surface.

    Covers the four common shapes a consumer can declare torch in:

    - ``[project].dependencies`` (PEP 621)
    - ``[project].optional-dependencies.*`` (PEP 621 extras)
    - ``[dependency-groups].*`` (PEP 735)
    - ``[tool.uv].dev-dependencies`` (uv's pre-PEP-735 dev-deps shape,
      still present on many existing projects)

    Plus the two non-PEP-621 build backends rag's users actually run
    into:

    - Poetry: ``[tool.poetry.dependencies]`` /
      ``[tool.poetry.group.*.dependencies]`` (Mapping[name → spec]).
      We synthesise a list of the *names* so ``_is_torch_requirement``
      matches them - the spec strings are not PEP 508 in Poetry.
    - PDM: ``[tool.pdm.dev-dependencies]`` (Mapping[group → list[str]]),
      same shape as PEP 735.

    Without these branches a Poetry/PDM user with ``torch`` correctly
    declared still triggers the "not a direct dep" warning, and the
    suggested fix (``add to [project].dependencies``) would break their
    build.
    """
    found: list[tuple[str, list[object]]] = []

    _extract_pep_deps(doc, found)

    tool = _tget(doc, "tool")
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        return found

    _extract_uv_deps(tool, found)
    _extract_poetry_deps(tool, found)
    _extract_pdm_deps(tool, found)
    _extract_hatch_deps(tool, found)

    return found


def _extract_pep_optional_deps(
    project: TableLike, found: list[tuple[str, list[object]]]
) -> None:
    optional = _tget(project, "optional-dependencies")
    if isinstance(optional, _TABLE_LIKE_TYPES):
        for name, group in optional.items():  # pyright: ignore[reportUnknownVariableType]  # tomlkit items() yields Unknown pairs
            if isinstance(group, list):
                found.append(
                    (
                        f"[project.optional-dependencies].{name}",
                        cast("list[object]", group),
                    )
                )


def _extract_pep_groups(
    doc: TOMLDocument, found: list[tuple[str, list[object]]]
) -> None:
    groups = _tget(doc, "dependency-groups")
    if isinstance(groups, _TABLE_LIKE_TYPES):
        for name, group in groups.items():  # pyright: ignore[reportUnknownVariableType]  # tomlkit items() yields Unknown pairs
            if isinstance(group, list):
                found.append(
                    (f"[dependency-groups].{name}", cast("list[object]", group))
                )


def _extract_pep_deps(doc: TOMLDocument, found: list[tuple[str, list[object]]]) -> None:
    project = _tget(doc, "project")
    if isinstance(project, _TABLE_LIKE_TYPES):
        deps = _tget(project, "dependencies")
        if isinstance(deps, list):
            found.append(("[project].dependencies", cast("list[object]", deps)))
        _extract_pep_optional_deps(project, found)
    _extract_pep_groups(doc, found)


def _extract_uv_deps(tool: TableLike, found: list[tuple[str, list[object]]]) -> None:
    uv = _tget(tool, "uv")
    if isinstance(uv, _TABLE_LIKE_TYPES):
        uv_dev = _tget(uv, "dev-dependencies")
        if isinstance(uv_dev, list):
            found.append(("[tool.uv].dev-dependencies", cast("list[object]", uv_dev)))


def _extract_poetry_groups(
    poetry: TableLike, found: list[tuple[str, list[object]]]
) -> None:
    pgroups = _tget(poetry, "group")
    if not isinstance(pgroups, _TABLE_LIKE_TYPES):
        return
    for gname, gtable in pgroups.items():  # pyright: ignore[reportUnknownVariableType]  # tomlkit items() yields Unknown pairs
        if not isinstance(gtable, _TABLE_LIKE_TYPES):
            continue
        gdeps = _tget(gtable, "dependencies")
        if isinstance(gdeps, _TABLE_LIKE_TYPES):
            found.append(
                (
                    f"[tool.poetry.group.{gname}.dependencies]",
                    list(gdeps.keys()),  # pyright: ignore[reportUnknownArgumentType]  # tomlkit keys() returns dict_keys[Unknown, Unknown]
                )
            )


def _extract_poetry_deps(
    tool: TableLike, found: list[tuple[str, list[object]]]
) -> None:
    poetry = _tget(tool, "poetry")
    if not isinstance(poetry, _TABLE_LIKE_TYPES):
        return
    pdeps = _tget(poetry, "dependencies")
    if isinstance(pdeps, _TABLE_LIKE_TYPES):
        found.append(("[tool.poetry.dependencies]", list(pdeps.keys())))  # pyright: ignore[reportUnknownArgumentType]  # tomlkit keys() returns dict_keys[Unknown, Unknown]
    pdev = _tget(poetry, "dev-dependencies")
    if isinstance(pdev, _TABLE_LIKE_TYPES):
        found.append(("[tool.poetry.dev-dependencies]", list(pdev.keys())))  # pyright: ignore[reportUnknownArgumentType]  # tomlkit keys() returns dict_keys[Unknown, Unknown]
    _extract_poetry_groups(poetry, found)


def _extract_pdm_deps(tool: TableLike, found: list[tuple[str, list[object]]]) -> None:
    pdm = _tget(tool, "pdm")
    if isinstance(pdm, _TABLE_LIKE_TYPES):
        pdm_dev = _tget(pdm, "dev-dependencies")
        if isinstance(pdm_dev, _TABLE_LIKE_TYPES):
            for gname, gdeps in pdm_dev.items():  # pyright: ignore[reportUnknownVariableType]  # tomlkit items() yields Unknown pairs
                if isinstance(gdeps, list):
                    found.append(
                        (
                            f"[tool.pdm.dev-dependencies].{gname}",
                            cast("list[object]", gdeps),
                        )
                    )


def _extract_hatch_env(
    ename: object, etable: object, found: list[tuple[str, list[object]]]
) -> None:
    if not isinstance(etable, _TABLE_LIKE_TYPES):
        return
    for key in ("dependencies", "extra-dependencies"):
        edeps = _tget(etable, key)
        if isinstance(edeps, list):
            found.append(
                (f"[tool.hatch.envs.{ename}].{key}", cast("list[object]", edeps))
            )
        elif isinstance(edeps, _TABLE_LIKE_TYPES):
            found.append(
                (
                    f"[tool.hatch.envs.{ename}.{key}]",
                    list(edeps.keys()),  # pyright: ignore[reportUnknownArgumentType]  # tomlkit keys() returns dict_keys[Unknown, Unknown]
                )
            )


def _extract_hatch_deps(tool: TableLike, found: list[tuple[str, list[object]]]) -> None:
    hatch = _tget(tool, "hatch")
    if not isinstance(hatch, _TABLE_LIKE_TYPES):
        return
    envs = _tget(hatch, "envs")
    if not isinstance(envs, _TABLE_LIKE_TYPES):
        return
    for ename, etable in envs.items():  # pyright: ignore[reportUnknownVariableType]  # tomlkit items() yields Unknown pairs
        _extract_hatch_env(cast("object", ename), cast("object", etable), found)  # pyright: ignore[reportUnknownArgumentType]  # tomlkit Unknown iteration values


def has_direct_torch_dep(pyproject: Path) -> tuple[bool, str]:
    """Return ``(present, location)`` for a direct ``torch`` dependency.

    uv silently ignores ``[tool.uv.sources]`` entries for purely-
    transitive packages. The cu130 source pin therefore only takes
    effect once ``torch`` appears as a direct dep of the consumer
    project. This helper lets the install flow surface a warning when
    the patch will be a no-op.

    Args:
        pyproject: Path to the consumer's ``pyproject.toml``.

    Returns:
        ``(True, "<location>")`` when torch is found as a direct dep,
        with ``location`` naming the dotted-key path of the table or
        list that contained the entry. ``(False, "")`` when absent or
        when the file cannot be parsed (the install flow already
        surfaces parse errors elsewhere).
    """
    try:
        doc = load_pyproject(pyproject)
    except Exception as exc:
        # Broad except: install flow surfaces parse errors elsewhere
        # via a dedicated diagnostic. Here we only need a
        # boolean answer; debug-log so the swallow stays observable.
        logger.debug("torch-config _load(%s) failed: %s", pyproject, exc, exc_info=True)
        return False, ""
    if doc is None:
        return False, ""
    for label, deps in _iter_dep_lists(doc):
        for entry in deps:
            if _is_torch_requirement(entry):
                return True, label
    return False, ""


def _tool_vaultspec_rag(doc: TOMLDocument) -> TableLike | None:
    tool = _tget(doc, "tool")
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        return None
    rag = _tget(tool, "vaultspec-rag")
    if not isinstance(rag, _TABLE_LIKE_TYPES):
        return None
    return rag


# The canonical location string for the PEP 621 project-deps surface.
# A legacy boolean ``managed-torch-direct-dependency = true`` marker is
# read as this surface so installs that predate the location-bearing
# marker uninstall from the same place they were written.
_PROJECT_DEPS_LOCATION: str = "[project].dependencies"
_GROUP_LOCATION_PREFIX: str = "[dependency-groups]."


def _set_managed_direct_dep_marker(doc: TOMLDocument, location: str) -> None:
    """Record the surface the managed torch dep was written to.

    The marker is location-bearing (the dotted-key path of the written
    surface) rather than a bare boolean, so uninstall removes from the
    surface install actually wrote and never from a hard-coded guess.
    """
    tool = doc.setdefault("tool", tomlkit.table())
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool] is not a table")
    rag = tool.setdefault("vaultspec-rag", tomlkit.table())
    if not isinstance(rag, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool.vaultspec-rag] is not a table")
    rag[_MANAGED_DIRECT_DEP_KEY] = location


def _clear_managed_direct_dep_marker(doc: TOMLDocument) -> None:
    rag = _tool_vaultspec_rag(doc)
    if rag is not None and _MANAGED_DIRECT_DEP_KEY in rag:
        del rag[_MANAGED_DIRECT_DEP_KEY]


def _managed_direct_dep_marker(doc: TOMLDocument) -> str | None:
    """Return the recorded write location, or ``None`` when unmanaged.

    A legacy boolean ``True`` marker (written before the marker carried
    a location) maps to ``[project].dependencies``, the only surface the
    historic code could write. Absent, ``False``, or any non-string /
    non-``True`` value reads as unmanaged.
    """
    rag = _tool_vaultspec_rag(doc)
    marker: object = _tget(rag, _MANAGED_DIRECT_DEP_KEY) if rag is not None else None
    if marker is True:
        return _PROJECT_DEPS_LOCATION
    if isinstance(marker, str) and marker:
        return marker
    return None


def _project_dependencies(
    doc: TOMLDocument,
) -> tuple[list[object] | None, str, list[str]]:
    project = doc.setdefault("project", tomlkit.table())
    if not isinstance(project, _TABLE_LIKE_TYPES):
        return None, "", ["[project] is not a table"]
    deps = _tget(project, "dependencies")
    if deps is None:
        new_arr = tomlkit.array()
        project["dependencies"] = new_arr
        deps = new_arr
    if not isinstance(deps, list):
        return None, "", ["[project].dependencies is not an array"]
    return cast("list[object]", deps), _PROJECT_DEPS_LOCATION, []


def _group_dependencies(
    doc: TOMLDocument, group: str
) -> tuple[list[object] | None, str, list[str]]:
    """Resolve the named PEP 735 ``[dependency-groups].<group>`` array.

    Mirrors :func:`_project_dependencies`: creates the
    ``[dependency-groups]`` table and the named array via
    ``setdefault`` / ``tomlkit.array()`` when absent, and returns the
    ``[dependency-groups].<group>`` location string. uv applies a
    ``[tool.uv.sources]`` pin to a group dep only when that group is
    enabled for the resolve, but the placement itself is still a valid
    direct-dep surface.
    """
    location = f"{_GROUP_LOCATION_PREFIX}{group}"
    groups = doc.setdefault("dependency-groups", tomlkit.table())
    if not isinstance(groups, _TABLE_LIKE_TYPES):
        return None, "", ["[dependency-groups] is not a table"]
    deps = _tget(groups, group)
    if deps is None:
        new_arr = tomlkit.array()
        groups[group] = new_arr
        deps = new_arr
    if not isinstance(deps, list):
        return None, "", [f"{location} is not an array"]
    return cast("list[object]", deps), location, []


def _resolve_write_target(
    doc: TOMLDocument, torch_group: str | None
) -> tuple[list[object] | None, str, list[str]]:
    """Pick the dependency surface the managed torch dep is written to.

    With no group selector the target is ``[project].dependencies``
    (the historic default, byte-for-byte unchanged). With a group
    selector the target is ``[dependency-groups].<group>``.
    """
    if torch_group is None:
        return _project_dependencies(doc)
    return _group_dependencies(doc, torch_group)


def ensure_direct_torch_dep(
    pyproject: Path, *, torch_group: str | None = None
) -> DirectTorchDepReport:
    """Ensure the consumer pyproject declares ``torch`` directly.

    uv applies ``[tool.uv.sources]`` only to direct dependencies. When
    rag writes the CUDA source pin, it must also ensure ``torch`` is
    present in the consumer's dependency graph, otherwise the pin is a
    no-op and uv keeps resolving the CPU wheel from PyPI.

    Args:
        pyproject: Path to the consumer's ``pyproject.toml``.
        torch_group: When given, the managed dep is written to the PEP
            735 ``[dependency-groups].<torch_group>`` surface instead of
            ``[project].dependencies``, keeping torch out of a dev-only
            consumer's published ``Requires-Dist``. ``None`` (the
            default) preserves the historic project-deps placement.
    """
    report = DirectTorchDepReport(action="skipped", path=pyproject)
    doc = load_pyproject(pyproject)
    if doc is None:
        report.action = "absent"
        return report

    direct, location = has_direct_torch_dep(pyproject)
    if direct:
        report.action = "already"
        report.location = location
        return report

    deps, location, conflicts = _resolve_write_target(doc, torch_group)
    if deps is None:
        report.action = "conflict"
        report.conflicts = conflicts
        return report

    deps.append(DIRECT_TORCH_REQUIREMENT)
    _set_managed_direct_dep_marker(doc, location)
    write_doc_preserving_shape(pyproject, doc)
    report.action = "applied"
    report.location = location
    return report


def _deps_for_location(
    doc: TOMLDocument, location: str
) -> tuple[list[object] | None, str, list[str]]:
    """Resolve the dependency array named by a recorded marker location.

    Inverse of :func:`_resolve_write_target`: parses the location string
    the marker recorded so uninstall removes from exactly that surface.
    """
    if location.startswith(_GROUP_LOCATION_PREFIX):
        group = location[len(_GROUP_LOCATION_PREFIX) :]
        return _group_dependencies(doc, group)
    return _project_dependencies(doc)


def remove_managed_direct_torch_dep(pyproject: Path) -> DirectTorchDepReport:
    """Remove the direct ``torch`` dependency only when rag added it.

    Removal targets the surface the ownership marker recorded - so a
    group-placed dep is removed from its group, a project-deps dep from
    project deps, and a legacy boolean marker from project deps. An
    unmarked user-declared torch is never touched.
    """
    report = DirectTorchDepReport(action="skipped", path=pyproject)
    doc = load_pyproject(pyproject)
    if doc is None:
        report.action = "absent"
        return report
    marker_location = _managed_direct_dep_marker(doc)
    if marker_location is None:
        return report

    deps, location, conflicts = _deps_for_location(doc, marker_location)
    if deps is None:
        report.action = "conflict"
        report.conflicts = conflicts
        return report

    for index, entry in enumerate(list(deps)):
        if entry == DIRECT_TORCH_REQUIREMENT:
            deps.pop(index)  # pyright: ignore[reportUnknownMemberType]  # tomlkit list
            _clear_managed_direct_dep_marker(doc)
            write_doc_preserving_shape(pyproject, doc)
            report.action = "removed"
            report.location = location
            return report

    _clear_managed_direct_dep_marker(doc)
    write_doc_preserving_shape(pyproject, doc)
    report.action = "absent"
    report.location = location
    return report
