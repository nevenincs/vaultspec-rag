"""Guards that the configuration reference cannot drift from the settings.

The reference page restates a name, a type, and a default for every knob. Every
one of those is a copy, and a copy with no check on it rots: the page shipped a
CUDA ceiling of 12288 long after the real default became 0 (auto-derive), and
listed six model knobs as reading no environment variable long after all six
gained one. A reader who trusts a stale table configures the wrong thing and
gets no error.

So the page is not merely correct here, it is checked. These tests read the
committed markdown and compare it against the live settings object, both
directions: nothing documented that the settings do not declare, nothing
declared that the page omits, and no restated type or default that disagrees.
The split between generically-resolved knobs and the ones parsed at their own
call site is derived from the override map, never from a list kept here, so a
knob moving across that boundary fails a test instead of quietly changing
meaning.

Each assertion below names the mutation it catches. Every one of those
mutations was run: the reference page broken one way at a time, the named test
run alone, observed to fail on the assertion it names, the page restored from a
copy held outside the repository, the test re-run and observed to pass. One
uninterrupted sequence, so no mutation outlived it on disk.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from ..config._schema import _ENV_OVERRIDE_MAP
from ..config._settings import VaultSpecConfigWrapper
from ..config._types import EnvVar
from .constants import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DOC = PROJECT_ROOT / "docs" / "configuration.md"

#: Heading of the section documenting the knobs that bypass the generic
#: resolution chain. Its membership is asserted against the override map.
_EXCEPTIONS_HEADING = "Variables with their own parsing rules"

#: Heading of the section documenting settings keys with no environment
#: variable at all.
_CONFIG_ONLY_HEADING = "Config-only keys"

_PREFIX = "VAULTSPEC_RAG_"
_CODE_SPAN = re.compile(r"`([^`]+)`")

_DEFAULTS: dict[str, Any] = VaultSpecConfigWrapper._RAG_DEFAULTS  # pyright: ignore[reportPrivateUsage]
_SETTINGS_KEY_BY_ENV: dict[str, str] = {
    member.value: key for key, member in _ENV_OVERRIDE_MAP.items()
}

pytestmark.append(
    pytest.mark.skipif(
        not _DOC.is_file(),
        reason="configuration reference is not shipped in the installed package",
    )
)


def _rows(doc: Path) -> list[tuple[str, list[str]]]:
    """Return ``(heading, cells)`` for every markdown table row in *doc*."""
    heading = ""
    parsed: list[tuple[str, list[str]]] = []
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue
        parsed.append((heading, cells))
    return parsed


def _variable_rows(doc: Path) -> dict[str, tuple[str, list[str]]]:
    """Return ``env var -> (heading, cells)`` for every documented variable."""
    found: dict[str, tuple[str, list[str]]] = {}
    for heading, cells in _rows(doc):
        match = _CODE_SPAN.fullmatch(cells[0])
        if match is None or not match.group(1).startswith(_PREFIX):
            continue
        found[match.group(1)] = (heading, cells)
    return found


def _config_only_rows(doc: Path) -> dict[str, list[str]]:
    """Return ``settings key -> cells`` for the config-only table."""
    found: dict[str, list[str]] = {}
    for heading, cells in _rows(doc):
        if heading != _CONFIG_ONLY_HEADING:
            continue
        match = _CODE_SPAN.fullmatch(cells[0])
        if match is not None:
            found[match.group(1)] = cells
    return found


def _declared() -> set[str]:
    """Every ``VAULTSPEC_RAG_*`` name the settings enum declares."""
    return {m.value for m in EnvVar if m.value.startswith(_PREFIX)}


def _default_agrees(documented: str, actual: object) -> bool:
    """Whether a Default cell states *actual*.

    ``None`` is written bare as ``none``; every other value is the first code
    span in the cell, so a trailing annotation such as ``(8 MiB)`` is free
    prose. Numbers compare numerically, so ``300`` states ``300.0``.
    """
    if actual is None:
        return documented == "none"
    span = _CODE_SPAN.search(documented)
    if span is None:
        return False
    token = span.group(1)
    if isinstance(actual, bool):
        return token in {"0", "1"} and (token == "1") is actual
    if isinstance(actual, (int, float)):
        try:
            return float(token) == float(actual)
        except ValueError:
            return False
    return token == actual


def _type_words(actual: object) -> set[str]:
    """Type words admissible for a default of *actual*'s type."""
    if isinstance(actual, bool):
        return {"boolean"}
    if isinstance(actual, int):
        return {"integer"}
    if isinstance(actual, float):
        return {"float"}
    # A ``None`` default is still set as text; path-like knobs say so.
    return {"string", "path"}


def test_every_documented_variable_is_a_declared_setting() -> None:
    """No table may name a variable the settings enum does not declare.

    Mutation: renamed a documented row to ``VAULTSPEC_RAG_INDEX_CUDA_CEILING``
    (a plausible near-miss of a real member). Observed this assertion fail
    naming that one variable.
    """
    undeclared = sorted(set(_variable_rows(_DOC)) - _declared())
    assert not undeclared, (
        "the configuration reference documents variables the settings enum "
        f"does not declare, so they configure nothing: {undeclared}"
    )


def test_every_declared_variable_is_documented() -> None:
    """Every declared variable must appear in the reference.

    Mutation: deleted the ``VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MB`` row - the
    omission shape the page shipped for eight variables at once. Observed this
    assertion fail naming that variable.
    """
    undocumented = sorted(_declared() - set(_variable_rows(_DOC)))
    assert not undocumented, (
        "the settings enum declares variables the configuration reference "
        f"never mentions, so operators cannot discover them: {undocumented}"
    )


def test_documented_defaults_match_the_shipped_defaults() -> None:
    """Every restated default must equal the value the settings ship.

    Mutation: restored the stale ``12288`` as the documented
    ``VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB`` default - the exact defect this
    page shipped. Observed this assertion fail naming that variable, its
    documented value and its real one.
    """
    wrong: dict[str, str] = {}
    for name, (_, cells) in sorted(_variable_rows(_DOC).items()):
        key = _SETTINGS_KEY_BY_ENV.get(name)
        if key is None:
            continue
        actual = _DEFAULTS[key]
        if not _default_agrees(cells[2], actual):
            wrong[name] = f"documented {cells[2]!r}, ships {actual!r}"
    assert not wrong, (
        "the configuration reference states defaults the settings do not "
        f"ship, so following it configures something else: {wrong}"
    )


def test_documented_types_match_the_shipped_defaults() -> None:
    """Every restated type must match how the loader coerces the value.

    Mutation: relabelled ``VAULTSPEC_RAG_WATCH_COOLDOWN_S`` as ``integer``
    while it ships a float, the shape that tells an operator a fractional
    value is unavailable. Observed this assertion fail naming that variable.
    """
    wrong: dict[str, str] = {}
    for name, (_, cells) in sorted(_variable_rows(_DOC).items()):
        key = _SETTINGS_KEY_BY_ENV.get(name)
        if key is None:
            continue
        admissible = _type_words(_DEFAULTS[key])
        if cells[1] not in admissible:
            wrong[name] = f"documented {cells[1]!r}, expected one of {admissible}"
    assert not wrong, (
        "the configuration reference states types the loader does not coerce "
        f"to, so a documented value may not parse: {wrong}"
    )


def test_the_exceptions_section_holds_exactly_the_bypassing_variables() -> None:
    """Membership of the exceptions section is decided by the override map.

    A variable resolved through the map follows the documented boolean and
    numeric rules; one outside it does not, and says so in its own section.
    A knob crossing that boundary silently changes what the page promises
    about it.

    Mutation: moved the ``VAULTSPEC_RAG_STDIO_WATCHDOG`` row into the
    preprocessing table, leaving its ``0/false/off/no`` rule filed under the
    generic boolean rule that would read ``off`` as false. Observed this
    assertion fail naming that variable as missing from the section.
    """
    documented = {
        name
        for name, (heading, _) in _variable_rows(_DOC).items()
        if heading == _EXCEPTIONS_HEADING
    }
    expected = _declared() - set(_SETTINGS_KEY_BY_ENV)
    assert documented == expected, (
        "the section for variables parsed at their own call site disagrees "
        "with the settings override map; a variable in the map follows the "
        "generic coercion rules and one outside it does not: "
        f"documented-only={sorted(documented - expected)}, "
        f"map-says-also={sorted(expected - documented)}"
    )


def test_config_only_table_lists_exactly_the_keys_with_no_env_var() -> None:
    """The config-only table must equal the keys the override map omits.

    Mutation: added ``embedding_model`` back to the table - the exact defect
    this page shipped, six keys listed as reading no environment variable
    after all six gained one. Observed this assertion fail naming that key as
    documented-only.
    """
    documented = set(_config_only_rows(_DOC))
    expected = set(_DEFAULTS) - set(_ENV_OVERRIDE_MAP)
    assert documented == expected, (
        "the config-only table disagrees with the settings override map, so "
        "it tells operators a key is unreachable from the environment when it "
        f"is not (or the reverse): documented-only={sorted(documented - expected)}, "
        f"missing={sorted(expected - documented)}"
    )


def test_config_only_defaults_match_the_shipped_defaults() -> None:
    """The config-only table restates defaults too, so check them as well.

    Mutation: changed the documented ``document_chunk_overlap_chars`` default
    from 256 to 512. Observed this assertion fail naming that key.
    """
    wrong: dict[str, str] = {}
    for key, cells in sorted(_config_only_rows(_DOC).items()):
        actual = _DEFAULTS.get(key)
        if not _default_agrees(cells[2], actual):
            wrong[key] = f"documented {cells[2]!r}, ships {actual!r}"
    assert not wrong, (
        f"the config-only table states defaults the settings do not ship: {wrong}"
    )
