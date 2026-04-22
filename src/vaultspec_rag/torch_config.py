"""Detect, write, and remove the canonical cu130 torch block in a user's
``pyproject.toml``.

This module is the pure-logic layer for rag's ``install`` /
``uninstall`` torch-config step. It mirrors the per-resource module
pattern core follows for ``gitignore.py`` / ``gitattributes.py`` /
``mcps.py``: no Typer, no Rich, no prompts, no process side-effects
beyond a single atomic write.

Canonical block shape — see :func:`manual_snippet` for the exact
bytes rag emits (three module constants compose the shape).

The three module-level constants are the single source of truth for
that shape — apply and remove compare against them, and
``manual_snippet`` renders them verbatim. Symmetric apply/remove is
guaranteed by construction.

See :doc:`.vault/adr/2026-04-22-install-cuda-adr` for the
architectural decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import AoT, Array, InlineTable, Table
from vaultspec_core.core.helpers import atomic_write

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "CU130_INDEX_NAME",
    "CU130_INDEX_URL",
    "CU130_MARKER",
    "PatchReport",
    "TorchConfigState",
    "TorchDiagnosis",
    "apply_patch",
    "detect_state",
    "diagnose_torch",
    "manual_snippet",
    "preview_patch",
    "remove_patch",
]


CU130_INDEX_NAME: Final[str] = "pytorch-cu130"
CU130_INDEX_URL: Final[str] = "https://download.pytorch.org/whl/cu130"
CU130_MARKER: Final[str] = "sys_platform == 'linux' or sys_platform == 'win32'"


class TorchConfigState(StrEnum):
    """Classification of a ``pyproject.toml`` relative to rag's cu130 block."""

    MISSING = "missing"
    CANONICAL = "canonical"
    CUSTOMISED = "customised"
    NO_PROJECT_FILE = "no_project_file"


class TorchDiagnosis(StrEnum):
    """Classification of a torch install's CUDA support."""

    NO_TORCH = "no_torch"
    CPU_ONLY = "cpu_only"
    NO_GPU = "no_gpu"
    WORKING = "working"


@dataclass
class PatchReport:
    """Structured outcome of an apply / remove pass.

    Attributes:
        action: One of ``"applied"``, ``"skipped"``, ``"conflict"``,
            ``"absent"``, ``"already"``, ``"removed"``.
        path: The pyproject.toml inspected.
        conflicts: Human-readable descriptions of conflicting keys
            when ``action == "conflict"``.
        preview: The TOML snippet that would be (or was) written,
            for dry-run / display purposes.
    """

    action: str
    path: Path
    conflicts: list[str] = field(default_factory=list)
    preview: str = ""


def manual_snippet() -> str:
    """Return the canonical cu130 block as a copy-pasteable string.

    Assembled from the three module constants so this string and the
    shape ``apply_patch`` writes can never drift.
    """
    return (
        "\n"
        "[[tool.uv.index]]\n"
        f'name = "{CU130_INDEX_NAME}"\n'
        f'url = "{CU130_INDEX_URL}"\n'
        "explicit = true\n"
        "\n"
        "[tool.uv.sources]\n"
        f'torch = [{{ index = "{CU130_INDEX_NAME}", '
        f'marker = "{CU130_MARKER}" }}]\n'
    )


def _load(pyproject: Path) -> TOMLDocument | None:
    """Load and parse the pyproject.toml, or return None if absent."""
    if not pyproject.is_file():
        return None
    try:
        return tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("pyproject.toml parse failed at %s: %s", pyproject, exc)
        raise


def _tool_uv(doc: TOMLDocument) -> Table | None:
    """Return the ``[tool.uv]`` table, or None."""
    tool = doc.get("tool")
    if not isinstance(tool, Table | dict):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, Table | dict):
        return None
    return uv  # type: ignore[return-value]


def _indices(doc: TOMLDocument) -> AoT | list | None:
    """Return the ``[[tool.uv.index]]`` array-of-tables, or None."""
    uv = _tool_uv(doc)
    if uv is None:
        return None
    idx = uv.get("index")
    if idx is None:
        return None
    return idx  # type: ignore[return-value]


def _torch_sources(doc: TOMLDocument) -> Array | list | None:
    """Return the ``torch`` entry under ``[tool.uv.sources]``, or None."""
    uv = _tool_uv(doc)
    if uv is None:
        return None
    sources = uv.get("sources")
    if not isinstance(sources, Table | dict):
        return None
    return sources.get("torch")  # type: ignore[return-value]


def _index_match(entry: Table | InlineTable | dict) -> str:
    """Classify one ``[[tool.uv.index]]`` entry against the canonical cu130.

    Returns ``"canonical"`` if the entry has our name, our url, and
    ``explicit = true``; ``"conflict"`` if the entry has our name but
    disagrees on url/explicit; ``""`` if the entry is unrelated (name
    does not match).
    """
    name = entry.get("name")
    if name != CU130_INDEX_NAME:
        return ""
    url = entry.get("url")
    explicit = entry.get("explicit", False)
    if url == CU130_INDEX_URL and bool(explicit) is True:
        return "canonical"
    return "conflict"


def _source_match(entry: InlineTable | dict) -> str:
    """Classify one ``torch`` source entry against the canonical cu130.

    Returns ``"canonical"`` if the entry matches our ``index`` and
    ``marker`` (and nothing else beyond the two keys); ``"conflict"``
    if the entry references our index name but disagrees; ``""`` if
    the entry is unrelated (different index).
    """
    idx = entry.get("index")
    if idx != CU130_INDEX_NAME:
        return ""
    marker = entry.get("marker")
    extras = set(entry.keys()) - {"index", "marker"}
    if marker == CU130_MARKER and not extras:
        return "canonical"
    return "conflict"


def _classify(doc: TOMLDocument) -> tuple[TorchConfigState, list[str]]:
    """Inspect the loaded doc and return (state, conflicts)."""
    indices = _indices(doc)
    torch_srcs = _torch_sources(doc)

    conflicts: list[str] = []
    index_canonical = False
    index_conflict = False

    if indices is not None:
        for entry in indices:
            if not isinstance(entry, Table | InlineTable | dict):
                continue
            m = _index_match(entry)
            if m == "canonical":
                index_canonical = True
            elif m == "conflict":
                index_conflict = True
                conflicts.append(
                    f"[[tool.uv.index]] '{CU130_INDEX_NAME}' "
                    f"exists with non-canonical url/explicit"
                )

    source_canonical = False
    source_conflict = False

    if torch_srcs is not None:
        # torch source may be a single inline table or a list of them.
        if isinstance(torch_srcs, list):
            entries: list = list(torch_srcs)
        else:
            entries = [torch_srcs]
        for entry in entries:
            if not isinstance(entry, InlineTable | Table | dict):
                continue
            m = _source_match(entry)
            if m == "canonical":
                source_canonical = True
            elif m == "conflict":
                source_conflict = True
                conflicts.append(
                    f"[tool.uv.sources] torch references "
                    f"'{CU130_INDEX_NAME}' with non-canonical marker/extras"
                )

    if index_conflict or source_conflict:
        return TorchConfigState.CUSTOMISED, conflicts
    if index_canonical and source_canonical:
        return TorchConfigState.CANONICAL, []
    if index_canonical != source_canonical:
        # Half-applied state — treat as customised; we cannot safely
        # complete it without risking user intent.
        missing = "source" if index_canonical else "index"
        conflicts.append(
            f"cu130 {missing} entry missing while the other half is present"
        )
        return TorchConfigState.CUSTOMISED, conflicts
    return TorchConfigState.MISSING, []


def detect_state(pyproject: Path) -> TorchConfigState:
    """Classify the current torch-config block at ``pyproject``.

    Returns one of ``NO_PROJECT_FILE``, ``MISSING``, ``CANONICAL``,
    ``CUSTOMISED``. Pure read; never writes.

    Args:
        pyproject: Path to the consumer's ``pyproject.toml``.

    Raises:
        tomlkit.exceptions.ParseError: If the file is syntactically
            invalid TOML. Callers should surface this as a hard error
            — there is no safe way to edit a corrupt file.
    """
    doc = _load(pyproject)
    if doc is None:
        return TorchConfigState.NO_PROJECT_FILE
    state, _ = _classify(doc)
    return state


def preview_patch(pyproject: Path) -> str:
    """Return the TOML snippet ``apply_patch`` would write.

    Returns an empty string when state is ``CANONICAL`` (nothing to
    do) or ``CUSTOMISED`` (apply refuses). Returns
    :func:`manual_snippet` for ``MISSING`` and ``NO_PROJECT_FILE``.
    """
    state = detect_state(pyproject)
    if state in (TorchConfigState.MISSING, TorchConfigState.NO_PROJECT_FILE):
        return manual_snippet()
    return ""


def apply_patch(pyproject: Path) -> PatchReport:
    """Write the canonical cu130 block into ``pyproject``.

    Idempotent:
    - ``CANONICAL`` → ``action="already"``, no write.
    - ``CUSTOMISED`` → ``action="conflict"`` with conflicts listed,
      no write.
    - ``NO_PROJECT_FILE`` → ``action="absent"``, no write.
    - ``MISSING`` → write via
      :func:`vaultspec_core.core.helpers.atomic_write`,
      ``action="applied"``.

    Preserves all user comments, key ordering, and whitespace in the
    rest of the document via tomlkit's round-trip semantics.
    """
    report = PatchReport(action="skipped", path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = "absent"
        return report

    state, conflicts = _classify(doc)
    if state == TorchConfigState.CANONICAL:
        report.action = "already"
        return report
    if state == TorchConfigState.CUSTOMISED:
        report.action = "conflict"
        report.conflicts = conflicts
        return report

    # MISSING → write.
    _ensure_tool_uv_index(doc)
    _ensure_torch_source(doc)
    new_text = tomlkit.dumps(doc)
    # Reparse to confirm validity before the write crosses the FS boundary.
    tomlkit.parse(new_text)
    atomic_write(pyproject, new_text)
    report.action = "applied"
    report.preview = manual_snippet()
    return report


def remove_patch(pyproject: Path) -> PatchReport:
    """Remove the canonical cu130 block from ``pyproject``.

    Symmetric inverse of :func:`apply_patch`:
    - ``MISSING`` or ``NO_PROJECT_FILE`` → ``action="absent"``.
    - ``CUSTOMISED`` → ``action="skipped"`` with conflicts listed;
      file unchanged.
    - ``CANONICAL`` → remove only our entries, drop any now-empty
      containers, ``action="removed"``.

    After removal, the file should reparse as valid TOML and all
    user-owned content outside the cu130 block is preserved.
    """
    report = PatchReport(action="skipped", path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = "absent"
        return report

    state, conflicts = _classify(doc)
    if state == TorchConfigState.MISSING:
        report.action = "absent"
        return report
    if state == TorchConfigState.CUSTOMISED:
        report.action = "skipped"
        report.conflicts = conflicts
        return report

    # CANONICAL → remove.
    _drop_cu130_index(doc)
    _drop_torch_source(doc)
    new_text = tomlkit.dumps(doc)
    tomlkit.parse(new_text)
    atomic_write(pyproject, new_text)
    report.action = "removed"
    return report


def diagnose_torch(cuda: str | None, available: bool) -> TorchDiagnosis:
    """Classify a torch install from its observable CUDA attributes.

    Args:
        cuda: ``torch.version.cuda`` — ``None`` for the CPU-only
            wheel, a version string like ``"13.0"`` for the CUDA
            wheels.
        available: ``torch.cuda.is_available()`` result.

    Returns:
        One of :class:`TorchDiagnosis`. ``(None, True)`` is an
        anomaly not produced by any supported torch build; we fall
        back to ``CPU_ONLY`` because the remediation (reinstall from
        cu130) is the safer of the two.
    """
    if cuda is None:
        return TorchDiagnosis.CPU_ONLY
    if available:
        return TorchDiagnosis.WORKING
    return TorchDiagnosis.NO_GPU


# ---------------------------------------------------------------------------
# tomlkit mutation helpers
# ---------------------------------------------------------------------------


def _ensure_tool_uv_index(doc: TOMLDocument) -> None:
    """Append ``[[tool.uv.index]]`` with the canonical cu130 entry.

    Creates ``[tool]`` and ``[tool.uv]`` if absent. Appends to the
    existing array-of-tables if one is present.
    """
    tool = doc.setdefault("tool", tomlkit.table())
    if not isinstance(tool, Table | dict):  # defensive
        raise TypeError("pyproject.toml [tool] is not a table")
    uv = tool.setdefault("uv", tomlkit.table())
    if not isinstance(uv, Table | dict):
        raise TypeError("pyproject.toml [tool.uv] is not a table")

    existing = uv.get("index")
    entry = tomlkit.table()
    entry["name"] = CU130_INDEX_NAME
    entry["url"] = CU130_INDEX_URL
    entry["explicit"] = True

    if existing is None:
        aot = tomlkit.aot()
        aot.append(entry)
        uv["index"] = aot
    else:
        # existing is already an AoT; append our entry to the end.
        existing.append(entry)


def _ensure_torch_source(doc: TOMLDocument) -> None:
    """Ensure ``[tool.uv.sources]`` has a cu130 torch entry."""
    tool = doc.setdefault("tool", tomlkit.table())
    uv = tool.setdefault("uv", tomlkit.table())
    sources = uv.setdefault("sources", tomlkit.table())
    if not isinstance(sources, Table | dict):
        raise TypeError("pyproject.toml [tool.uv.sources] is not a table")

    inline = tomlkit.inline_table()
    inline["index"] = CU130_INDEX_NAME
    inline["marker"] = CU130_MARKER

    current = sources.get("torch")
    if current is None:
        arr = tomlkit.array()
        arr.append(inline)
        arr.multiline(True)
        sources["torch"] = arr
        return

    if isinstance(current, list):
        current.append(inline)
        return

    # Existing single inline-table form → promote to array.
    arr = tomlkit.array()
    arr.append(current)
    arr.append(inline)
    arr.multiline(True)
    sources["torch"] = arr


def _drop_cu130_index(doc: TOMLDocument) -> None:
    """Remove the canonical cu130 entry from ``[[tool.uv.index]]``."""
    indices = _indices(doc)
    if indices is None:
        return
    kept = []
    for e in indices:
        if isinstance(e, Table | InlineTable | dict) and _index_match(e) == "canonical":
            continue
        kept.append(e)
    uv = _tool_uv(doc)
    if uv is None:
        return
    if not kept:
        del uv["index"]
        return
    # Rebuild the AoT from the kept entries.
    aot = tomlkit.aot()
    for e in kept:
        aot.append(e)
    uv["index"] = aot


def _drop_torch_source(doc: TOMLDocument) -> None:
    """Remove the canonical cu130 torch entry from ``[tool.uv.sources]``."""
    uv = _tool_uv(doc)
    if uv is None:
        return
    sources = uv.get("sources")
    if not isinstance(sources, Table | dict):
        return
    torch_entry = sources.get("torch")
    if torch_entry is None:
        return

    if isinstance(torch_entry, InlineTable | dict) and not isinstance(
        torch_entry, list
    ):
        if _source_match(torch_entry) == "canonical":
            del sources["torch"]
        return

    # Array-of-inline-tables form.
    kept = [
        e
        for e in torch_entry
        if not (isinstance(e, InlineTable | dict) and _source_match(e) == "canonical")
    ]
    if not kept:
        del sources["torch"]
    else:
        arr = tomlkit.array()
        for e in kept:
            arr.append(e)
        if len(kept) > 1:
            arr.multiline(True)
        sources["torch"] = arr

    # If sources table is now empty, drop it. Same for [tool.uv] and [tool].
    if not sources:
        del uv["sources"]
    if not uv:
        tool = doc.get("tool")
        if isinstance(tool, Table | dict):
            del tool["uv"]
            if not tool:
                del doc["tool"]
