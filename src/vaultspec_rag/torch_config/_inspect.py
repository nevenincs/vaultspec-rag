"""TOML inspection and classification of a consumer's ``pyproject.toml``.

Pure reads: load and parse the document, then classify the
``[[tool.uv.index]]`` and ``[tool.uv.sources]`` sections against rag's
canonical cu130 block. Never writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import AoT, InlineTable, Table

from ._constants import (
    _TABLE_LIKE_TYPES,
    CU130_INDEX_NAME,
    CU130_INDEX_URL,
    CU130_MARKER,
    TableLike,
    TorchConfigState,
    logger,
)

if TYPE_CHECKING:
    from pathlib import Path


def _detect_crlf(pyproject: Path) -> bool:
    """Return True when ``pyproject`` uses CRLF line endings on disk.

    Sniffs the raw bytes (not the decoded text) so the answer is the
    real on-disk encoding, immune to ``newline=`` translation. A
    Windows pyproject with ``\\r\\n`` line endings should round-trip
    through apply / remove without losing them - ``tomlkit.dumps``
    always emits LF, so the writer must restore the original
    convention before the atomic write or the user gets a noisy
    git diff that touches every existing line on the very first
    install.
    """
    try:
        return b"\r\n" in pyproject.read_bytes()
    except OSError as exc:
        logger.debug("pyproject %s unreadable for CRLF probe: %s", pyproject, exc)
        return False


def _load(pyproject: Path) -> TOMLDocument | None:
    """Load and parse the pyproject.toml, or return None if absent.

    Reads with ``utf-8-sig`` so a leading UTF-8 BOM (``U+FEFF``) is
    transparently stripped. Files saved from Notepad / "UTF-8 with BOM"
    in VS Code / git on Windows with certain ``core.autocrlf`` settings
    can carry a BOM that tomlkit's parser rejects as an empty bare
    key. ``tomllib`` (stdlib) accepts the BOM; tomlkit does not. The
    ``-sig`` codec is forgiving for files without a BOM, so the change
    is upward-compatible: every file that previously parsed continues
    to parse unchanged.
    """
    if not pyproject.is_file():
        return None
    try:
        return tomlkit.parse(pyproject.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.warning("pyproject.toml parse failed at %s: %s", pyproject, exc)
        raise


def _tool_uv(doc: TOMLDocument) -> TableLike | None:
    """Return the ``[tool.uv]`` table, or None.

    Narrowed to either :class:`tomlkit.items.Table` or
    :class:`tomlkit.container.OutOfOrderTableProxy`. tomlkit returns
    the proxy whenever ``[tool.uv]`` and ``[tool.uv.sources]`` (or
    ``[[tool.uv.index]]``) are interleaved with non-uv sections - the
    dominant ``[tool.*]`` layout in real-world pyprojects. Both expose
    the same Mapping surface we touch.
    """
    tool = doc.get("tool")
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, _TABLE_LIKE_TYPES):
        return None
    return uv


def _indices(doc: TOMLDocument) -> AoT | None:
    """Return the ``[[tool.uv.index]]`` array-of-tables, or None.

    Returns None if the key is absent OR if it exists but is not an
    AoT. Callers (apply/remove helpers) rely on AoT-specific methods
    like ``.append()`` and item-index ``.pop()``; returning only AoT
    keeps the downstream contract narrow. The CUSTOMISED-classifier
    in :func:`_classify` catches non-AoT shapes separately via a
    direct ``uv.get("index")`` probe.
    """
    uv = _tool_uv(doc)
    if uv is None:
        return None
    idx = uv.get("index")
    if not isinstance(idx, AoT):
        return None
    return idx


def _torch_sources(doc: TOMLDocument) -> Any:
    """Return the ``torch`` entry under ``[tool.uv.sources]``, or None.

    Returns whatever tomlkit has at that key so the caller can
    classify unusual shapes (scalar, standard Table, inline-table
    array, or missing). Strictly-typed callers downcast as needed.

    ``sources`` may be either the standard-table form (``[tool.uv.sources]``
    + line of keys), the proxy form when interleaved with non-uv
    sections, OR the inline-table form (``sources = { torch = [...] }``)
    that tomlkit returns as :class:`tomlkit.items.InlineTable`. All
    three expose the ``.get(key)`` Mapping surface we exercise here.
    """
    uv = _tool_uv(doc)
    if uv is None:
        return None
    sources = uv.get("sources")
    if not isinstance(sources, _TABLE_LIKE_TYPES):
        return None
    return sources.get("torch")


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
    if url == CU130_INDEX_URL and bool(explicit):
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


def _classify_indices(
    doc: TOMLDocument,
) -> tuple[bool | None, bool, list[str]]:
    """Classify the ``[[tool.uv.index]]`` section.

    Returns a tuple ``(canonical_seen, conflict_seen, conflicts)``
    where ``canonical_seen`` is ``None`` when the user's TOML has a
    shape we refuse to touch (single-table ``[tool.uv.index]``) -
    the caller should short-circuit to ``CUSTOMISED``.
    """
    conflicts: list[str] = []

    # ``[tool.uv.index]`` (single table) and ``index = [{...}]`` (inline
    # array dotted-key form) are both valid TOML but incompatible with
    # our array-of-tables mutations. Probe the raw key directly -
    # ``_indices()`` narrows to AoT only, so we can't use its return
    # value to detect these shapes. Distinguish the two so the
    # conflict message describes what the user actually wrote (a
    # "single table" message for an inline-array confused some users
    # into thinking the issue was the wrong-key shape). TOML-03.
    uv = _tool_uv(doc)
    raw_index = uv.get("index") if uv is not None else None
    if raw_index is not None and not isinstance(raw_index, AoT):
        if isinstance(raw_index, list):
            conflicts.append(
                "[tool.uv.index] is an inline array (dotted-key form); "
                "rag's apply_patch expects [[tool.uv.index]] table-array "
                "syntax"
            )
        else:
            conflicts.append(
                "[tool.uv.index] is a single table, not an array-of-tables; "
                "rag's apply_patch expects [[tool.uv.index]]"
            )
        return None, False, conflicts

    canonical_seen = False
    conflict_seen = False
    indices = _indices(doc)
    if indices is not None:
        for entry in indices:
            if not isinstance(entry, Table | InlineTable | dict):
                continue
            m = _index_match(entry)
            if m == "canonical":
                canonical_seen = True
            elif m == "conflict":
                conflict_seen = True
                conflicts.append(
                    f"[[tool.uv.index]] '{CU130_INDEX_NAME}' "
                    f"exists with non-canonical url/explicit"
                )
    return canonical_seen, conflict_seen, conflicts


def _classify_sources(
    doc: TOMLDocument,
) -> tuple[bool | None, bool, list[str]]:
    """Classify the ``[tool.uv.sources]`` ``torch`` entry.

    Return convention mirrors :func:`_classify_indices`: a
    ``canonical_seen`` value of ``None`` signals an unsupported
    user shape (scalar or standard-table form), and the caller must
    short-circuit to ``CUSTOMISED``.
    """
    conflicts: list[str] = []
    torch_srcs = _torch_sources(doc)
    if torch_srcs is None:
        return False, False, conflicts

    # Scalar at `tool.uv.sources.torch` (string, int, bool, …) is
    # syntactically legal TOML but semantically nonsense for uv.
    # Treat as CUSTOMISED so apply_patch refuses before the
    # mutation helpers inherit a value they cannot recurse into.
    if not isinstance(torch_srcs, InlineTable | Table | list | dict):
        conflicts.append(
            f"[tool.uv.sources] torch is a "
            f"{type(torch_srcs).__name__}, not an array or table"
        )
        return None, False, conflicts

    # `[tool.uv.sources.torch]` (standard table, e.g. a git source
    # spelled as its own section) cannot be promoted into a TOML
    # array - arrays can only hold inline tables. Treat as
    # CUSTOMISED so apply never tries to rewrite it.
    if isinstance(torch_srcs, Table) and not isinstance(torch_srcs, InlineTable | list):
        conflicts.append(
            "[tool.uv.sources.torch] is a standard table; "
            "rag's apply_patch expects an inline-table array"
        )
        return None, False, conflicts

    canonical_seen = False
    conflict_seen = False
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
            canonical_seen = True
        elif m == "conflict":
            conflict_seen = True
            conflicts.append(
                f"[tool.uv.sources] torch references "
                f"'{CU130_INDEX_NAME}' with non-canonical marker/extras"
            )
    return canonical_seen, conflict_seen, conflicts


def _classify(doc: TOMLDocument) -> tuple[TorchConfigState, list[str]]:
    """Inspect the loaded doc and return (state, conflicts).

    Delegates the per-section classification to
    :func:`_classify_indices` and :func:`_classify_sources`, then
    combines their verdicts into a single ``TorchConfigState``.
    """
    index_canonical, index_conflict, index_conflicts = _classify_indices(doc)
    if index_canonical is None:
        # Short-circuit on an unsupported user shape at [[tool.uv.index]].
        return TorchConfigState.CUSTOMISED, index_conflicts

    source_canonical, source_conflict, source_conflicts = _classify_sources(doc)
    if source_canonical is None:
        return TorchConfigState.CUSTOMISED, source_conflicts

    conflicts = index_conflicts + source_conflicts
    if index_conflict or source_conflict:
        return TorchConfigState.CUSTOMISED, conflicts
    if index_canonical and source_canonical:
        return TorchConfigState.CANONICAL, []
    if index_canonical != source_canonical:
        # Half-applied state - treat as customised; we cannot safely
        # complete it without risking user intent.
        missing = "source" if index_canonical else "index"
        conflicts.append(
            f"cu130 {missing} entry missing while the other half is present"
        )
        return TorchConfigState.CUSTOMISED, conflicts
    return TorchConfigState.MISSING, []


def _is_half_applied(doc: TOMLDocument) -> bool:
    """Return True for the half-applied no-conflict state.

    Half-applied = exactly one of ``[[tool.uv.index]]`` /
    ``[tool.uv.sources]`` carries a rag-canonical entry; the other
    half is simply absent (no non-canonical entry, no unsupported
    shape, no per-half conflict). :func:`_classify` returns
    ``CUSTOMISED`` on this state out of caution for the apply path
    (we refuse to "complete" a half-applied state automatically),
    but :func:`remove_patch` can safely drop the canonical half -
    the rag-named entry is unambiguously rag-owned, and leaving it
    behind violates the symmetric-mirror promise. TOML-02.
    """
    index_canonical, index_conflict, index_cc = _classify_indices(doc)
    if index_canonical is None or index_conflict or index_cc:
        return False
    source_canonical, source_conflict, source_cc = _classify_sources(doc)
    if source_canonical is None or source_conflict or source_cc:
        return False
    return index_canonical != source_canonical


def detect_state(pyproject: Path) -> TorchConfigState:
    """Classify the current torch-config block at ``pyproject``.

    Returns one of ``NO_PROJECT_FILE``, ``MISSING``, ``CANONICAL``,
    ``CUSTOMISED``. Pure read; never writes.

    Args:
        pyproject: Path to the consumer's ``pyproject.toml``.

    Raises:
        tomlkit.exceptions.ParseError: If the file is syntactically
            invalid TOML. Callers should surface this as a hard error
            - there is no safe way to edit a corrupt file.
    """
    doc = _load(pyproject)
    if doc is None:
        return TorchConfigState.NO_PROJECT_FILE
    state, _ = _classify(doc)
    return state
