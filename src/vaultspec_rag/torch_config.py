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
from typing import TYPE_CHECKING, Any, Final

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from tomlkit import TOMLDocument
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import AoT, InlineTable, Table
from vaultspec_core.core.helpers import atomic_write

# tomlkit returns ``OutOfOrderTableProxy`` for any ``[tool.X]`` whose
# child tables (``[tool.X.Y]``, ``[tool.X.Z]``) are interleaved with
# unrelated sections — the dominant pyproject.toml shape (e.g.
# ``[tool.uv]``, ``[tool.ruff]``, ``[tool.uv.sources]`` interspersed).
# It implements the same Mapping API we exercise (``get``, ``setdefault``,
# ``__setitem__``, ``__delitem__``, ``__bool__``) but does not subclass
# ``Table``. ``InlineTable`` is the third shape (``sources = { ... }``
# inline form) the reader can encounter at the same surfaces. All
# three expose the same Mapping API; a plain ``isinstance(x, Table)``
# check rejects the others and forces apply / detect onto the wrong
# code path. Treat all three as table-like throughout the module.
#
# ``_TABLE_LIKE_TYPES`` is a plain tuple (no ``Final[tuple[type, ...]]``
# annotation) so static type-checkers (ty/pyright) narrow ``x`` to
# ``Table | OutOfOrderTableProxy | InlineTable`` after
# ``isinstance(x, _TABLE_LIKE_TYPES)``. The matching ``TableLike``
# alias is the union form for return types and parameter annotations.
TableLike = Table | OutOfOrderTableProxy | InlineTable
_TABLE_LIKE_TYPES = (Table, OutOfOrderTableProxy, InlineTable)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "CU130_INDEX_NAME",
    "CU130_INDEX_URL",
    "CU130_MARKER",
    "TORCH_MIN_VERSION",
    "PatchReport",
    "TorchConfigAction",
    "TorchConfigState",
    "TorchDiagnosis",
    "apply_patch",
    "detect_state",
    "diagnose_torch",
    "has_direct_torch_dep",
    "manual_snippet",
    "preview_patch",
    "remove_patch",
]


CU130_INDEX_NAME: Final[str] = "pytorch-cu130"
CU130_INDEX_URL: Final[str] = "https://download.pytorch.org/whl/cu130"
CU130_MARKER: Final[str] = "sys_platform == 'linux' or sys_platform == 'win32'"
# Minimum supported torch version. Surfaced in three places: the
# educational comment in :func:`manual_snippet`, the warning text in
# ``commands._maybe_warn_transitive_dep``, and the README's
# direct-dep example. Extracting the value as a single constant keeps
# the three surfaces in lockstep when PyTorch drops a major version.
TORCH_MIN_VERSION: Final[str] = "2.4"


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


class TorchConfigAction(StrEnum):
    """Closed set of action strings emitted on the install / uninstall
    report's ``torch_config_action`` field.

    The set was historically an open string surface; round-2 audit
    surfaced a JSON-contract gap (the ADR documented 5 values but the
    code emitted 13). Pinning the vocabulary to a ``StrEnum`` makes
    the contract self-documenting and lets static type-checkers catch
    typos. ``StrEnum`` members compare equal to their string value,
    so existing consumers that filter on ``"applied"`` keep working.

    Values:
        APPLIED: cu130 block was just written.
        ALREADY: pyproject is already canonical; nothing to write.
        CONFLICT: a non-canonical cu130 block exists; refused to mutate.
        ABSENT: no pyproject.toml at the target.
        REMOVED: cu130 block was just removed (uninstall side only).
        DISABLED: ``configure_torch=False`` opted out.
        DRY_RUN: dry-run preview, no write.
        DECLINED: user declined the prompt (or a custom confirm hook
            raised an exception we converted to a decline).
        SKIPPED: torch-config step did nothing this run; the report
            field's default before the orchestrator updates it.
        SKIPPED_NON_TTY: non-interactive caller without a confirm hook.
        SKIPPED_EOF: confirmation prompt hit end-of-stream (CI / pipe).
        ERROR: parse or write failure during inspect / patch.
    """

    APPLIED = "applied"
    ALREADY = "already"
    CONFLICT = "conflict"
    ABSENT = "absent"
    REMOVED = "removed"
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    DECLINED = "declined"
    SKIPPED = "skipped"
    SKIPPED_NON_TTY = "skipped-non-tty"
    SKIPPED_EOF = "skipped-eof"
    ERROR = "error"


@dataclass
class PatchReport:
    """Structured outcome of an apply / remove pass.

    Attributes:
        action: A :class:`TorchConfigAction` member describing the
            outcome (``APPLIED``, ``ALREADY``, ``CONFLICT``,
            ``ABSENT``, ``REMOVED``, or ``SKIPPED`` as the default).
            Subclasses ``str``, so legacy consumers comparing with
            string literals (``action == "applied"``) keep working.
        path: The pyproject.toml inspected.
        conflicts: Human-readable descriptions of conflicting keys
            when ``action == TorchConfigAction.CONFLICT``.
        preview: The TOML snippet that would be (or was) written,
            for dry-run / display purposes.
    """

    action: TorchConfigAction
    path: Path
    conflicts: list[str] = field(default_factory=list)
    preview: str = ""


def manual_snippet() -> str:
    """Return the canonical cu130 block as a copy-pasteable string.

    The cu130 portion of the snippet is generated by running the same
    ``_ensure_*`` helpers ``apply_patch`` uses against an empty
    ``tomlkit`` document and serialising the result. The educational
    comment block (about direct-dep promotion under ``uv``) is appended
    as a separate constant. This guarantees byte-equality between the
    snippet and what ``apply_patch`` actually writes — drift between
    the README, install logs, and runtime CPU_ONLY error message is
    structurally impossible.
    """
    doc = tomlkit.document()
    _ensure_tool_uv_index(doc)
    _ensure_torch_source(doc)
    cu130_block = tomlkit.dumps(doc)
    return "\n" + cu130_block + _SNIPPET_DIRECT_DEP_COMMENT


_SNIPPET_DIRECT_DEP_COMMENT: Final[str] = (
    "\n"
    "# uv ignores [tool.uv.sources] for purely-transitive deps.\n"
    f"# Add torch as a direct dep too, e.g. in [project].dependencies\n"
    f'# or [dependency-groups].dev:  "torch>={TORCH_MIN_VERSION}"\n'
)


def _detect_crlf(pyproject: Path) -> bool:
    """Return True when ``pyproject`` uses CRLF line endings on disk.

    Sniffs the raw bytes (not the decoded text) so the answer is the
    real on-disk encoding, immune to ``newline=`` translation. A
    Windows pyproject with ``\\r\\n`` line endings should round-trip
    through apply / remove without losing them — ``tomlkit.dumps``
    always emits LF, so the writer must restore the original
    convention before the atomic write or the user gets a noisy
    git diff that touches every existing line on the very first
    install.
    """
    try:
        return b"\r\n" in pyproject.read_bytes()
    except OSError:
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
    ``[[tool.uv.index]]``) are interleaved with non-uv sections — the
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
    shape we refuse to touch (single-table ``[tool.uv.index]``) —
    the caller should short-circuit to ``CUSTOMISED``.
    """
    conflicts: list[str] = []

    # ``[tool.uv.index]`` (single table) and ``index = [{...}]`` (inline
    # array dotted-key form) are both valid TOML but incompatible with
    # our array-of-tables mutations. Probe the raw key directly —
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
    # array — arrays can only hold inline tables. Treat as
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
        # Half-applied state — treat as customised; we cannot safely
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
    but :func:`remove_patch` can safely drop the canonical half —
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
    report = PatchReport(action=TorchConfigAction.SKIPPED, path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = TorchConfigAction.ABSENT
        return report

    state, conflicts = _classify(doc)
    if state == TorchConfigState.CANONICAL:
        report.action = TorchConfigAction.ALREADY
        return report
    if state == TorchConfigState.CUSTOMISED:
        report.action = TorchConfigAction.CONFLICT
        report.conflicts = conflicts
        return report

    # MISSING → write.
    uses_crlf = _detect_crlf(pyproject)
    original_bytes = pyproject.read_bytes()
    _ensure_tool_uv_index(doc)
    _ensure_torch_source(doc)
    new_text = tomlkit.dumps(doc)
    # Reparse to confirm validity before the write crosses the FS boundary.
    tomlkit.parse(new_text)
    if uses_crlf:
        # tomlkit emits LF; restore the file's original CRLF so the
        # diff stays minimal. tomlkit's parser accepts both endings,
        # so the validation reparse above still applies.
        new_text = new_text.replace("\n", "\r\n")
    # Preserve the file's original trailing-newline shape so both
    # apply and remove are EOF-neutral. Necessary for the ADR's
    # symmetric-mirror byte-equality promise (apply→remove leaves the
    # file byte-identical to the pre-apply content). BEHAV-01.
    new_text = _match_trailing_newline(original_bytes, new_text, uses_crlf=uses_crlf)
    atomic_write(pyproject, new_text)
    report.action = TorchConfigAction.APPLIED
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
    report = PatchReport(action=TorchConfigAction.SKIPPED, path=pyproject)
    doc = _load(pyproject)
    if doc is None:
        report.action = TorchConfigAction.ABSENT
        return report

    state, conflicts = _classify(doc)
    if state == TorchConfigState.MISSING:
        report.action = TorchConfigAction.ABSENT
        return report
    if state == TorchConfigState.CUSTOMISED:
        # Half-applied edge case (one half canonical, the other simply
        # absent — no per-half conflict, no unsupported shape). The
        # default classifier flags this as CUSTOMISED so apply refuses
        # to "complete" it, but the present half IS rag's canonical
        # shape — uninstall can safely drop it. Without this branch
        # uninstall leaves an orphan rag-named entry behind. TOML-02.
        if _is_half_applied(doc):
            # Fall through to the normal CANONICAL→remove path. The
            # per-half drop helpers (``_drop_cu130_index`` /
            # ``_drop_torch_source``) are no-ops on absent halves.
            pass
        else:
            report.action = TorchConfigAction.SKIPPED
            report.conflicts = conflicts
            return report

    # CANONICAL (or half-applied) → remove. Capture the trailing-newline shape pre-read
    # so the symmetric-mirror promise (apply→remove leaves the file
    # byte-identical to the pre-apply content) holds — tomlkit's
    # ``dumps`` always emits a single trailing LF, which can append
    # one extra byte if the original ended without one. BEHAV-01.
    uses_crlf = _detect_crlf(pyproject)
    original_bytes = pyproject.read_bytes()
    _drop_cu130_index(doc)
    _drop_torch_source(doc)
    new_text = tomlkit.dumps(doc)
    tomlkit.parse(new_text)
    if uses_crlf:
        new_text = new_text.replace("\n", "\r\n")
    new_text = _match_trailing_newline(original_bytes, new_text, uses_crlf=uses_crlf)
    atomic_write(pyproject, new_text)
    report.action = TorchConfigAction.REMOVED
    return report


def _match_trailing_newline(
    original_bytes: bytes, new_text: str, *, uses_crlf: bool
) -> str:
    """Restore the original file's trailing-newline shape on ``new_text``.

    tomlkit's ``dumps`` always emits exactly one trailing LF.
    Real-world pyproject files vary: some end with LF, some with two
    LFs (POSIX convention with a blank final line), some with no
    trailing newline at all. Without this normalisation, ``apply →
    remove`` would silently shift the file's terminator shape,
    breaking the ADR's "symmetric mirror — leaves the file byte-
    identical to its pre-apply content" promise.
    """
    eol = "\r\n" if uses_crlf else "\n"
    eol_bytes = b"\r\n" if uses_crlf else b"\n"

    # Count the trailing-newline run on the original (in the chosen
    # eol). Compare with the trailing-newline run on tomlkit's output.
    def _count_trailing(buf: bytes, sep: bytes) -> int:
        n = 0
        while buf.endswith(sep):
            n += 1
            buf = buf[: -len(sep)]
        return n

    original_trail = _count_trailing(original_bytes, eol_bytes)
    new_bytes = new_text.encode("utf-8")
    current_trail = _count_trailing(new_bytes, eol_bytes)
    if current_trail == original_trail:
        return new_text
    # Surgically strip exactly the EOL run tomlkit emitted, then append
    # the original count. ``rstrip("\r\n")`` would over-strip any
    # adjacent CR/LF chars that aren't part of the trailing run; using
    # the counted slice keeps any non-newline trailing whitespace
    # intact (rare in TOML but cheap to preserve).
    stripped = new_text[: -current_trail * len(eol)] if current_trail > 0 else new_text
    return stripped + eol * original_trail


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
    except InvalidRequirement:
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
    except Exception:
        return False, ""
    if doc is None:
        return False, ""
    for label, deps in _iter_dep_lists(doc):
        for entry in deps:
            if _is_torch_requirement(entry):
                return True, label
    return False, ""


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


def _get_or_create_tool_uv(doc: TOMLDocument) -> TableLike:
    """Return the writable ``[tool.uv]`` table, creating it if absent.

    Extracted so :func:`_ensure_tool_uv_index` and
    :func:`_ensure_torch_source` share a single source of truth for
    how the ``[tool]`` → ``[tool.uv]`` hierarchy is materialised.
    Raises if either level exists but isn't a table (refuses to
    silently clobber a user-owned key).

    Accepts both :class:`tomlkit.items.Table` and
    :class:`tomlkit.container.OutOfOrderTableProxy`. Both expose the
    Mapping API we exercise here (``setdefault`` / ``__setitem__``);
    the proxy is what tomlkit returns whenever ``[tool.X]`` sub-tables
    are interleaved with unrelated sections.
    """
    tool = doc.setdefault("tool", tomlkit.table())
    if not isinstance(tool, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool] is not a table")
    uv = tool.setdefault("uv", tomlkit.table())
    if not isinstance(uv, _TABLE_LIKE_TYPES):
        raise TypeError("pyproject.toml [tool.uv] is not a table")
    return uv


def _ensure_tool_uv_index(doc: TOMLDocument) -> None:
    """Append ``[[tool.uv.index]]`` with the canonical cu130 entry.

    Creates ``[tool]`` and ``[tool.uv]`` if absent. Appends to the
    existing array-of-tables if one is present.
    """
    uv = _get_or_create_tool_uv(doc)
    existing = uv.get("index")
    entry = tomlkit.table()
    entry["name"] = CU130_INDEX_NAME
    entry["url"] = CU130_INDEX_URL
    entry["explicit"] = True

    if existing is None:
        # Fresh AoT — tomlkit already inserts a trailing blank line
        # before the next top-level section, so no manual trivia
        # override is needed.
        aot = tomlkit.aot()
        aot.append(entry)
        uv["index"] = aot
        return

    # Defensive: _classify already rejects single-table forms as
    # CUSTOMISED so apply_patch never reaches this function in that
    # case. Guard anyway — silently-wrong mutation is the worst
    # outcome for a user-owned file.
    if not isinstance(existing, AoT | list):
        raise TypeError(
            "pyproject.toml [tool.uv.index] is not an array-of-tables; "
            "refuse to mutate to avoid producing invalid TOML"
        )
    # Appending to an existing AoT: set a trailing blank line on the
    # last key's value-trivia so the appended block visually separates
    # from the next top-level section. Without this, the new block
    # lands flush against the following section header and produces
    # a noisy git diff that breaks the "preserve user formatting"
    # reason for using tomlkit. TOML-04.
    last_value = entry.value._body[-1][1]
    last_value.trivia.trail = "\n\n"
    existing.append(entry)


def _ensure_torch_source(doc: TOMLDocument) -> None:
    """Ensure ``[tool.uv.sources]`` has a cu130 torch entry.

    Accepts ``InlineTable`` symmetric with :func:`_torch_sources` and
    :func:`_drop_torch_source`. Without it, a project that wrote
    ``sources = { … }`` inline classifies as MISSING via the inline-
    aware detector, then crashes here with TypeError when apply tries
    to mutate.
    """
    uv = _get_or_create_tool_uv(doc)
    sources = uv.setdefault("sources", tomlkit.table())
    if not isinstance(sources, _TABLE_LIKE_TYPES):
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

    # Promotion: existing single inline-table → array of two inline
    # tables. Only valid when `current` is an InlineTable; a standard
    # Table (e.g. ``[tool.uv.sources.torch]`` section form) cannot be
    # nested inside a TOML array. _classify already rejects that
    # shape as CUSTOMISED; guard anyway for defence-in-depth.
    if not isinstance(current, InlineTable):
        raise TypeError(
            "pyproject.toml [tool.uv.sources] torch is a standard "
            "table; refuse to promote into an inline-table array "
            "(would produce invalid TOML)"
        )
    arr = tomlkit.array()
    arr.append(current)
    arr.append(inline)
    arr.multiline(True)
    sources["torch"] = arr


def _drop_cu130_index(doc: TOMLDocument) -> None:
    """Remove the canonical cu130 entry from ``[[tool.uv.index]]``.

    OutOfOrderTableProxy quirk applies here too: re-fetch ``uv`` via
    :func:`_tool_uv` immediately before ``del uv["index"]`` instead of
    holding a stale reference, so a freshly-constructed proxy carries
    consistent internal table positions.
    """
    indices = _indices(doc)
    if indices is None:
        return
    # Iterate backwards and pop in-place so user trivia (comments,
    # blank lines, custom formatting between tables) in the kept
    # entries is preserved. Rebuilding the AoT from scratch would
    # strip that metadata.
    for i in range(len(indices) - 1, -1, -1):
        entry = indices[i]
        if isinstance(entry, Table | InlineTable | dict) and _index_match(entry) == (
            "canonical"
        ):
            indices.pop(i)
    if len(indices) == 0:
        uv = _tool_uv(doc)
        if uv is not None:
            del uv["index"]


def _drop_torch_source(doc: TOMLDocument) -> None:
    """Remove the canonical cu130 torch entry from ``[tool.uv.sources]``.

    Always runs the end-of-function cleanup that drops empty
    ``sources`` / ``uv`` / ``tool`` tables, even when ``torch`` was
    never present or was a single-entry deletion. This matters after
    :func:`_drop_cu130_index` has already removed the index table —
    both callers run in sequence and the consumer file should end up
    without orphaned empty sections.

    OutOfOrderTableProxy quirk: tomlkit's proxy memoises the position
    of the underlying tables on construction; a ``__delitem__`` on it
    invalidates those positions and a second ``__delitem__`` against
    the SAME proxy can raise ``IndexError``. We work around it by
    re-fetching the proxy from its parent before each cascade-stage
    deletion (``del uv["sources"]`` → re-fetch → ``del tool["uv"]``).
    """
    uv = _tool_uv(doc)
    if uv is None:
        return
    sources = uv.get("sources")

    # Process the torch entry only when sources is present and
    # shaped as a table. The early-return anti-pattern is avoided:
    # even when sources is absent, the cleanup cascade below must
    # run so that an empty ``[tool.uv]`` left behind by
    # :func:`_drop_cu130_index` gets dropped. ``InlineTable`` covers
    # the ``sources = { torch = [...] }`` inline form symmetric with
    # :func:`_torch_sources` so remove honours every detect-classified
    # CANONICAL shape.
    if isinstance(sources, _TABLE_LIKE_TYPES):
        torch_entry = sources.get("torch")
        if torch_entry is not None:
            if isinstance(torch_entry, InlineTable | dict) and not isinstance(
                torch_entry, list
            ):
                if _source_match(torch_entry) == "canonical":
                    del sources["torch"]
            elif isinstance(torch_entry, list):
                # Array-of-inline-tables form. Iterate backwards and
                # pop in-place to preserve inline comments and
                # formatting on non-canonical entries; rebuilding
                # the array from a kept list would strip that trivia.
                for i in range(len(torch_entry) - 1, -1, -1):
                    e = torch_entry[i]
                    if isinstance(e, InlineTable | dict) and (
                        _source_match(e) == "canonical"
                    ):
                        torch_entry.pop(i)
                if len(torch_entry) == 0:
                    del sources["torch"]

        if not sources:
            # Re-fetch ``uv`` before the cascade-stage delete —
            # ``_drop_cu130_index`` may have already mutated this same
            # proxy via ``del uv["index"]``. See the OutOfOrderTableProxy
            # note in this function's docstring.
            uv = _tool_uv(doc)
            if uv is not None:
                del uv["sources"]

    # Cleanup cascades: always try to drop empty parent tables so a
    # full uninstall (index + torch) leaves no orphaned sections.
    # Re-fetch ``uv`` again so the emptiness check runs on a fresh
    # proxy with consistent internal state.
    uv = _tool_uv(doc)
    if uv is not None and not uv:
        tool = doc.get("tool")
        if isinstance(tool, _TABLE_LIKE_TYPES):
            del tool["uv"]
            if not tool:
                del doc["tool"]
