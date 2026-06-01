"""Manage the direct ``torch`` dependency in a consumer's pyproject.

uv applies ``[tool.uv.sources]`` only to direct dependencies, so the
cu130 source pin is a no-op until ``torch`` appears as a direct dep.
This submodule detects that condition across every dependency surface
(PEP 621 / 735, uv dev-deps, Poetry, PDM, Hatch) and, when rag manages
it, adds or removes the direct entry under a marker key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from tomlkit import TOMLDocument

from ._constants import (
    _MANAGED_DIRECT_DEP_KEY,
    _TABLE_LIKE_TYPES,
    DIRECT_TORCH_REQUIREMENT,
    DirectTorchDepReport,
    TableLike,
    logger,
)
from ._inspect import _load
from ._mutate import _write_doc_preserving_shape

if TYPE_CHECKING:
    from pathlib import Path


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
    entries, integers, comments — the predicate must stay total).
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


def _iter_dep_lists(doc: TOMLDocument) -> list[tuple[str, Any]]:
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
      matches them — the spec strings are not PEP 508 in Poetry.
    - PDM: ``[tool.pdm.dev-dependencies]`` (Mapping[group → list[str]]),
      same shape as PEP 735.

    Without these branches a Poetry/PDM user with ``torch`` correctly
    declared still triggers the "not a direct dep" warning, and the
    suggested fix (``add to [project].dependencies``) would break their
    build.
    """
    found: list[tuple[str, Any]] = []
    project = doc.get("project")
    # ``project`` is normally a standard table; ``optional-dependencies``
    # and ``dependency-groups`` may be expressed as inline tables
    # (``optional-dependencies = { gpu = [...] }``), which tomlkit returns
    # as :class:`tomlkit.items.InlineTable`. All three shapes expose the
    # ``.get(key)`` / ``.items()`` Mapping surface we exercise here.
    if isinstance(project, _TABLE_LIKE_TYPES):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            found.append(("[project].dependencies", deps))
        optional = project.get("optional-dependencies")
        if isinstance(optional, _TABLE_LIKE_TYPES):
            for name, group in optional.items():
                if isinstance(group, list):
                    found.append((f"[project.optional-dependencies].{name}", group))
    groups = doc.get("dependency-groups")
    if isinstance(groups, _TABLE_LIKE_TYPES):
        for name, group in groups.items():
            if isinstance(group, list):
                found.append((f"[dependency-groups].{name}", group))

    tool = doc.get("tool")
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        return found

    uv = tool.get("uv")
    if isinstance(uv, _TABLE_LIKE_TYPES):
        uv_dev = uv.get("dev-dependencies")
        if isinstance(uv_dev, list):
            found.append(("[tool.uv].dev-dependencies", uv_dev))

    poetry = tool.get("poetry")
    if isinstance(poetry, _TABLE_LIKE_TYPES):
        # Poetry's ``[tool.poetry.dependencies]`` is ``Mapping[name → spec]``.
        # The keys are bare package names; we synthesise a list of those
        # so ``_is_torch_requirement`` ("torch") matches.
        pdeps = poetry.get("dependencies")
        if isinstance(pdeps, _TABLE_LIKE_TYPES):
            found.append(("[tool.poetry.dependencies]", list(pdeps.keys())))
        # Pre-1.2 Poetry expressed dev deps as ``[tool.poetry.dev-dependencies]``.
        # Poetry 1.2+ moved them under ``[tool.poetry.group.dev.dependencies]``
        # but the legacy section is still produced by older `poetry add`
        # invocations and still on countless deployed pyprojects.
        pdev = poetry.get("dev-dependencies")
        if isinstance(pdev, _TABLE_LIKE_TYPES):
            found.append(("[tool.poetry.dev-dependencies]", list(pdev.keys())))
        pgroups = poetry.get("group")
        if isinstance(pgroups, _TABLE_LIKE_TYPES):
            for gname, gtable in pgroups.items():
                if not isinstance(gtable, _TABLE_LIKE_TYPES):
                    continue
                gdeps = gtable.get("dependencies")
                if isinstance(gdeps, _TABLE_LIKE_TYPES):
                    found.append(
                        (
                            f"[tool.poetry.group.{gname}.dependencies]",
                            list(gdeps.keys()),
                        )
                    )

    pdm = tool.get("pdm")
    if isinstance(pdm, _TABLE_LIKE_TYPES):
        # PDM ``[tool.pdm.dev-dependencies]`` is ``Mapping[group → list[str]]``,
        # same shape as PEP 735 ``[dependency-groups]``.
        pdm_dev = pdm.get("dev-dependencies")
        if isinstance(pdm_dev, _TABLE_LIKE_TYPES):
            for gname, gdeps in pdm_dev.items():
                if isinstance(gdeps, list):
                    found.append((f"[tool.pdm.dev-dependencies].{gname}", gdeps))

    hatch = tool.get("hatch")
    if isinstance(hatch, _TABLE_LIKE_TYPES):
        # Hatch envs (``[tool.hatch.envs.<env>]``) carry per-environment
        # dependency lists. Two surfaces are common in real projects:
        # ``dependencies`` / ``extra-dependencies`` as PEP 508 lists,
        # and the legacy ``[tool.hatch.envs.<env>.dependencies]`` table
        # form (``Mapping[name → spec]``, same shape as Poetry deps).
        # Both must be checked so a Hatch user with torch declared
        # doesn't trigger the "not a direct dep" warning.
        envs = hatch.get("envs")
        if isinstance(envs, _TABLE_LIKE_TYPES):
            for ename, etable in envs.items():
                if not isinstance(etable, _TABLE_LIKE_TYPES):
                    continue
                for key in ("dependencies", "extra-dependencies"):
                    edeps = etable.get(key)
                    if isinstance(edeps, list):
                        found.append((f"[tool.hatch.envs.{ename}].{key}", edeps))
                    elif isinstance(edeps, _TABLE_LIKE_TYPES):
                        found.append(
                            (
                                f"[tool.hatch.envs.{ename}.{key}]",
                                list(edeps.keys()),
                            )
                        )
    return found


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
        doc = _load(pyproject)
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
    tool = doc.get("tool")
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        return None
    rag = tool.get("vaultspec-rag")
    if not isinstance(rag, _TABLE_LIKE_TYPES):
        return None
    return rag


def _set_managed_direct_dep_marker(doc: TOMLDocument) -> None:
    tool = doc.setdefault("tool", tomlkit.table())
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool] is not a table")
    rag = tool.setdefault("vaultspec-rag", tomlkit.table())
    if not isinstance(rag, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool.vaultspec-rag] is not a table")
    rag[_MANAGED_DIRECT_DEP_KEY] = True


def _clear_managed_direct_dep_marker(doc: TOMLDocument) -> None:
    rag = _tool_vaultspec_rag(doc)
    if rag is not None and _MANAGED_DIRECT_DEP_KEY in rag:
        del rag[_MANAGED_DIRECT_DEP_KEY]


def _managed_direct_dep_marker(doc: TOMLDocument) -> bool:
    rag = _tool_vaultspec_rag(doc)
    return bool(rag is not None and rag.get(_MANAGED_DIRECT_DEP_KEY) is True)


def _project_dependencies(doc: TOMLDocument) -> tuple[list | None, str, list[str]]:
    project = doc.setdefault("project", tomlkit.table())
    if not isinstance(project, _TABLE_LIKE_TYPES):
        return None, "", ["[project] is not a table"]
    deps = project.get("dependencies")
    if deps is None:
        deps = tomlkit.array()
        project["dependencies"] = deps
    if not isinstance(deps, list):
        return None, "", ["[project].dependencies is not an array"]
    return deps, "[project].dependencies", []


def ensure_direct_torch_dep(pyproject: Path) -> DirectTorchDepReport:
    """Ensure the consumer pyproject declares ``torch`` directly.

    uv applies ``[tool.uv.sources]`` only to direct dependencies. When
    rag writes the CUDA source pin, it must also ensure ``torch`` is
    present in the consumer's dependency graph, otherwise the pin is a
    no-op and uv keeps resolving the CPU wheel from PyPI.
    """
    report = DirectTorchDepReport(action="skipped", path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = "absent"
        return report

    direct, location = has_direct_torch_dep(pyproject)
    if direct:
        report.action = "already"
        report.location = location
        return report

    deps, location, conflicts = _project_dependencies(doc)
    if deps is None:
        report.action = "conflict"
        report.conflicts = conflicts
        return report

    deps.append(DIRECT_TORCH_REQUIREMENT)
    _set_managed_direct_dep_marker(doc)
    _write_doc_preserving_shape(pyproject, doc)
    report.action = "applied"
    report.location = location
    return report


def remove_managed_direct_torch_dep(pyproject: Path) -> DirectTorchDepReport:
    """Remove the direct ``torch`` dependency only when rag added it."""
    report = DirectTorchDepReport(action="skipped", path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = "absent"
        return report
    if not _managed_direct_dep_marker(doc):
        return report

    deps, location, conflicts = _project_dependencies(doc)
    if deps is None:
        report.action = "conflict"
        report.conflicts = conflicts
        return report

    for index, entry in enumerate(list(deps)):
        if entry == DIRECT_TORCH_REQUIREMENT:
            deps.pop(index)
            _clear_managed_direct_dep_marker(doc)
            _write_doc_preserving_shape(pyproject, doc)
            report.action = "removed"
            report.location = location
            return report

    _clear_managed_direct_dep_marker(doc)
    _write_doc_preserving_shape(pyproject, doc)
    report.action = "absent"
    report.location = location
    return report
